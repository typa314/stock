# -*- coding: utf-8 -*-
"""
Phase 1 回測執行器：
在 test/mtf-strategy 分支下，使用多核心並行執行 9 檔核心個股之 point-in-time 歷史回測，
產出 signals_phase1_m12_s5.csv，並與 baseline 進行 head-to-head 效益與勝率比較。
"""
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import pandas as pd

sys.path.insert(0, r"F:\stock")
sys.path.insert(0, r"F:\stock\backtest")

from backtest_accuracy import run

TARGET_TICKERS = ['1717', '2330', '2454', '2616', '3008', '3042', '6182', '6446', '6643']

def run_worker(ticker, months=12, step=5, start_date="2020-01-01"):
    out_file = f"F:\\stock\\backtest\\part_phase1_{ticker}.csv"
    try:
        run([ticker], months=months, step=step, start_date=start_date, out_path=out_file, verbose=True)
        return ticker, out_file, True, ""
    except Exception as e:
        return ticker, out_file, False, str(e)

def main():
    months = 12
    step = 5
    start_date = "2020-01-01"
    merged_output = r"F:\stock\backtest\signals_phase1_m12_s5.csv"

    print(f"=== 啟動 Phase 1 多核心並行回測 ({len(TARGET_TICKERS)} 檔個股，step={step}，months={months}) ===")
    t0 = time.time()

    workers = min(len(TARGET_TICKERS), 12)
    dfs = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_worker, t, months, step, start_date): t for t in TARGET_TICKERS}
        for fut in as_completed(futures):
            ticker, out_file, ok, err = fut.result()
            if ok and os.path.exists(out_file):
                sub_df = pd.read_csv(out_file)
                dfs.append(sub_df)
                print(f"[DONE] {ticker}: {len(sub_df)} 筆訊號")
                try:
                    os.remove(out_file)
                except Exception:
                    pass
            else:
                print(f"[FAIL] {ticker}: {err}")

    if dfs:
        all_df = pd.concat(dfs, ignore_index=True)
        all_df.sort_values(by=["ticker", "date"], inplace=True)
        all_df.to_csv(merged_output, index=False, encoding="utf-8-sig")
        elapsed = time.time() - t0
        print(f"\n全部完成！共 {len(all_df)} 筆訊號，耗時 {elapsed:.1f} 秒")
        print(f"結果已存入: {merged_output}")
    else:
        print("未產生任何訊號")

if __name__ == "__main__":
    main()
