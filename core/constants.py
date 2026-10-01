# -*- coding: utf-8 -*-
"""共用常數與時區設定（原 kline.py 開頭的模組層級設定，抽出供各子模組共用）"""
from datetime import timezone, timedelta

# 台股標準時區 (GMT+8)
TW_TZ = timezone(timedelta(hours=8))

__version__ = "3.6.0"


HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
MA_DAYS = [5, 20, 60]
VOL_MA = 20
MA_COLORS = ["#f59e0b", "#6366f1", "#ec4899"]
MIN_SWING_R_PCT = 0.018  # 1.8% 最低健康波段空間門檻

# 波動度自適應停損參數（供 core.indicators.compute_risk_stop 使用）
# 回測實證：2.5×ATR 於 20~60 日波段績效優於 3.0×ATR；-7% 剛性停損明確傷害 60 日報酬
STOP_ATR_MULT = 2.5          # 動態停損乘數（由 3.0 調整為 2.5，貼近結構性低點防守）
STOP_PCT_MIN = 0.08          # 最緊防守上限 -8%（防日內雜訊洗出場）
STOP_PCT_MAX = 0.15          # 最寬風險下限 -15%（鎖定單筆最大虧損）
STOP_PCT_FALLBACK = 0.07     # 無法取得 ATR 時退回 -7%（兼容舊邏輯）
STOP_PCT_DB_DEFAULT = -7.0   # positions.stop_loss_pct 的預設值，視為「自動」而非使用者自訂

# ── 評分懲罰常數 (Rating Calibration Penalty Constants) ──
# 用於 core/rating.py 的動態扣分，所有門檻集中於此方便回測微調
PENALTY_BIAS_TIER1_THRESHOLD = 8.0    # 正乖離 > +8%：第一階過熱警戒
PENALTY_BIAS_TIER1_POINTS    = 12     # 扣 12 分
PENALTY_BIAS_TIER2_THRESHOLD = 12.0   # 正乖離 > +12%：第二階嚴重過熱
PENALTY_BIAS_TIER2_POINTS    = 20     # 扣 20 分
PENALTY_VOL_DULL_THRESHOLD   = 0.70   # 當日量能 < 20MA × 0.70：量縮警戒
PENALTY_VOL_DULL_POINTS      = 8      # 額外扣 8 分（防高乖離+縮量雙重過熱）
