# -*- coding: utf-8 -*-
"""
台股專業 K 線量價 + 籌碼 + 技術形態多維研判系統
------------------------------------------------------
此檔案為相容性 facade：實際邏輯已拆分至 core/ 套件（依職責分為資料擷取、指標、
策略判讀、評級、繪圖、整合入口等子模組，見 core/__init__.py 說明）。

保留 kline.py 是為了不破壞既有呼叫方（app.py、bot_flex.py、line_server.py、
monitor_worker.py、backtest/ 等）目前使用的 `from kline import ...` 匯入方式。
新程式碼建議直接 `from core.xxx import ...`，逐步淘汰對本檔案的依賴。
"""

from core.constants import __version__, TW_TZ, HEADERS, MA_DAYS, VOL_MA, MA_COLORS, MIN_SWING_R_PCT
from core.data_fetch import (
    get_info, fetch_twse, fetch_from_yfinance, fetch_otc,
    fetch_realtime_bar, fetch_inst_finmind, fetch_institutional, fetch_fundamentals,
)
from core.indicators import get_tw_tick, compute_atr_pct, compute_risk_stop
from core.strategy_brooks import evaluate_brooks_price_action
from core.strategy_volume import evaluate_volume_price
from core.strategy_trend import evaluate_professional_trend
from core.rating import get_rating_badge, evaluate_composite_rating
from core.charting import build_stock_chart
from core.analyzer import analyze_stock, analyze_stock_5m, classify_candlestick_patterns
from core.kline_cache import get_daily_kline_records
from core.quote_hub import fetch_realtime_quotes_batch, fetch_realtime_quote

__all__ = [
    "__version__", "TW_TZ", "HEADERS", "MA_DAYS", "VOL_MA", "MA_COLORS", "MIN_SWING_R_PCT",
    "get_info", "fetch_twse", "fetch_from_yfinance", "fetch_otc",
    "fetch_realtime_bar", "fetch_inst_finmind", "fetch_institutional", "fetch_fundamentals",
    "get_tw_tick", "compute_atr_pct", "compute_risk_stop",
    "evaluate_brooks_price_action", "evaluate_volume_price", "evaluate_professional_trend",
    "get_rating_badge", "evaluate_composite_rating", "build_stock_chart",
    "analyze_stock", "analyze_stock_5m", "classify_candlestick_patterns",
    "get_daily_kline_records", "fetch_realtime_quotes_batch", "fetch_realtime_quote",
]


if __name__ == "__main__":
    # CLI 邏輯保留在 core/analyzer.py，等同執行：
    #   python -m core.analyzer 3042 --months 1 --cost 100
    import runpy
    runpy.run_module("core.analyzer", run_name="__main__")
