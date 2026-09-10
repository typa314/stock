# -*- coding: utf-8 -*-
"""core 套件：台股量化分析引擎的核心邏輯，依職責拆分為子模組。

- constants        共用常數（時區、均線設定、停損參數等）
- data_fetch       外部資料來源（TWSE / yfinance / FinMind）擷取
- indicators       純數值指標計算（tick 級距、ATR、風控停損價）
- strategy_brooks  Al Brooks 價格行為學（BPA）判讀
- strategy_volume  Wyckoff / VPA 量價結構評估
- strategy_trend   Stan Weinstein 趨勢階段與專業趨勢研判
- rating           綜合評級（Minervini / CANSLIM / BPA / 籌碼）
- charting         Plotly 圖表繪製
- analyzer         整合以上模組的主要對外入口（analyze_stock / analyze_stock_5m）
"""
