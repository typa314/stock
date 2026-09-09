"""
把訊號換算成「照做會賺多少」：不重疊持倉的逐檔模擬對帳。

規則（貼近 LINE Bot 實際用法）：
  進場：訊號日出現指定決策（預設 BUY）→ 次一交易日開盤買進
  出場：以下任一先到者
        (a) -7% 硬停損（bot 的強制停損規則）觸價出場
        (b) 持有滿 N 個交易日（預設 20）收盤出場
  在持倉期間忽略新訊號（不加碼、不重疊），因此可直接串成資金曲線
  對照組：同期間同一檔的買進持有（含息）

用法：python simulate_strategy.py signals_m1_s1.csv --action BUY --hold 20
"""
import sys, os, argparse, pickle
import numpy as np
import pandas as pd

try:   # Windows 終端預設 cp950
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("BT_CACHE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache"))

FEE = 0.001425 * 0.6 * 2 + 0.003   # 券商手續費 6 折買賣各一次 + 賣出證交稅 0.3%


def load_px(ticker):
    with open(os.path.join(CACHE, ticker + ".pkl"), "rb") as f:
        d = pickle.load(f)
    px = d["price"].copy()
    f_ = (px["adj_close"] / px["close"]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    px["adj_open"] = px["open"] * f_
    px["adj_low"] = px["low"] * f_
    px["adj_high"] = px["high"] * f_
    # ATR(20)：與 monitor_worker 的 Conformal 門檻同一口徑（True Range 的 20 日均值）
    tr = pd.concat([px["adj_high"] - px["adj_low"],
                    (px["adj_high"] - px["adj_close"].shift(1)).abs(),
                    (px["adj_low"] - px["adj_close"].shift(1)).abs()], axis=1).max(axis=1)
    px["atr20"] = tr.rolling(20, min_periods=20).mean()
    return px.reset_index(drop=True)


def simulate(sig, actions, hold, stop_pct, fee, stop_atr=0.0, stop_cap=0.0, stop_floor=0.0):
    out = []
    for t, g in sig.groupby("ticker"):
        px = load_px(t)
        pos = {d: i for i, d in enumerate(px["date"])}
        g = g[g["action"].isin(actions)].sort_values("date")
        trades = []
        busy_until = -1
        for _, row in g.iterrows():
            i = pos.get(pd.Timestamp(row["date"]))
            if i is None or i <= busy_until or i + 1 >= len(px):
                continue
            entry = px["adj_open"].iloc[i + 1]
            if not np.isfinite(entry) or entry <= 0:
                continue
            if stop_atr > 0:
                atr = px["atr20"].iloc[i]
                if not np.isfinite(atr) or atr <= 0:
                    continue
                stop = entry - stop_atr * atr
                if stop_cap > 0:                      # 停損幅度上限（避免高波動股停損過寬）
                    stop = max(stop, entry * (1 - stop_cap))
                if stop_floor > 0:                    # 停損幅度下限（避免低波動股停損過緊）
                    stop = min(stop, entry * (1 - stop_floor))
            else:
                stop = entry * (1 + stop_pct)
            exit_i, exit_p, why = None, None, ""
            for j in range(i + 1, min(i + 1 + hold, len(px))):
                if px["adj_low"].iloc[j] <= stop:
                    exit_i, exit_p, why = j, stop, "stop"
                    break
            if exit_i is None:
                j = min(i + hold, len(px) - 1)
                exit_i, exit_p, why = j, px["adj_close"].iloc[j], "time"
            r = exit_p / entry - 1 - fee
            trades.append({"ticker": t, "entry_date": px["date"].iloc[i + 1],
                           "exit_date": px["date"].iloc[exit_i], "ret": r,
                           "days": exit_i - i, "exit": why})
            busy_until = exit_i
        if not trades:
            continue
        td = pd.DataFrame(trades)
        eq = (1 + td["ret"]).prod()
        first, last = pos[pd.Timestamp(g["date"].iloc[0])], len(px) - 1
        bh = px["adj_close"].iloc[last] / px["adj_open"].iloc[first + 1] - 1
        years = (px["date"].iloc[last] - px["date"].iloc[first + 1]).days / 365.25
        in_mkt = td["days"].sum() / max(1, (last - first))
        out.append({"ticker": t, "trades": len(td), "win": (td["ret"] > 0).mean(),
                    "avg": td["ret"].mean(), "median": td["ret"].median(),
                    "total": eq - 1, "cagr": eq ** (1 / years) - 1 if years > 0 else np.nan,
                    "bh_total": bh, "bh_cagr": (1 + bh) ** (1 / years) - 1 if years > 0 else np.nan,
                    "in_market": in_mkt, "stop_exit": (td["exit"] == "stop").mean(),
                    "worst": td["ret"].min(), "best": td["ret"].max()})
    return pd.DataFrame(out), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--action", default="BUY")
    ap.add_argument("--hold", type=int, default=20)
    ap.add_argument("--stop", type=float, default=-0.07)
    ap.add_argument("--fee", type=float, default=FEE)
    ap.add_argument("--min-score", type=float, default=0,
                    help="只採用綜合評分 >= 此值的訊號（用於檢驗門檻校準）")
    ap.add_argument("--stop-atr", type=float, default=0.0,
                    help="改用波動度自適應停損：停損價 = 進場價 - K x ATR20（K 為本參數）")
    ap.add_argument("--stop-floor", type=float, default=0.0,
                    help="搭配 --stop-atr 使用的停損幅度下限，例如 0.08 代表至少 -8%%")
    ap.add_argument("--stop-cap", type=float, default=0.0,
                    help="搭配 --stop-atr 使用的停損幅度上限，例如 0.15 代表最多 -15%%")
    a = ap.parse_args()
    sig = pd.read_csv(a.csv, parse_dates=["date"], dtype={"ticker": str}).dropna(subset=["action"])
    if a.min_score > 0:
        sig = sig[sig["score"] >= a.min_score]
    actions = a.action.split(",")
    r, _ = simulate(sig, actions, a.hold, a.stop, a.fee, a.stop_atr, a.stop_cap, a.stop_floor)
    if r.empty:
        print("無交易產生")
        return
    stop_desc = ("%.1fxATR20" % a.stop_atr + (" 上限%.0f%%" % (a.stop_cap * 100) if a.stop_cap > 0 else ""))         if a.stop_atr > 0 else ("%.0f%%" % (a.stop * 100))
    print("訊號：%s ｜持有上限 %d 交易日 ｜停損 %s ｜來回成本 %.3f%%"
          % ("/".join(actions), a.hold, stop_desc, a.fee * 100))
    print("-" * 104)
    print("%-6s %6s %7s %9s %10s %10s %10s %10s %8s %8s"
          % ("個股", "交易數", "勝率", "平均報酬", "策略總報酬", "策略CAGR",
             "買進持有", "B&H CAGR", "在market", "停損出場"))
    for _, x in r.iterrows():
        print("%-6s %6d %6.1f%% %8.2f%% %9.1f%% %9.1f%% %9.1f%% %9.1f%% %7.0f%% %7.0f%%"
              % (x["ticker"], x["trades"], x["win"] * 100, x["avg"] * 100, x["total"] * 100,
                 x["cagr"] * 100, x["bh_total"] * 100, x["bh_cagr"] * 100,
                 x["in_market"] * 100, x["stop_exit"] * 100))
    print("-" * 104)
    w = r["trades"]
    print("%-6s %6d %6.1f%% %8.2f%% %9s %9.1f%% %9s %9.1f%% %7.0f%% %7.0f%%"
          % ("加權", w.sum(), np.average(r["win"], weights=w) * 100,
             np.average(r["avg"], weights=w) * 100, "-",
             r["cagr"].mean() * 100, "-", r["bh_cagr"].mean() * 100,
             r["in_market"].mean() * 100, np.average(r["stop_exit"], weights=w) * 100))
    print("\n策略 CAGR 贏過買進持有的檔數：%d / %d"
          % (int((r["cagr"] > r["bh_cagr"]).sum()), len(r)))
    print("註：策略只在持倉期間承受風險（平均在市 %.0f%%），CAGR 為訊號期間的實際資金曲線年化，"
          "與買進持有的 100%% 在市不可直接畫等號，需併看平均在市比率。" % (r["in_market"].mean() * 100))
    out = os.path.join(os.path.dirname(os.path.abspath(a.csv)),
                       "sim_%s_h%d.csv" % ("-".join(actions), a.hold))
    r.to_csv(out, index=False, encoding="utf-8-sig")
    print("[OK] → %s" % out)


if __name__ == "__main__":
    main()
