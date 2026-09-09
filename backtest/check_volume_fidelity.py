"""
資料源保真度檢核：回測價格取自 yfinance（OHLC 與 TWSE 完全相同），
但 yfinance 的成交量約為 TWSE 官方成交量的 85%（且比例逐日浮動，
Yahoo 未計入盤後定價／零股／鉅額等），量價評分與帶量突破判定可能受影響。

本腳本以同一段期間、同一引擎，分別餵入 TWSE 官方成交量與 yfinance 成交量，
直接量測最終決策（action）與綜合評分（score）的差異比率。

用法：python check_volume_fidelity.py 2330 3042
"""
import sys, os, pickle
import pandas as pd

sys.path.insert(0, r"F:\stock")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kline
import backtest_accuracy as bt

MONTHS_FETCH = 24
ORIG_FETCH_TWSE = kline.fetch_twse   # 先留存原始函式，避免被 install_patches 取代


def build_twse_px(ticker, yf_px):
    rec = ORIG_FETCH_TWSE(ticker, MONTHS_FETCH)
    if not rec:
        return None
    t = pd.DataFrame(rec)
    t["date"] = pd.to_datetime(t["date"])
    t = t.dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)
    # 用 yfinance 的還原因子補上 adj_close（僅用於前瞻報酬，不進訊號引擎）
    m = t.merge(yf_px[["date", "close", "adj_close"]], on="date", how="left",
                suffixes=("", "_yf"))
    m["adj_close"] = m["close"] * (m["adj_close"] / m["close_yf"]).fillna(1.0)
    return m[["date", "open", "high", "low", "close", "adj_close", "volume"]]


def main():
    tickers = sys.argv[1:] or ["2330"]
    rows = []
    for t in tickers:
        with open(os.path.join(bt.CACHE, t + ".pkl"), "rb") as f:
            d = pickle.load(f)
        yf_px = d["price"]
        print("[%s] 抓取 TWSE 官方 %d 個月原始資料..." % (t, MONTHS_FETCH))
        tw_px = build_twse_px(t, yf_px)
        if tw_px is None or len(tw_px) < 320:
            print("    [SKIP] TWSE 資料不足")
            continue
        print("    TWSE %d 筆 %s ~ %s" % (len(tw_px), tw_px["date"].iloc[0].date(),
                                          tw_px["date"].iloc[-1].date()))
        bt.install_patches()
        # 測試日期取 TWSE 資料的第 300 根之後（確保 Minervini 15mo 補抓路徑有料）
        dates = tw_px["date"].iloc[300:len(tw_px) - 1].tolist()
        both = {}
        for tag, px in (("twse", tw_px), ("yf", yf_px)):
            pxf = bt.add_forward(px.copy())
            bt.S.update(px=pxf, inst=d.get("inst"), rev=d.get("revenue"), fs=d.get("fs"),
                        market=d.get("market", "tse"))
            out = {}
            for dt in dates:
                if dt not in set(pxf["date"]):
                    continue
                bt.S["cut"] = pd.Timestamp(dt).to_pydatetime()
                try:
                    res = kline.analyze_stock(t, months=1, generate_html=False,
                                              print_report=False, quick_mode=False)
                except Exception:
                    continue
                cr = res.get("composite_rating") or {}
                out[dt] = (cr.get("score"), cr.get("action_type"),
                           (res.get("vol_eval") or {}).get("status"))
            both[tag] = out
        common = sorted(set(both["twse"]) & set(both["yf"]))
        same_act = sum(1 for x in common if both["twse"][x][1] == both["yf"][x][1])
        same_sc = sum(1 for x in common if both["twse"][x][0] == both["yf"][x][0])
        same_vs = sum(1 for x in common if both["twse"][x][2] == both["yf"][x][2])
        dsc = [abs((both["twse"][x][0] or 0) - (both["yf"][x][0] or 0)) for x in common]
        print("    比對 %d 日 ｜決策相同 %.1f%% ｜評分相同 %.1f%% ｜量價狀態相同 %.1f%% ｜評分平均差 %.2f 分"
              % (len(common), same_act / len(common) * 100, same_sc / len(common) * 100,
                 same_vs / len(common) * 100, sum(dsc) / len(dsc)))
        rows.append({"ticker": t, "n": len(common),
                     "action_same": same_act / len(common),
                     "score_same": same_sc / len(common),
                     "volstatus_same": same_vs / len(common),
                     "score_mad": sum(dsc) / len(dsc)})
    if rows:
        r = pd.DataFrame(rows)
        r.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "volume_fidelity.csv"), index=False, encoding="utf-8-sig")
        print("\n合計：決策一致率 %.1f%%，評分平均差 %.2f 分"
              % (r["action_same"].mean() * 100, r["score_mad"].mean()))


if __name__ == "__main__":
    main()
