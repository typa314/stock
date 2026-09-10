# -*- coding: utf-8 -*-
"""
scripts/generate_seeds.py - 台股核心標的 Parquet 種子檔產生工具
-------------------------------------------------------------
批次抓取台灣 50 / 熱門權值股近 1.5 年日K資料，壓縮儲存為 seeds/tw_stock_seeds.parquet。
作為雲端節點（如 Render）冷啟動時的零延遲歷史資料基底。
"""

import os
import time
import pandas as pd
import yfinance as yf

# 核心種子標的名單（台股 50 成分股 + 系統常測熱門股）
TOP_TICKERS = [
    # 半導體 / 電子代工 / 權值股
    ("2330", "TW"), ("2454", "TW"), ("2317", "TW"), ("2308", "TW"), ("2382", "TW"),
    ("2379", "TW"), ("3008", "TW"), ("3034", "TW"), ("2303", "TW"), ("3711", "TW"),
    ("2357", "TW"), ("2395", "TW"), ("3231", "TW"), ("4938", "TW"), ("2327", "TW"),
    ("3042", "TW"), ("3443", "TW"), ("3661", "TW"), ("6669", "TW"), ("6415", "TWO"),
    ("6182", "TWO"), ("6446", "TWO"), ("8046", "TW"), ("2376", "TW"), ("1717", "TW"),
    # 金融股
    ("2881", "TW"), ("2882", "TW"), ("2891", "TW"), ("2886", "TW"), ("2884", "TW"),
    ("2885", "TW"), ("2880", "TW"), ("5880", "TW"), ("2892", "TW"), ("2887", "TW"),
    ("2890", "TW"), ("5871", "TW"), ("5876", "TW"),
    # 航運 / 傳產 / 塑化 / 原物料
    ("2603", "TW"), ("2609", "TW"), ("2615", "TW"), ("2618", "TW"), ("2610", "TW"),
    ("1101", "TW"), ("1216", "TW"), ("1301", "TW"), ("1303", "TW"), ("2002", "TW"),
    ("6505", "TW"), ("2207", "TW"), ("2912", "TW"), ("9910", "TW"),
    # 熱門 ETF
    ("0050", "TW"), ("0056", "TW"), ("00878", "TW"), ("00919", "TW"), ("00929", "TW")
]


def generate_seeds(output_path=None, period="18mo"):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if output_path is None:
        seeds_dir = os.path.join(base_dir, "seeds")
        os.makedirs(seeds_dir, exist_ok=True)
        output_path = os.path.join(seeds_dir, "tw_stock_seeds.parquet")

    print(f"[*] 開始產出 Parquet 種子檔，共 {len(TOP_TICKERS)} 檔標的...")
    all_rows = []

    for ticker, suffix in TOP_TICKERS:
        sym = f"{ticker}.{suffix}"
        try:
            raw = yf.download(sym, period=period, progress=False, timeout=10)
            if raw is None or raw.empty:
                # 嘗試對向市場後綴
                alt_suffix = "TWO" if suffix == "TW" else "TW"
                raw = yf.download(f"{ticker}.{alt_suffix}", period=period, progress=False, timeout=10)

            if raw is not None and not raw.empty:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                df = raw.reset_index()
                df.columns = [c.lower() for c in df.columns]

                dt_col = "date" if "date" in df.columns else df.columns[0]
                df["date_str"] = pd.to_datetime(df[dt_col]).dt.strftime("%Y-%m-%d")
                df["volume_shares"] = df["volume"] / 1000.0  # 轉為張數

                for _, row in df.iterrows():
                    all_rows.append({
                        "ticker": ticker,
                        "date": str(row["date_str"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume_shares"])
                    })
                print(f"  [OK] {ticker} ({len(df)} 根日K)")
            else:
                print(f"  [WARN] {ticker} 無法取得歷史日K")
        except Exception as e:
            print(f"  [ERROR] {ticker} 下載失敗: {e}")
        time.sleep(0.05)

    if not all_rows:
        print("[!] 未抓取到任何資料，取消寫入。")
        return None

    seed_df = pd.DataFrame(all_rows)
    # 確保型態
    seed_df["ticker"] = seed_df["ticker"].astype(str)
    seed_df["date"] = seed_df["date"].astype(str)
    for col in ["open", "high", "low", "close", "volume"]:
        seed_df[col] = seed_df[col].astype(float)

    seed_df = seed_df.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"]).reset_index(drop=True)
    seed_df.to_parquet(output_path, compression="snappy", index=False)
    file_size_kb = os.path.getsize(output_path) / 1024.0
    print(f"\n[SUCCESS] 已產出種子檔: {output_path}")
    print(f"  總筆數: {len(seed_df):,} 列")
    print(f"  涵蓋標的: {seed_df['ticker'].nunique()} 檔")
    print(f"  檔案大小: {file_size_kb:.1f} KB")
    return output_path


if __name__ == "__main__":
    generate_seeds()
