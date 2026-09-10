"""
F:\\stock 研判系統準確度回測（Point-in-Time，零未來資料）

作法：不修改任何 production 程式，改以 monkeypatch 把 kline.py 的所有資料抓取函式
換成「只回傳 cutoff 日期（含）以前」的歷史切片，然後逐日呼叫真正的 kline.analyze_stock()，
記錄它在當天實際會輸出的綜合評分與決策（建議買入／持有／觀望／賣出），
再比對後續 5／10／20／60 交易日的實際報酬。

用法：
    python backtest_accuracy.py --months 1 --step 1          # production 預設路徑
    python backtest_accuracy.py --months 12 --step 5         # 餵足歷史的對照組
"""
import os, sys, argparse, pickle, warnings
from datetime import timedelta
import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

warnings.filterwarnings("ignore")
sys.path.insert(0, r"F:\stock")

import kline

CACHE = os.environ.get("BT_CACHE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache"))

# ── 目前受測股票的 point-in-time 狀態 ────────────────────────────
S = {"px": None, "inst": None, "rev": None, "fs": None, "cut": None, "market": "tse"}


# ── 1. 價格：模擬 kline 的三條抓取路徑 ──────────────────────────
def _rows(start, cut):
    px = S["px"]
    m = (px["date"] >= pd.Timestamp(start)) & (px["date"] <= pd.Timestamp(cut))
    return px.loc[m, ["date", "open", "high", "low", "close", "volume"]].to_dict("records")


def patched_fetch_twse(ticker, months):
    # 比照原始實作：TWSE 以「整月區塊」抓取，實際起點為 (cutoff - months) 當月 1 日
    cut = S["cut"]
    return _rows((cut - relativedelta(months=months)).replace(day=1), cut)


def patched_fetch_from_yfinance(sym, months):
    cut = S["cut"]
    return _rows(cut - relativedelta(months=months), cut)


def patched_fetch_otc(ticker, months):
    return patched_fetch_from_yfinance(ticker + ".TWO", months)


class _FakeYF:
    """供 evaluate_composite_rating 在資料不足 200 筆時的 15mo 長期補抓路徑使用"""
    @staticmethod
    def download(sym, period=None, start=None, end=None, progress=False, **kw):
        cut = S["cut"]
        if period and str(period).endswith("mo"):
            begin = cut - relativedelta(months=int(str(period)[:-2]))
        elif start:
            begin = pd.Timestamp(start)
        else:
            begin = cut - relativedelta(months=15)
        px = S["px"]
        m = (px["date"] >= pd.Timestamp(begin)) & (px["date"] <= pd.Timestamp(cut))
        sub = px.loc[m].set_index("date")[["open", "high", "low", "close", "volume"]]
        sub.columns = ["Open", "High", "Low", "Close", "Volume"]
        return sub

    @staticmethod
    def Ticker(sym):
        class _T:
            info = {}
        return _T()


# ── 2. 三大法人：只給 cutoff 當日（含）以前已公告的資料 ──────────
def patched_fetch_institutional(ticker, market, days=5):
    inst = S["inst"]
    if inst is None or len(inst) == 0:
        return pd.DataFrame()
    sub = inst[inst["date"] <= pd.Timestamp(S["cut"])].tail(days).reset_index(drop=True)
    return sub if len(sub) else pd.DataFrame()


# ── 3. 基本面：依實際公告落後期過濾，其餘解析邏輯完全比照 kline ──
_FS_LAG = {3: 45, 6: 45, 9: 45, 12: 90}   # Q1/Q2/Q3 約 45 天後公告、Q4 年報約 90 天


def _fs_available(rec, cut):
    d = pd.Timestamp(rec["date"])
    return d + timedelta(days=_FS_LAG.get(d.month, 60)) <= pd.Timestamp(cut)


def patched_fetch_fundamentals(ticker, market="tse"):
    cut = pd.Timestamp(S["cut"])
    res = {"per": None, "pbr": None, "dividend_yield": None, "eps_ttm": None,
           "latest_eps": None, "latest_quarter": "", "gross_margin": None,
           "operating_margin": None, "latest_revenue_val": None, "revenue_date": "",
           "revenue_yoy": None, "has_data": False}

    # 財報：比照原始 start_date = now - 18 個月，且僅取當下已公告者
    fs_start = cut - relativedelta(years=1, months=6)
    fs_data = [x for x in (S["fs"] or [])
               if pd.Timestamp(x["date"]) >= fs_start and _fs_available(x, cut)]
    if fs_data:
        eps_list = sorted([x for x in fs_data if x.get("type") == "EPS"], key=lambda x: x["date"])
        if eps_list:
            res["latest_eps"] = eps_list[-1]["value"]
            res["latest_quarter"] = eps_list[-1]["date"][:7]
            res["eps_ttm"] = round(sum(x["value"] for x in eps_list[-4:]), 2)
            res["has_data"] = True
            latest_date = eps_list[-1]["date"]
            q = {x["type"]: x["value"] for x in fs_data if x.get("date") == latest_date}
            rev, gp, op = q.get("Revenue", 0), q.get("GrossProfit", 0), q.get("OperatingIncome", 0)
            if rev and rev > 0:
                res["gross_margin"] = round(gp / rev * 100, 1)
                res["operating_margin"] = round(op / rev * 100, 1)

    # 月營收：比照原始 start_date = now - 14 個月；FinMind date 已是次月，再加 10 天公告緩衝
    rev_start = cut - relativedelta(months=14)
    rev_data = [x for x in (S["rev"] or [])
                if pd.Timestamp(x["date"]) >= rev_start
                and pd.Timestamp(x["date"]) + timedelta(days=10) <= cut]
    rev_data = sorted(rev_data, key=lambda x: (x["revenue_year"], x["revenue_month"]))
    if len(rev_data) >= 12:
        latest_r = rev_data[-1]
        same = [x for x in rev_data[:-1] if x.get("revenue_month") == latest_r.get("revenue_month")]
        if same and same[-1].get("revenue", 0) > 0:
            ly = same[-1]
            res["revenue_yoy"] = round((latest_r["revenue"] - ly["revenue"]) / ly["revenue"] * 100, 2)
        res["latest_revenue_val"] = round(latest_r["revenue"] / 1e8, 1)
        res["revenue_date"] = str(latest_r["revenue_year"]) + "/" + str(latest_r["revenue_month"])
        res["has_data"] = True
    return res


def load_alert_checker():
    """載入 LINE Bot 實際推播用的 BPA 底部買點雷達（monitor_worker），一併驗證其命中率"""
    try:
        import logging
        import monitor_worker
        logging.getLogger("monitor_worker").setLevel(logging.ERROR)  # 回測不需要逐日攔截日誌
        logging.getLogger().setLevel(logging.ERROR)
        return monitor_worker.check_bottom_confirmation_signals
    except Exception as e:
        print("[WARN] 無法載入 monitor_worker，略過推播訊號驗證：%s" % e)
        return None


def install_patches():
    kline.fetch_twse = patched_fetch_twse
    kline.fetch_from_yfinance = patched_fetch_from_yfinance
    kline.fetch_otc = patched_fetch_otc
    kline.fetch_institutional = patched_fetch_institutional
    kline.fetch_fundamentals = patched_fetch_fundamentals
    kline.fetch_realtime_bar = lambda ticker, market: None      # 回測一律盤後定盤
    kline.build_stock_chart = lambda *a, **k: None              # 不畫圖，純加速
    kline.get_info = lambda t: (S["market"], t)                 # 免打 twstock，市場別取自快取
    kline.yf = _FakeYF

    # 同步 monkeypatch core/ 模組（避免模組層級已快取原函式）
    import core.data_fetch as c_df
    import core.analyzer as c_an
    import core.rating as c_rt
    import core.indicators as c_ind
    import core.market_regime as c_mr

    for mod in (c_df, c_an):
        mod.fetch_twse = patched_fetch_twse
        mod.fetch_from_yfinance = patched_fetch_from_yfinance
        mod.fetch_otc = patched_fetch_otc
        mod.fetch_institutional = patched_fetch_institutional
        mod.fetch_fundamentals = patched_fetch_fundamentals
        mod.fetch_realtime_bar = lambda ticker, market: None
        mod.get_info = lambda t: (S["market"], t)
        mod.yf = _FakeYF

    c_rt.yf = _FakeYF

    # 載入大盤歷史資料以提供零未來資訊的 Point-in-Time 大盤體系判定
    twii_path = os.path.join(CACHE, "TWII.pkl")
    twii_df = None
    if os.path.exists(twii_path):
        try:
            with open(twii_path, "rb") as f:
                twii_df = pickle.load(f)
        except Exception as e:
            print(f"[WARN] 無法載入 TWII.pkl: {e}")

    def patched_get_market_regime_status(force_refresh=False):
        cut = S.get("cut")
        if twii_df is None or cut is None:
            return {
                "is_market_bear": False, "market_score": 70, "twii_close": 0.0,
                "twii_ma20": 0.0, "twii_ma60": 0.0, "twii_ma60_slope": 0.0,
                "status_desc": "大盤數據離線（常態多頭）"
            }
        sub = twii_df[twii_df.index <= pd.Timestamp(cut)]
        if len(sub) < 65:
            return {
                "is_market_bear": False, "market_score": 70, "twii_close": 0.0,
                "twii_ma20": 0.0, "twii_ma60": 0.0, "twii_ma60_slope": 0.0,
                "status_desc": "數據不足 65 根"
            }
        c = sub["close"]
        ma20 = c.rolling(20).mean().iloc[-1]
        ma60 = c.rolling(60).mean().iloc[-1]
        ma60_10d = c.rolling(60).mean().iloc[-11]
        c_now = float(c.iloc[-1])
        slope = (ma60 - ma60_10d) / (ma60_10d + 1e-9) * 100
        is_bear = (c_now < ma60 * 0.99 and slope < 0) or (c_now < ma60 * 0.97)
        return {
            "is_market_bear": bool(is_bear),
            "market_score": 35 if is_bear else 85,
            "twii_close": round(c_now, 2),
            "twii_ma20": round(float(ma20), 2),
            "twii_ma60": round(float(ma60), 2),
            "twii_ma60_slope": round(float(slope), 2),
            "status_desc": "熊市防禦模式" if is_bear else "多方主控"
        }

    c_mr.get_market_regime_status = patched_get_market_regime_status
    c_an.get_market_regime_status = patched_get_market_regime_status
    c_rt.get_market_regime_status = patched_get_market_regime_status
    c_ind.get_market_regime_status = patched_get_market_regime_status


# ── 4. 前瞻報酬（含息；T+1 開盤進場為可交易情境） ────────────────
def add_forward(px):
    f = (px["adj_close"] / px["close"]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    px["adj_open"] = px["open"] * f
    px["adj_high"] = px["high"] * f
    px["adj_low"] = px["low"] * f
    px["entry_next_open"] = px["adj_open"].shift(-1)
    for h in (5, 10, 20, 60):
        px["ret_c%d" % h] = px["adj_close"].shift(-h) / px["adj_close"] - 1.0        # 收→收（純訊號）
        px["ret_t1_%d" % h] = px["adj_close"].shift(-h) / px["entry_next_open"] - 1.0  # T+1 開盤進場
    # 20 日內先觸及 -7%（LINE bot 硬停損）或先觸及 +7%
    lo, hi, ent = px["adj_low"].values, px["adj_high"].values, px["entry_next_open"].values
    n = len(px)
    dn_arr = np.full(n, np.nan)
    up_arr = np.full(n, np.nan)
    for i in range(n):
        e = ent[i]
        if not np.isfinite(e) or i + 21 >= n:
            continue
        dn = up = 0
        for j in range(i + 1, min(i + 21, n)):
            if lo[j] <= e * 0.93:
                dn = 1
                break
            if hi[j] >= e * 1.07:
                up = 1
                break
        dn_arr[i], up_arr[i] = dn, up
    px["stop7_first_20d"] = dn_arr
    px["tp7_first_20d"] = up_arr
    return px


# ── 5. 主回測迴圈 ────────────────────────────────────────────────
def run(tickers, months, step, start_date, out_path, verbose=True, with_alert=False):
    install_patches()
    alert_fn = load_alert_checker() if with_alert else None
    rows = []
    for ti, t in enumerate(tickers, 1):
        p = os.path.join(CACHE, t + ".pkl")
        if not os.path.exists(p):
            print("[SKIP] %s 無快取" % t)
            continue
        with open(p, "rb") as f:
            d = pickle.load(f)
        px = add_forward(d["price"].copy())
        S.update(px=px, inst=d.get("inst"), rev=d.get("revenue"), fs=d.get("fs"),
                 market=d.get("market", "tse"))

        # 暖身：Minervini 需 250 交易日、月營收 YoY 需 14 個月 → 至少 300 根
        idx0 = max(300, int((px["date"] < pd.Timestamp(start_date)).sum()))
        last = len(px) - 61            # 保留 60 日前瞻空間
        ok = err = 0
        for i in range(idx0, last, step):
            S["cut"] = px["date"].iloc[i].to_pydatetime()
            try:
                res = kline.analyze_stock(t, months=months, generate_html=False,
                                          print_report=False, quick_mode=False)
            except Exception as e:
                err += 1
                if err <= 3 and verbose:
                    print("    [ERR] %s %s %s: %s" % (t, S["cut"].date(), type(e).__name__, e))
                continue
            df_sig = res["df"]
            # 一致性檢核：引擎最後一根 K 棒必須正好是 cutoff 當天
            if pd.Timestamp(df_sig["date"].iloc[-1]).normalize() != pd.Timestamp(S["cut"]).normalize():
                err += 1
                continue
            cr = res.get("composite_rating") or {}
            bpa = res.get("bpa_res") or {}
            fu = res.get("fundamentals") or {}
            inst_df = res.get("inst_df")
            r = {
                "ticker": t, "market": d.get("market"), "date": px["date"].iloc[i],
                "months": months, "bars_used": len(df_sig),
                "score": cr.get("score"), "action": cr.get("action_type"),
                "is_stage4": 1 if cr.get("is_stage4_bear") else 0,
                "is_market_bear": 1 if (res.get("market_regime") or {}).get("is_market_bear") else 0,
                "minervini": cr.get("minervini_passed"),
                "canslim": (cr.get("canslim_grade") or "")[:2].strip(),
                "bpa": bpa.get("always_in_zh"),
                "trend_score": res.get("trend_score"),
                "trend_stage": res.get("trend_stage"),
                "vol_score": (res.get("vol_eval") or {}).get("score"),
                "inst5d": int(inst_df["total"].sum()) if (inst_df is not None and len(inst_df)) else 0,
                "close": float(px["close"].iloc[i]),
                "eps_ttm": fu.get("eps_ttm"), "rev_yoy": fu.get("revenue_yoy"),
                "gross_margin": fu.get("gross_margin"),
            }
            if alert_fn is not None:
                try:
                    al = alert_fn(t, market=d.get("market", "tse"), analysis_res=res) or {}
                except Exception:
                    al = {}
                r["alert"] = 1 if al.get("triggered") else 0
                r["alert_name"] = (al.get("signal_name") or "")[:24]
            for h in (5, 10, 20, 60):
                r["ret_c%d" % h] = px["ret_c%d" % h].iloc[i]
                r["ret_t1_%d" % h] = px["ret_t1_%d" % h].iloc[i]
            r["stop7_first_20d"] = px["stop7_first_20d"].iloc[i]
            r["tp7_first_20d"] = px["tp7_first_20d"].iloc[i]
            rows.append(r)
            ok += 1
        if verbose:
            print("[%d/%d] %s (%s) 產生 %d 筆訊號%s"
                  % (ti, len(tickers), t, d.get("market"), ok, ("，%d 筆失敗" % err) if err else ""))
            sys.stdout.flush()
    out = pd.DataFrame(rows)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print("\n[OK] 共 %d 筆 → %s" % (len(out), out_path))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=1,
                    help="餵給 analyze_stock 的歷史月數（production 預設 1）")
    ap.add_argument("--step", type=int, default=1, help="每隔幾個交易日取樣一次")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--with-alert", action="store_true",
                    help="一併驗證 LINE Bot 實際推播的 BPA 底部買點雷達")
    a = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from fetch_history import UNIVERSE
    tk = [x for x in a.tickers.split(",") if x] or UNIVERSE
    outp = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "signals_m%d_s%d.csv" % (a.months, a.step))
    run(tk, a.months, a.step, a.start, outp, with_alert=a.with_alert)
