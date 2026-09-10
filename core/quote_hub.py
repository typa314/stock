# -*- coding: utf-8 -*-
"""
core/quote_hub.py - 中央即時報價 Hub (Central Quote Hub)
------------------------------------------------------
職責：
  1. TWSE MIS 官方撮合 API 批次查詢（支援 ex_ch 多檔合併，每批上限 20 檔）。
  2. 全域速率控制器（Global Rate Limiter）：強制限制任兩次對 TWSE MIS 的請求間隔 >= 2.0 秒，
     並以執行緒鎖（Thread Lock）徹底消除瞬間併發（Burst Concurrency），杜絕觸發 5 秒 3 次被 Ban 的風險。
  3. 雙軌備援架構：TWSE MIS 失敗或冷門標的未回傳時，自動以 Yahoo Finance 批次備援。
  4. 專責時效性需求（查現價、算損益、盤中停損巡邏），徹底與 5分K 歷史時框解耦。
"""

import time
import math
import logging
import threading
from datetime import datetime
import requests
import pandas as pd
import yfinance as yf

from core.constants import TW_TZ, HEADERS

logger = logging.getLogger("quote_hub")


class GlobalRateLimiter:
    """
    執行緒安全的全域冷卻限流器 (Cool-down Guard)
    確保對外部敏感 API（TWSE MIS）的呼叫間隔至少大於 min_interval 秒。
    """
    def __init__(self, min_interval: float = 2.0):
        self.min_interval = min_interval
        self.last_call_time = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self.last_call_time
            if elapsed < self.min_interval:
                sleep_needed = self.min_interval - elapsed
                logger.debug(f"[RateLimiter] 冷卻等待 {sleep_needed:.2f} 秒以符合 TWSE 速率規範...")
                time.sleep(sleep_needed)
            self.last_call_time = time.time()


# 全域單例限流器（強制單次間隔 >= 2.0 秒，杜絕 5 秒 3 次封鎖線）
twse_limiter = GlobalRateLimiter(min_interval=2.0)


def _parse_twse_item(item: dict) -> dict:
    """解析 TWSE MIS msgArray 的單一股票行情項目"""
    ticker = item.get("c", "").strip()
    p_str = item.get("z", "-")

    # 若最新撮合價 z 為 '-'，fallback 讀取委買、委賣首檔或昨收 y
    if not p_str or p_str == "-":
        bids = [b for b in item.get("b", "").split("_") if b]
        asks = [a for a in item.get("a", "").split("_") if a]
        if bids:
            p_str = bids[0]
        elif asks:
            p_str = asks[0]
        else:
            p_str = item.get("y", "-")

    if not p_str or p_str == "-":
        return None

    price = float(p_str)
    open_p = float(item.get("o", price)) if item.get("o") and item.get("o") != "-" else price
    high_p = float(item.get("h", price)) if item.get("h") and item.get("h") != "-" else price
    low_p  = float(item.get("l", price)) if item.get("l") and item.get("l") != "-" else price
    vol    = float(item.get("v", 0)) if item.get("v") and item.get("v") != "-" else 0.0
    d_str  = item.get("d", "")
    t_str  = item.get("t", "")
    d_obj  = pd.to_datetime(d_str, format="%Y%m%d") if d_str else pd.Timestamp.now().normalize()

    return {
        "ticker": ticker,
        "name": item.get("n", ""),
        "date": d_obj,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": price,
        "volume": vol,
        "time": t_str,
        "is_realtime": True,
        "source": "TWSE MIS 官方撮合"
    }


def _fetch_yahoo_fallback(ticker: str, market: str) -> dict:
    """軌道 2：Yahoo Finance 單檔備援"""
    try:
        sym = f"{ticker}.TW" if market == "tse" else f"{ticker}.TWO"
        y_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
        r = requests.get(y_url, headers=HEADERS, timeout=5)
        chart = r.json().get("chart", {}).get("result", [])
        if chart:
            meta = chart[0]["meta"]
            price = float(meta["regularMarketPrice"])
            high_p = float(meta.get("regularMarketDayHigh", price))
            low_p  = float(meta.get("regularMarketDayLow", price))
            open_p = None
            if meta.get("regularMarketOpen") is not None:
                open_p = float(meta["regularMarketOpen"])
            elif meta.get("regularMarketDayOpen") is not None:
                open_p = float(meta["regularMarketDayOpen"])
            else:
                quote = chart[0].get("indicators", {}).get("quote", [{}])[0]
                opens = [x for x in quote.get("open", []) if x is not None]
                if opens:
                    open_p = float(opens[0])
                else:
                    open_p = price

            vol    = float(meta.get("regularMarketVolume", 0)) / 1000.0
            return {
                "ticker": ticker,
                "date": pd.Timestamp.now(tz=TW_TZ).normalize().tz_localize(None),
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": price,
                "volume": vol,
                "time": datetime.now(TW_TZ).strftime("%H:%M:%S"),
                "is_realtime": True,
                "source": "Yahoo Finance 即時"
            }
    except Exception:
        pass
    return None



def fetch_realtime_quotes_batch(items: list, chunk_size: int = 20) -> dict:
    """
    中央批次報價入口：
    傳入格式：[("2330", "tse"), ("2454", "tse"), ("6182", "otc")] 或 dict 列表
    回傳字典：{ "2330": {...}, "2454": {...} }
    """
    if not items:
        return {}

    # 正規化輸入為 (ticker, market) 列表
    pairs = []
    for it in items:
        if isinstance(it, tuple):
            pairs.append((str(it[0]).strip(), str(it[1]).lower().strip()))
        elif isinstance(it, dict):
            t = str(it.get("ticker", "")).strip()
            m = str(it.get("market", "tse")).lower().strip()
            pairs.append((t, m))
        elif isinstance(it, str):
            pairs.append((it.strip(), "tse"))

    # 去重
    unique_pairs = list({p[0]: p for p in pairs}.values())
    results = {}

    # 分批切塊（Chunking，每批 <= 20 檔，避免 URL 過長與伺服器逾時）
    for i in range(0, len(unique_pairs), chunk_size):
        chunk = unique_pairs[i:i + chunk_size]
        ex_chs = []
        for t, m in chunk:
            pfx = "tse" if m == "tse" else "otc"
            ex_chs.append(f"{pfx}_{t}.tw")

        ch_param = "|".join(ex_chs)
        ts = int(time.time() * 1000)
        mis_url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ch_param}&json=1&delay=0&_={ts}"

        # 執行緒鎖與全域冷卻等待 (>= 2.0s)
        twse_limiter.wait()

        try:
            r = requests.get(mis_url, headers=HEADERS, timeout=6)
            data = r.json().get("msgArray", [])
            for raw_item in data:
                parsed = _parse_twse_item(raw_item)
                if parsed and parsed.get("ticker"):
                    results[parsed["ticker"]] = parsed
        except Exception as e:
            logger.warning(f"TWSE MIS 批次查詢異常: {e}")

        # 檢查該批是否有漏掉的標的，啟動 Yahoo Finance 備援補齊
        for t, m in chunk:
            if t not in results:
                fb = _fetch_yahoo_fallback(t, m)
                if fb:
                    results[t] = fb

    return results


def fetch_realtime_quote(ticker: str, market: str = "tse") -> dict:
    """單一標的即時撮合價查詢（透過中央 Hub 調度與限流）"""
    res = fetch_realtime_quotes_batch([(ticker, market)])
    return res.get(str(ticker).strip())
