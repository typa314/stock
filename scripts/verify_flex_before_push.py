# -*- coding: utf-8 -*-
"""
scripts/verify_flex_before_push.py
強制驗證所有 LINE Flex Message 圖卡結構、非空文字與色碼規範（#RRGGBB / #RRGGBBAA），
並呼叫 LINE 官方 /v2/bot/message/validate/reply 端點實測驗證，
防止任何非法屬性（如 CSS rgba(...)、transparent 或空字串 text）未經檢查即被上傳部署。
"""

import os
import re
import sys
import json
import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT_DIR, ".env"))

import bot_flex
from core.decision_engine import arbitrate_signals

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


def find_invalid_flex_props(obj, path=""):
    """遞迴檢查 Flex JSON 內所有 color / backgroundColor / borderColor 與 text 屬性"""
    invalid = []
    if isinstance(obj, dict):
        if obj.get("type") == "text":
            txt_val = obj.get("text")
            if not isinstance(txt_val, str) or len(txt_val.strip()) == 0:
                invalid.append((f"{path}/text", txt_val))
        for k, v in obj.items():
            cur = f"{path}/{k}"
            if k in ("color", "backgroundColor", "borderColor"):
                if not isinstance(v, str) or not HEX_COLOR_RE.match(v):
                    invalid.append((cur, v))
            invalid.extend(find_invalid_flex_props(v, cur))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            invalid.extend(find_invalid_flex_props(item, f"{path}/{idx}"))
    return invalid


def build_all_sample_flex_cards():
    """組建全系統所有類型之 Flex 圖卡（含跨時框仲裁 5 種情境、關鍵價位地圖、持倉、自選）"""
    cards = {}

    res5_base = {
        "ticker": "6446",
        "stock_name": "藥華藥",
        "market": "two",
        "close_now": 1390.0,
        "change_today": 15.0,
        "change_today_pct": 1.09,
        "bpa_status": "🟢 多方控盤",
        "noise_ratio": 1.1,
        "action_tag": "🟢 順勢做多",
        "ema_now": 1380.0,
        "high_today": 1405.0,
        "low_today": 1370.0,
        "buy_stop": 1395.0,
        "sell_stop": 1365.0,
        "stop_loss": 1370.0,
        "target_1r": 1420.0,
        "target_2r": 1445.0,
        "fib_levels": {
            "ext_162": 1430.0,
            "ext_127": 1415.0,
            "fib_ladder": [
                {"ratio": "38.2%", "price": 1391.6, "meaning": "強勢淺回"},
                {"ratio": "50.0%", "price": 1387.5, "meaning": "中軸支撐"},
                {"ratio": "61.8%", "price": 1383.4, "meaning": "黃金分割"},
            ],
        },
    }

    scenarios = [
        ("BUY_NORMAL", {"composite_rating": {"score": 88, "action_type": "BUY"}, "bpa_res": {"always_in_zh": "🟢 多頭主升趨勢"}, "close_now": 1390.0, "ema20": 1363.41}, res5_base),
        ("SELL", {"composite_rating": {"score": 45, "action_type": "SELL"}, "bpa_res": {"always_in_zh": "🔴 空頭趨勢"}, "close_now": 1390.0, "ema20": 1420.0}, res5_base),
        ("AVOID_VOL", {"composite_rating": {"score": 88, "action_type": "BUY"}, "bpa_res": {"always_in_zh": "🟢 多頭主升趨勢"}, "close_now": 1390.0, "ema20": 1363.41}, {**res5_base, "is_noise_extreme": True, "noise_ratio": 3.2}),
        ("WAIT_DULL", {"composite_rating": {"score": 88, "action_type": "BUY"}, "bpa_res": {"always_in_zh": "🟢 多頭主升趨勢"}, "close_now": 1390.0, "ema20": 1363.41}, {**res5_base, "is_vol_dull": True, "noise_ratio": 0.3}),
        ("HOLD", {"composite_rating": {"score": 74, "action_type": "HOLD"}, "bpa_res": {"always_in_zh": "🟡 箱型震盪"}, "close_now": 1390.0, "ema20": 1363.41}, res5_base),
    ]

    for name, d_res, r5 in scenarios:
        arb = arbitrate_signals(d_res, r5)
        b_daily = bot_flex.build_dashboard_stock_flex(
            stock_name="藥華藥", ticker="6446", market="two",
            close_now=1390.0, chg_val=15.0, chg_pct=1.09,
            realtime_info={"is_realtime": True, "time": "13:30:00"}, df=None,
            bpa_res=d_res["bpa_res"], trend_score=85, trend_stage="第二階段",
            rating_badge="A+", comp=d_res["composite_rating"],
            sr={"s1": 1350.0, "r1": 1420.0}, arbitration=arb
        )
        b_5m = bot_flex.build_5m_stock_flex(r5, arbitration=arb)
        b_map = bot_flex.build_key_levels_flex(r5, daily_res=d_res, arbitration=arb)
        cards[f"carousel_{name}"] = bot_flex.build_stock_carousel_flex(b_daily, b_5m, b_map)

    cards["portfolio"] = bot_flex.build_portfolio_flex(
        "測試用戶",
        [{
            "ticker": "2330", "stock_name": "台積電", "shares": 1000,
            "cost_price": 950.0, "current_price": 1000.0,
            "pnl": 5.26, "pnl_pct": 5.26, "pnl_amount": 50000,
            "stop_7": 880.0, "buf_7": 12.0, "tag": "續抱", "tag_color": "#4ade80"
        }],
        50000, 5.26
    )

    cards["watchlist"] = bot_flex.build_watchlist_flex(
        "測試用戶",
        [{
            "ticker": "2330", "stock_name": "台積電",
            "current_price": 1000.0, "chg_val": 10.0, "chg_pct": 1.01,
            "bpa_zh": "多頭趨勢", "bpa_color": "#4ade80", "dist_desc": "距月線 +1.5%"
        }]
    )

    return cards


def verify_all_flex_cards(require_online_validate=False):
    """執行本地靜態色碼/非空文字檢查與（可選）LINE 官方 API 驗證"""
    cards = build_all_sample_flex_cards()
    all_invalid = []
    for name, payload in cards.items():
        inv = find_invalid_flex_props(payload, path=f"[{name}]")
        all_invalid.extend(inv)

    if all_invalid:
        raise AssertionError(f"❌ LINE Flex 圖卡包含非法屬性（LINE API 將退回 HTTP 400）: {all_invalid}")

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip().strip('"').strip("'")
    if token and token != "YOUR_CHANNEL_ACCESS_TOKEN":
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        for key in ("carousel_BUY_NORMAL", "carousel_SELL", "carousel_AVOID_VOL", "carousel_WAIT_DULL", "carousel_HOLD", "portfolio", "watchlist"):
            r = requests.post(
                "https://api.line.me/v2/bot/message/validate/reply",
                headers=headers,
                json={"messages": [{"type": "flex", "altText": f"Validate {key}", "contents": cards[key]}]},
                timeout=10,
            )
            if r.status_code != 200:
                raise AssertionError(f"❌ LINE 官方 API 驗證失敗 ({key}): HTTP {r.status_code} {r.text}")
    elif require_online_validate:
        raise AssertionError("❌ 未偵測到 LINE_CHANNEL_ACCESS_TOKEN，無法執行 LINE 官方 API 強制驗證")

    return True


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify_all_flex_cards()
        print("✅ [PRE-PUSH GUARD] LINE Flex Message 全數圖卡色碼、非空文字與 LINE 官方 API 驗證 100% 通過！")
        sys.exit(0)
    except Exception as e:
        print(f"🚨 [PRE-PUSH GUARD 攔截] {e}", file=sys.stderr)
        sys.exit(1)
