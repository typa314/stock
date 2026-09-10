# -*- coding: utf-8 -*-
"""
core/kline_cache.py - 本地 SQLite 增量日K快取與 Parquet 種子引擎
--------------------------------------------------------------
職責：
  1. 維護 daily_kline 本地資料表，杜絕盤中對 TWSE 官網的 12 個月逐月 requests 爬蟲。
  2. 冷啟動時優先自 seeds/tw_stock_seeds.parquet 極速種入歷史日線（耗時 < 0.01 秒）。
  3. 針對本地快取最新日與昨日之間的差集，透過 yfinance 單次輕量增量補齊。
  4. 當日盤中未定盤棒線不寫入本庫，維持歷史定盤數據之純淨性。
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd
import yfinance as yf

from core.constants import TW_TZ
from bot_db import get_connection, DEFAULT_DB_PATH

logger = logging.getLogger("kline_cache")

# 預設種子檔案路徑
DEFAULT_SEED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "seeds", "tw_stock_seeds.parquet"
)


def init_kline_cache_table(db_path=None):
    """確保 daily_kline 資料表與索引存在"""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_kline (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (ticker, date)
        )
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_kline_ticker_date 
        ON daily_kline (ticker, date)
        """)


def load_ticker_from_seed(ticker: str, db_path=None, seed_path=None) -> int:
    """
    若種子檔存在且包含該標的，直接由 Parquet 批量匯入 SQLite。
    回傳匯入列數。
    """
    path = seed_path or DEFAULT_SEED_PATH
    if not os.path.exists(path):
        return 0

    ticker = str(ticker).strip()
    try:
        # 使用 pyarrow 謂詞下推 (Predicate Pushdown) 極速過濾單檔
        seed_df = pd.read_parquet(path, filters=[("ticker", "==", ticker)])
        if seed_df.empty:
            return 0

        rows = []
        for _, r in seed_df.iterrows():
            rows.append((
                ticker,
                str(r["date"]),
                float(r["open"]),
                float(r["high"]),
                float(r["low"]),
                float(r["close"]),
                float(r["volume"])
            ))

        init_kline_cache_table(db_path)
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany("""
            INSERT OR IGNORE INTO daily_kline (ticker, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)

        logger.info(f"🌱 已自種子檔成功匯入 {ticker} 歷史日K 共 {len(rows)} 筆")
        return len(rows)
    except Exception as e:
        logger.warning(f"自種子檔讀取 {ticker} 失敗: {e}")
        return 0


def _fetch_yfinance_bars(ticker: str, market: str, start_str: str, end_str: str):
    """透過 yfinance 抓取指定日期範圍的歷史日K (排除今日盤中未定盤棒)"""
    sym = f"{ticker}.TW" if market == "tse" else f"{ticker}.TWO"
    try:
        raw = yf.download(sym, start=start_str, end=end_str, progress=False, timeout=10)
        if raw is None or raw.empty:
            alt_sym = f"{ticker}.TWO" if market == "tse" else f"{ticker}.TW"
            raw = yf.download(alt_sym, start=start_str, end=end_str, progress=False, timeout=10)
        if raw is None or raw.empty:
            return []

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw.reset_index()
        df.columns = [c.lower() for c in df.columns]

        dt_col = "date" if "date" in df.columns else df.columns[0]
        df = df.dropna(subset=["open", "high", "low", "close", dt_col])
        df["date_str"] = pd.to_datetime(df[dt_col]).dt.strftime("%Y-%m-%d")
        today_str = datetime.now(TW_TZ).strftime("%Y-%m-%d")

        records = []
        for _, r in df.iterrows():
            d_str = str(r["date_str"])
            # 盤中未收盤定盤的棒線絕不寫入 SQLite 歷史表
            if d_str >= today_str:
                continue
            try:
                o_val = float(r["open"])
                h_val = float(r["high"])
                l_val = float(r["low"])
                c_val = float(r["close"])
                v_val = float(r["volume"]) / 1000.0 if not pd.isna(r.get("volume")) else 0.0
                if any(pd.isna([o_val, h_val, l_val, c_val])):
                    continue
                records.append({
                    "ticker": ticker,
                    "date": d_str,
                    "open": o_val,
                    "high": h_val,
                    "low": l_val,
                    "close": c_val,
                    "volume": v_val
                })
            except Exception:
                continue
        return records

    except Exception as e:
        logger.warning(f"yfinance 下載 {ticker} 增量區間 [{start_str} ~ {end_str}] 異常: {e}")
        return []


def get_daily_kline_records(ticker: str, market: str = "tse", months: int = 12,
                            db_path=None, seed_path=None):
    """
    核心入口：取得乾淨且連續的歷史日K資料（含 SQLite 增量維護）。
    
    執行流程：
      1. 查詢本地 SQLite。
      2. 若無資料：嘗試自 Parquet 種子載入；若無種子則自 yfinance 拉取 18 個月全量。
      3. 增量檢查：若本地最新日期小於昨日，向 yfinance 補齊最近缺漏日線。
      4. 回傳 [start_date, 昨日] 之歷史紀錄清單 (格式完全相容 kline.py records)。
    """
    ticker = str(ticker).strip()
    init_kline_cache_table(db_path)

    now_tw = datetime.now(TW_TZ)
    start_dt = now_tw - relativedelta(months=months)
    start_str = start_dt.strftime("%Y-%m-%d")
    today_str = now_tw.strftime("%Y-%m-%d")

    # 1. 查詢現存快取範圍
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM daily_kline WHERE ticker = ?", (ticker,))
        row = cursor.fetchone()
        min_date, max_date, count = row[0], row[1], row[2]

    # 2. 若完全無資料：嘗試種子或拉全量
    if count == 0:
        seed_count = load_ticker_from_seed(ticker, db_path, seed_path)
        if seed_count > 0:
            with get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM daily_kline WHERE ticker = ?", (ticker,))
                row = cursor.fetchone()
                min_date, max_date, count = row[0], row[1], row[2]
        else:
            # 冷門股：向 yfinance 抓取 18 個月
            full_start = (now_tw - relativedelta(months=18)).strftime("%Y-%m-%d")
            fresh_records = _fetch_yfinance_bars(ticker, market, full_start, today_str)
            if fresh_records:
                for r in fresh_records:
                    r.setdefault("ticker", ticker)
                with get_connection(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.executemany("""
                    INSERT OR REPLACE INTO daily_kline (ticker, date, open, high, low, close, volume)
                    VALUES (:ticker, :date, :open, :high, :low, :close, :volume)
                    """, fresh_records)
                logger.info(f"📥 已為冷門股 {ticker} 自 yfinance 建立全新 18 個月歷史快取 ({len(fresh_records)} 筆)")
                with get_connection(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM daily_kline WHERE ticker = ?", (ticker,))
                    row = cursor.fetchone()
                    min_date, max_date, count = row[0], row[1], row[2]

    # 3. 增量補齊：若最新日期落後昨日
    yesterday_str = (now_tw - timedelta(days=1)).strftime("%Y-%m-%d")
    if max_date and max_date < yesterday_str:
        # 抓取 [max_date + 1, today]
        inc_records = _fetch_yfinance_bars(ticker, market, max_date, today_str)
        if inc_records:
            for r in inc_records:
                r.setdefault("ticker", ticker)
            with get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.executemany("""
                INSERT OR REPLACE INTO daily_kline (ticker, date, open, high, low, close, volume)
                VALUES (:ticker, :date, :open, :high, :low, :close, :volume)
                """, inc_records)
            logger.info(f"🔄 增量更新 {ticker}: 補齊 {len(inc_records)} 筆日K ({max_date} -> {yesterday_str})")

    # 4. 撈出符合 target months 範圍的歷史資料
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT date, open, high, low, close, volume 
        FROM daily_kline 
        WHERE ticker = ? AND date >= ?
        ORDER BY date ASC
        """, (ticker, start_str))
        rows = cursor.fetchall()

    result = []
    for r in rows:
        result.append({
            "date": r["date"],
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"])
        })
    return result
