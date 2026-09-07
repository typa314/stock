# -*- coding: utf-8 -*-
"""
monitor_worker.py - 盤中風控巡邏守護引擎
平日交易時段（09:00~13:35）每 60 秒批次比對所有用戶持股
當現價跌破 -7% 強制停損時，透過 LINE Push Notification 發送緊急警報
內建單日單股去重冷卻機制，確保每月用量極低（<20則），守護官方 200 則免費額度
"""

import os
import sys
import time
import logging
from datetime import datetime

# 確保當前目錄在模組搜尋路徑第一位
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(current_dir, ".env"))

import bot_db
import bot_flex
from kline import get_info, fetch_realtime_bar

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("monitor_worker")

CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "YOUR_CHANNEL_ACCESS_TOKEN").strip().strip('"').strip("'")

line_bot_api = None
try:
    from linebot import LineBotApi
    from linebot.models import FlexSendMessage
    if CHANNEL_ACCESS_TOKEN != "YOUR_CHANNEL_ACCESS_TOKEN":
        line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
        logger.info("巡邏 Worker: LINE Push API 成功啟用！")
except Exception as e:
    logger.warning(f"巡邏 Worker: LINE SDK 未設定憑證，執行模擬告警模式: {e}")

def is_market_open(force_test=False):
    """判斷當前是否為台股開盤時段 (平日 09:00 ~ 13:35)"""
    if force_test:
        return True
    now = datetime.now()
    if now.weekday() >= 5:  # 週六日休市
        return False
    now_min = now.hour * 60 + now.minute
    return (9 * 60) <= now_min <= (13 * 60 + 35)

def run_patrol_cycle(force_test=False):
    """執行一次持股風控巡邏比對"""
    active_positions = bot_db.get_all_active_positions()
    if not active_positions:
        logger.debug("目前無活躍持倉監控需求。")
        return 0

    alerts_triggered = 0
    # 收集需要查詢即時行情的標的（去重查詢，節省 API）
    ticker_market_map = {}
    for p in active_positions:
        t = p["ticker"]
        if t not in ticker_market_map:
            market, sname = get_info(t)
            ticker_market_map[t] = (market, sname or p.get("stock_name", t))

    # 批次取得各標的最新現價
    price_cache = {}
    for t, (market, sname) in ticker_market_map.items():
        rt = fetch_realtime_bar(t, market)
        if rt and rt.get("close") and rt["close"] > 0:
            price_cache[t] = float(rt["close"])
        else:
            logger.debug(f"標的 {t} 暫無法取得盤中撮合價，跳過本次檢查。")

    # 逐一檢查持倉是否跌破停損線
    for p in active_positions:
        t = p["ticker"]
        if t not in price_cache:
            continue

        cur_p = price_cache[t]
        cost_p = float(p["cost_price"])
        stop_7 = round(cost_p * 0.93, 2)
        user_id = p["user_id"]
        line_user_id = p["line_user_id"]
        _, sname = ticker_market_map.get(t, ("tse", t))

        # 判定是否跌破 -7%
        if cur_p <= stop_7:
            # 檢查今日是否已發送過告警（去重防騷擾）
            if bot_db.should_send_alert(user_id, t, "STOP_LOSS_7"):
                diff_pct = (cur_p - cost_p) / cost_p * 100
                logger.warning(f"🚨 觸發強制停損！用戶 {line_user_id} 標的 {t} 現價 {cur_p} 跌破停損線 {stop_7}")

                alert_flex = bot_flex.build_stop_loss_alert_flex(
                    sname, t, cur_p, cost_p, stop_7, diff_pct
                )

                if line_bot_api:
                    try:
                        msg = FlexSendMessage(alt_text=f"🚨【強制停損告警】{sname} ({t}) 跌破 -7%", contents=alert_flex)
                        line_bot_api.push_message(line_user_id, msg)
                        logger.info(f"已發送 Push 推播至 LINE 用戶 {line_user_id}")
                    except Exception as e:
                        logger.error(f"發送 LINE Push 失敗: {e}")
                else:
                    logger.info(f"[模擬推播] 發送緊急停損卡至用戶 {line_user_id}")

                # 記錄已發送日誌（今日不再重複通知）
                bot_db.record_alert_log(user_id, t, "STOP_LOSS_7", cur_p)
                alerts_triggered += 1

    return alerts_triggered

def start_worker_loop(interval_sec=60, force_test=False):
    """巡邏循環主函數"""
    logger.info(f"盤中風控巡邏 Worker 啟動！巡邏間隔: {interval_sec} 秒 (測試模式: {force_test})")
    while True:
        try:
            if is_market_open(force_test=force_test):
                logger.info("執行盤中風控巡邏比對...")
                triggered = run_patrol_cycle(force_test=force_test)
                if triggered > 0:
                    logger.info(f"本次巡邏發出 {triggered} 則停損告警。")
            else:
                logger.debug("目前非盤中交易時段，休眠中...")
        except Exception as e:
            logger.error(f"巡邏 Worker 異常: {e}", exc_info=True)

        time.sleep(interval_sec)

if __name__ == "__main__":
    # 若直接執行預設為強制測試 1 次
    run_patrol_cycle(force_test=True)
