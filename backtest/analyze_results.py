"""
回測結果統計：把 backtest_accuracy.py 產出的訊號檔換算成「準確度」指標。

準確度定義（三層，避免只看單一數字誤判）：
  1. 方向命中率  ：看多訊號(BUY/HOLD)後續上漲、看空訊號(SELL)後續下跌的比率
  2. 相對基準超額：同一批樣本的「無條件平均報酬」為基準，訊號必須贏過它才算有資訊
  3. 排序能力 IC ：綜合評分與後續報酬的 Spearman 相關（含每日橫斷面 IC）

顯著性：日頻訊號與 20 日前瞻報酬高度重疊，且個股間同時受大盤影響，
        因此採「(個股 × 月份) 區塊 bootstrap」計算信賴區間，不用一般 t 檢定。

用法：python analyze_results.py signals_m1_s1.csv [signals_m12_s5.csv ...]
"""
import sys, os
import numpy as np
import pandas as pd

try:   # Windows 終端預設 cp950，無法輸出報告用的符號
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HORIZONS = [5, 10, 20, 60]
LONG = ("BUY", "HOLD")
SHORT = ("SELL",)
RNG = np.random.default_rng(20260909)


def load(path):
    df = pd.read_csv(path, parse_dates=["date"], dtype={"ticker": str})
    df = df.dropna(subset=["score", "action"])
    df["block"] = df["ticker"] + "_" + df["date"].dt.strftime("%Y-%m")
    return df


def block_bootstrap_mean(df, col, n=2000):
    """以 (個股×月份) 為區塊重抽，回傳平均值的 95% 信賴區間"""
    sub = df.dropna(subset=[col])
    if len(sub) < 30:
        return (np.nan, np.nan)
    groups = [g[col].values for _, g in sub.groupby("block")]
    k = len(groups)
    means = np.empty(n)
    for i in range(n):
        pick = RNG.integers(0, k, k)
        means[i] = np.concatenate([groups[j] for j in pick]).mean()
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def block_bootstrap_diff(df, mask, col, n=2000):
    """訊號組平均 - 全樣本基準平均，的 95% 信賴區間（同樣以區塊重抽）"""
    sub = df.dropna(subset=[col]).copy()
    sub["_m"] = mask.reindex(sub.index).fillna(False).astype(bool)
    if sub["_m"].sum() < 30:
        return (np.nan, np.nan)
    groups = [(g[col].values, g["_m"].values) for _, g in sub.groupby("block")]
    k = len(groups)
    out = np.empty(n)
    for i in range(n):
        pick = RNG.integers(0, k, k)
        v = np.concatenate([groups[j][0] for j in pick])
        m = np.concatenate([groups[j][1] for j in pick])
        out[i] = (v[m].mean() - v.mean()) if m.sum() > 0 else np.nan
    out = out[np.isfinite(out)]
    if len(out) == 0:
        return (np.nan, np.nan)
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def pct(x):
    return "n/a" if x is None or not np.isfinite(x) else "%+.2f%%" % (x * 100)


def rate(x):
    return "n/a" if x is None or not np.isfinite(x) else "%.1f%%" % (x * 100)


def section(title):
    print("\n" + "=" * 78)
    print("  " + title)
    print("=" * 78)


def describe(df, label, lines):
    section("樣本描述：%s" % label)
    n = len(df)
    lines.append("### 樣本描述：%s\n" % label)
    lines.append("- 訊號筆數：**%d**（%d 檔個股，%s ~ %s）" %
                 (n, df["ticker"].nunique(), df["date"].min().date(), df["date"].max().date()))
    lines.append("- 引擎實際使用 K 棒數：中位數 %d 根（min %d / max %d）" %
                 (df["bars_used"].median(), df["bars_used"].min(), df["bars_used"].max()))
    print("訊號筆數 %d ｜個股 %d ｜期間 %s ~ %s ｜K棒中位數 %d 根"
          % (n, df["ticker"].nunique(), df["date"].min().date(), df["date"].max().date(),
             df["bars_used"].median()))
    dist = df["action"].value_counts()
    lines.append("- 決策分布：" + "／".join("%s %d 筆（%.1f%%）" % (k, v, v / n * 100)
                                            for k, v in dist.items()))
    print("決策分布：" + "  ".join("%s=%d(%.1f%%)" % (k, v, v / n * 100) for k, v in dist.items()))
    lines.append("- 綜合評分分布：平均 %.1f，中位數 %.0f，範圍 %d~%d" %
                 (df["score"].mean(), df["score"].median(), df["score"].min(), df["score"].max()))
    print("評分：mean %.1f median %.0f range %d~%d"
          % (df["score"].mean(), df["score"].median(), df["score"].min(), df["score"].max()))
    lines.append("")


def action_table(df, label, lines, ret_prefix="ret_t1_"):
    section("各決策後續報酬（%s，進場價＝T+1 開盤，含息）" % label)
    base = {h: df["%s%d" % (ret_prefix, h)].dropna() for h in HORIZONS}
    hdr = "%-6s %7s " % ("決策", "筆數") + " ".join("%18s" % ("%d日 平均/勝率" % h) for h in HORIZONS)
    print(hdr)
    print("-" * len(hdr))
    lines.append("### 各決策後續報酬（%s）\n" % label)
    lines.append("進場價＝訊號日次一交易日開盤（含息調整）。基準列為同期間全樣本無條件平均，"
                 "代表「隨機任一天買進」的結果。\n")
    lines.append("| 決策 | 筆數 | " + " | ".join("%d日平均" % h for h in HORIZONS) +
                 " | " + " | ".join("%d日勝率" % h for h in HORIZONS) + " |")
    lines.append("|---|---|" + "---|" * (2 * len(HORIZONS)))

    rows = []
    for act in ["BUY", "HOLD", "WAIT", "SELL"]:
        sub = df[df["action"] == act]
        if len(sub) == 0:
            continue
        cells, means, wins = [], [], []
        for h in HORIZONS:
            r = sub["%s%d" % (ret_prefix, h)].dropna()
            m = r.mean() if len(r) else np.nan
            w = (r > 0).mean() if len(r) else np.nan
            means.append(pct(m))
            wins.append(rate(w))
            cells.append("%18s" % ("%s / %s" % (pct(m), rate(w))))
        print("%-6s %7d " % (act, len(sub)) + " ".join(cells))
        rows.append("| **%s** | %d | " % (act, len(sub)) + " | ".join(means) + " | " + " | ".join(wins) + " |")
    # 基準
    cells, means, wins = [], [], []
    for h in HORIZONS:
        r = base[h]
        means.append(pct(r.mean()))
        wins.append(rate((r > 0).mean()))
        cells.append("%18s" % ("%s / %s" % (pct(r.mean()), rate((r > 0).mean()))))
    print("%-6s %7d " % ("基準", len(df)) + " ".join(cells))
    rows.append("| 基準（全樣本） | %d | " % len(df) + " | ".join(means) + " | " + " | ".join(wins) + " |")
    lines.extend(rows)
    lines.append("")

    # 超額報酬與信賴區間（20 日）
    section("20 日超額報酬 bootstrap 95%% 信賴區間（%s）" % label)
    lines.append("#### 20 日超額報酬（vs 全樣本基準）95%% 區塊 bootstrap 信賴區間\n")
    lines.append("| 決策 | 20日平均 | 超額 | 95% CI | 是否顯著優於基準 |")
    lines.append("|---|---|---|---|---|")
    col = "%s20" % ret_prefix
    b20 = df[col].dropna().mean()
    for act in ["BUY", "HOLD", "WAIT", "SELL"]:
        mask = df["action"] == act
        if mask.sum() < 30:
            continue
        m = df.loc[mask, col].dropna().mean()
        lo, hi = block_bootstrap_diff(df, mask, col)
        sig = "n/a"
        if np.isfinite(lo):
            sig = "✅ 顯著優於" if lo > 0 else ("❌ 顯著劣於" if hi < 0 else "⚪ 不顯著")
        print("%-6s 平均 %s ｜超額 %s ｜CI [%s, %s] %s"
              % (act, pct(m), pct(m - b20), pct(lo), pct(hi), sig))
        lines.append("| **%s** | %s | %s | [%s, %s] | %s |"
                     % (act, pct(m), pct(m - b20), pct(lo), pct(hi), sig))
    lines.append("")


def direction_accuracy(df, label, lines, ret_prefix="ret_t1_"):
    section("方向命中率（看多=BUY/HOLD 需上漲，看空=SELL 需下跌）")
    lines.append("### 方向命中率\n")
    lines.append("看多訊號（BUY／HOLD）後續上漲、看空訊號（SELL）後續下跌即算命中；"
                 "WAIT 無方向不列入。括號內為同期間該方向的隨機基準命中率。\n")
    lines.append("| 期間 | 看多命中率 | (隨機基準) | 看空命中率 | (隨機基準) | 綜合方向命中率 |")
    lines.append("|---|---|---|---|---|---|")
    for h in HORIZONS:
        col = "%s%d" % (ret_prefix, h)
        d = df.dropna(subset=[col])
        up_base = (d[col] > 0).mean()
        L = d[d["action"].isin(LONG)]
        Sh = d[d["action"].isin(SHORT)]
        l_hit = (L[col] > 0).mean() if len(L) else np.nan
        s_hit = (Sh[col] < 0).mean() if len(Sh) else np.nan
        both_n = len(L) + len(Sh)
        both = ((L[col] > 0).sum() + (Sh[col] < 0).sum()) / both_n if both_n else np.nan
        print("%2d 日 ｜看多 %s (基準 %s, n=%d) ｜看空 %s (基準 %s, n=%d) ｜綜合 %s"
              % (h, rate(l_hit), rate(up_base), len(L), rate(s_hit), rate(1 - up_base), len(Sh), rate(both)))
        lines.append("| %d 日 | **%s** (n=%d) | %s | **%s** (n=%d) | %s | **%s** |"
                     % (h, rate(l_hit), len(L), rate(up_base), rate(s_hit), len(Sh),
                        rate(1 - up_base), rate(both)))
    lines.append("")


def score_power(df, label, lines, ret_prefix="ret_t1_"):
    section("綜合評分的排序能力（IC）與分層報酬")
    lines.append("### 綜合評分（0~100）的排序能力\n")
    lines.append("| 期間 | 合併 Spearman IC | 每日橫斷面 IC 平均 | IC 勝率 |")
    lines.append("|---|---|---|---|")
    for h in HORIZONS:
        col = "%s%d" % (ret_prefix, h)
        d = df.dropna(subset=[col, "score"])
        pooled = d["score"].corr(d[col], method="spearman")
        daily = []
        for _, g in d.groupby("date"):
            if g["ticker"].nunique() >= 8 and g["score"].nunique() > 1:
                daily.append(g["score"].corr(g[col], method="spearman"))
        daily = pd.Series(daily).dropna()
        print("%2d 日 ｜合併 IC %.3f ｜每日橫斷面 IC 平均 %.3f（%d 天，IC>0 佔 %s）"
              % (h, pooled, daily.mean() if len(daily) else np.nan, len(daily),
                 rate((daily > 0).mean()) if len(daily) else np.nan))
        lines.append("| %d 日 | %.3f | %.3f (n=%d 天) | %s |"
                     % (h, pooled, daily.mean() if len(daily) else np.nan, len(daily),
                        rate((daily > 0).mean()) if len(daily) else np.nan))
    lines.append("")

    # 另一個引擎輸出：evaluate_professional_trend 的多因子 trend_score
    if "trend_score" in df.columns:
        lines.append("#### 另一路輸出：多因子 trend_score（驅動星級徽章）的排序能力\n")
        lines.append("| 期間 | 合併 Spearman IC |")
        lines.append("|---|---|")
        for h in HORIZONS:
            col = "%s%d" % (ret_prefix, h)
            d = df.dropna(subset=[col, "trend_score"])
            ic = d["trend_score"].corr(d[col], method="spearman")
            print("trend_score %2d 日 合併 IC %.3f" % (h, ic))
            lines.append("| %d 日 | %.3f |" % (h, ic))
        lines.append("")

    # 評分分層
    section("評分分層 → 後續 20 日報酬（單調性檢查）")
    lines.append("#### 評分分層 → 後續 20 日報酬（檢查是否分數越高、報酬越好）\n")
    lines.append("| 評分區間 | 筆數 | 20日平均報酬 | 20日勝率 |")
    lines.append("|---|---|---|---|")
    bins = [0, 35, 45, 55, 60, 65, 70, 75, 80, 101]
    col = "%s20" % ret_prefix
    d = df.dropna(subset=[col]).copy()
    d["bucket"] = pd.cut(d["score"], bins, right=False)
    for b, g in d.groupby("bucket", observed=True):
        if len(g) == 0:
            continue
        print("%-12s n=%5d ｜平均 %s ｜勝率 %s"
              % ("[%d,%d)" % (b.left, b.right), len(g), pct(g[col].mean()), rate((g[col] > 0).mean())))
        lines.append("| %d ~ %d | %d | %s | %s |"
                     % (b.left, b.right - 1, len(g), pct(g[col].mean()), rate((g[col] > 0).mean())))
    lines.append("")


def risk_check(df, label, lines):
    section("風控檢核：LINE Bot -7% 硬停損在訊號後 20 日內的觸發率")
    lines.append("### 風控檢核：-7% 硬停損觸發率（訊號後 20 日內）\n")
    lines.append("以 T+1 開盤為成本，觀察 20 日內先觸及 -7%（停損）或先觸及 +7%（獲利）的比率。\n")
    lines.append("| 決策 | 筆數 | 先觸 -7% | 先觸 +7% | 皆未觸及 | 觸發比（+7:-7） |")
    lines.append("|---|---|---|---|---|---|")
    d = df.dropna(subset=["stop7_first_20d", "tp7_first_20d"])
    for act in ["BUY", "HOLD", "WAIT", "SELL", "ALL"]:
        g = d if act == "ALL" else d[d["action"] == act]
        if len(g) < 20:
            continue
        dn = g["stop7_first_20d"].mean()
        up = g["tp7_first_20d"].mean()
        none = 1 - dn - up
        ratio = (up / dn) if dn > 0 else np.nan
        name = "全樣本基準" if act == "ALL" else act
        print("%-8s n=%5d ｜先觸-7%% %s ｜先觸+7%% %s ｜未觸 %s ｜比 %.2f"
              % (name, len(g), rate(dn), rate(up), rate(none), ratio))
        lines.append("| %s | %d | %s | %s | %s | %s |"
                     % (name, len(g), rate(dn), rate(up), rate(none),
                        "n/a" if not np.isfinite(ratio) else "%.2f" % ratio))
    lines.append("")


def bpa_check(df, label, lines, ret_prefix="ret_t1_"):
    section("BPA Always-In 狀態判定的方向準確度")
    lines.append("### BPA Always-In 狀態的方向準確度\n")
    lines.append("| BPA 狀態 | 筆數 | 5日平均 | 5日上漲率 | 20日平均 | 20日上漲率 |")
    lines.append("|---|---|---|---|---|---|")
    d = df.dropna(subset=["bpa"])
    for st, g in d.groupby("bpa"):
        if len(g) < 30:
            continue
        r5 = g["%s5" % ret_prefix].dropna()
        r20 = g["%s20" % ret_prefix].dropna()
        print("%-10s n=%5d ｜5日 %s/%s ｜20日 %s/%s"
              % (st, len(g), pct(r5.mean()), rate((r5 > 0).mean()),
                 pct(r20.mean()), rate((r20 > 0).mean())))
        lines.append("| %s | %d | %s | %s | %s | %s |"
                     % (st, len(g), pct(r5.mean()), rate((r5 > 0).mean()),
                        pct(r20.mean()), rate((r20 > 0).mean())))
    lines.append("")


def per_ticker(df, label, lines, ret_prefix="ret_t1_"):
    section("逐檔穩定性（看多訊號 20 日命中率，檢查是否只靠少數個股撐起來）")
    lines.append("### 逐檔穩定性（看多訊號 20 日命中率）\n")
    col = "%s20" % ret_prefix
    rec = []
    for t, g in df[df["action"].isin(LONG)].dropna(subset=[col]).groupby("ticker"):
        if len(g) < 20:
            continue
        base = df[(df["ticker"] == t)][col].dropna()
        rec.append({"ticker": t, "n": len(g), "hit": (g[col] > 0).mean(),
                    "mean": g[col].mean(), "base_hit": (base > 0).mean(),
                    "base_mean": base.mean()})
    r = pd.DataFrame(rec).sort_values("hit", ascending=False)
    if r.empty:
        print("（看多訊號樣本不足）")
        lines.append("（看多訊號樣本不足）\n")
        return
    lines.append("| 個股 | 看多筆數 | 命中率 | 該股基準 | 差 |")
    lines.append("|---|---|---|---|---|")
    for _, x in r.iterrows():
        print("%-6s n=%4d ｜命中 %s ｜該股基準 %s ｜差 %+.1f pp"
              % (x["ticker"], x["n"], rate(x["hit"]), rate(x["base_hit"]),
                 (x["hit"] - x["base_hit"]) * 100))
        lines.append("| %s | %d | %s | %s | %+.1f pp |"
                     % (x["ticker"], x["n"], rate(x["hit"]), rate(x["base_hit"]),
                        (x["hit"] - x["base_hit"]) * 100))
    win = (r["hit"] > r["base_hit"]).mean()
    print("\n贏過自身基準的個股比例：%s（%d/%d 檔）" % (rate(win), (r["hit"] > r["base_hit"]).sum(), len(r)))
    lines.append("\n贏過自身基準的個股比例：**%s**（%d/%d 檔）\n"
                 % (rate(win), (r["hit"] > r["base_hit"]).sum(), len(r)))


def alert_check(df, label, lines, ret_prefix="ret_t1_"):
    """LINE Bot 實際推播的 BPA 底部買點雷達（monitor_worker.check_bottom_confirmation_signals）"""
    if "alert" not in df.columns:
        return
    section("LINE Bot BPA 買點雷達推播訊號的實際命中率")
    lines.append("### LINE Bot BPA 買點雷達（實際推播訊號）\n")
    lines.append("對應 `monitor_worker.check_bottom_confirmation_signals`，"
                 "以盤後定盤 K 棒評估（production 為盤中每 60 秒評估，見報告末段限制說明）。\n")
    d = df.copy()
    d["alert"] = d["alert"].fillna(0).astype(int)
    n_all = len(d)
    n_hit = int(d["alert"].sum())
    print("觸發率：%d / %d = %s（平均每檔每年約 %.1f 次）"
          % (n_hit, n_all, rate(n_hit / n_all),
             n_hit / d["ticker"].nunique() / ((d["date"].max() - d["date"].min()).days / 365.25)))
    lines.append("- 觸發率：**%d / %d = %s**，平均每檔每年約 **%.1f 次**\n"
                 % (n_hit, n_all, rate(n_hit / n_all),
                    n_hit / d["ticker"].nunique() / ((d["date"].max() - d["date"].min()).days / 365.25)))
    lines.append("| 樣本 | 筆數 | " + " | ".join("%d日平均" % h for h in HORIZONS) +
                 " | " + " | ".join("%d日勝率" % h for h in HORIZONS) + " |")
    lines.append("|---|---|" + "---|" * (2 * len(HORIZONS)))
    for name, sub in (("推播觸發", d[d["alert"] == 1]), ("未觸發", d[d["alert"] == 0]),
                      ("基準（全樣本）", d)):
        if len(sub) < 20:
            continue
        means, wins, cells = [], [], []
        for h in HORIZONS:
            r = sub["%s%d" % (ret_prefix, h)].dropna()
            means.append(pct(r.mean()))
            wins.append(rate((r > 0).mean()))
            cells.append("%d日 %s/%s" % (h, pct(r.mean()), rate((r > 0).mean())))
        print("%-14s n=%5d ｜" % (name, len(sub)) + " ｜".join(cells))
        lines.append("| %s | %d | " % (name, len(sub)) + " | ".join(means) + " | " + " | ".join(wins) + " |")
    mask = d["alert"] == 1
    col = "%s20" % ret_prefix
    if mask.sum() >= 30:
        lo, hi = block_bootstrap_diff(d, mask, col)
        base = d[col].dropna().mean()
        m = d.loc[mask, col].dropna().mean()
        sig = "n/a" if not np.isfinite(lo) else ("✅ 顯著優於基準" if lo > 0 else
                                                ("❌ 顯著劣於基準" if hi < 0 else "⚪ 與基準無顯著差異"))
        print("20 日超額 %s ｜95%% CI [%s, %s] %s" % (pct(m - base), pct(lo), pct(hi), sig))
        lines.append("\n20 日超額報酬 **%s**，95%% 區塊 bootstrap CI [%s, %s] → **%s**\n"
                     % (pct(m - base), pct(lo), pct(hi), sig))
        dn = d.loc[mask, "stop7_first_20d"].dropna()
        dn_b = d["stop7_first_20d"].dropna()
        print("推播後 20 日內先觸 -7%% 停損比率：%s（全樣本基準 %s）"
              % (rate(dn.mean()), rate(dn_b.mean())))
        lines.append("推播後 20 日內先觸及 -7%% 硬停損比率：**%s**（全樣本基準 %s）\n"
                     % (rate(dn.mean()), rate(dn_b.mean())))
    if "alert_name" in d.columns:
        lines.append("\n| 訊號類型 | 筆數 | 20日平均 | 20日勝率 |")
        lines.append("|---|---|---|---|")
        for nm, g in d[mask].groupby("alert_name"):
            if len(g) < 10:
                continue
            r = g[col].dropna()
            print("  %-24s n=%4d ｜20日 %s / %s" % (nm, len(g), pct(r.mean()), rate((r > 0).mean())))
            lines.append("| %s | %d | %s | %s |" % (nm, len(g), pct(r.mean()), rate((r > 0).mean())))
    lines.append("")


def analyze(path, lines):
    df = load(path)
    label = os.path.basename(path)
    mode = "production 預設（months=%d）" % df["months"].iloc[0]
    lines.append("\n---\n\n## %s ｜ %s\n" % (label, mode))
    describe(df, label, lines)
    action_table(df, label, lines)
    direction_accuracy(df, label, lines)
    score_power(df, label, lines)
    risk_check(df, label, lines)
    bpa_check(df, label, lines)
    alert_check(df, label, lines)
    per_ticker(df, label, lines)
    return df


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        print("用法：python analyze_results.py signals_m1_s1.csv [...]")
        sys.exit(1)
    lines = ["# F:\\stock 研判系統 歷史資料準確度驗證\n"]
    for p in paths:
        analyze(p, lines)
    out = os.path.join(os.path.dirname(os.path.abspath(paths[0])), "accuracy_report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n[OK] 明細報告 → %s" % out)
