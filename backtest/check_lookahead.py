"""
未來資料洩漏稽核：
把資料截斷在 T 與截斷在 T+10 分別跑一次引擎，比較「重疊日期區間」內
所有 BPA 形態旗標與技術指標欄位是否完全相同。

若引擎有任何一處偷看了未來 K 棒（例如用到 shift(-1)、centered rolling、
或整段 rolling 後才判斷極值），同一天的旗標值在兩次計算下就會不一致。

用法：python check_lookahead.py 2330
"""
import sys, os, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, r"F:\stock")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kline
import backtest_accuracy as bt


def main():
    t = (sys.argv[1:] or ["2330"])[0]
    months = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    with open(os.path.join(bt.CACHE, t + ".pkl"), "rb") as f:
        d = pickle.load(f)
    bt.install_patches()
    px = bt.add_forward(d["price"].copy())
    bt.S.update(px=px, inst=d.get("inst"), rev=d.get("revenue"), fs=d.get("fs"),
                market=d.get("market", "tse"))

    i = len(px) - 200          # 任取一個中段日期
    res = {}
    for off in (0, 10):
        bt.S["cut"] = px["date"].iloc[i + off].to_pydatetime()
        r = kline.analyze_stock(t, months=months, generate_html=False,
                                print_report=False, quick_mode=False)
        res[off] = r["df"].set_index("date")

    a, b = res[0], res[10]
    common = a.index.intersection(b.index)
    print("截斷 %s vs 截斷 %s ｜重疊 %d 個交易日"
          % (px["date"].iloc[i].date(), px["date"].iloc[i + 10].date(), len(common)))
    bad = []
    for c in a.columns:
        if c not in b.columns:
            continue
        x, y = a.loc[common, c], b.loc[common, c]
        if x.dtype == bool or y.dtype == bool:
            n = int((x.astype(bool) != y.astype(bool)).sum())
        else:
            try:
                n = int((~np.isclose(x.astype(float), y.astype(float),
                                     rtol=1e-9, atol=1e-9, equal_nan=True)).sum())
            except Exception:
                n = int((x.astype(str) != y.astype(str)).sum())
        if n:
            bad.append((c, n))
    if not bad:
        print("[PASS] 全部 %d 個欄位在重疊區間完全一致 → 引擎無未來資料洩漏" % len(a.columns))
    else:
        print("[FAIL] 以下欄位在加入未來 10 根 K 棒後改變了過去的值（疑似前視偏誤）：")
        for c, n in sorted(bad, key=lambda x: -x[1]):
            print("   %-16s 不一致 %d / %d 日" % (c, n, len(common)))


if __name__ == "__main__":
    main()
