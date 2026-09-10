# -*- coding: utf-8 -*-
"""共用常數與時區設定（原 kline.py 開頭的模組層級設定，抽出供各子模組共用）"""
from datetime import timezone, timedelta

# 台股標準時區 (GMT+8)
TW_TZ = timezone(timedelta(hours=8))

__version__ = "3.3.0"

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
MA_DAYS = [5, 20, 60]
VOL_MA = 20
MA_COLORS = ["#f59e0b", "#6366f1", "#ec4899"]
MIN_SWING_R_PCT = 0.018  # 1.8% 最低健康波段空間門檻

# 波動度自適應停損參數（供 core.indicators.compute_risk_stop 使用）
STOP_ATR_MULT = 3.0
STOP_PCT_MIN = 0.08          # 最緊 -8%
STOP_PCT_MAX = 0.15          # 最寬 -15%
STOP_PCT_FALLBACK = 0.07     # 無法取得 ATR 時沿用原本的 -7%
STOP_PCT_DB_DEFAULT = -7.0   # positions.stop_loss_pct 的預設值，視為「自動」而非使用者自訂
