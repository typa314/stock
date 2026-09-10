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
from datetime import datetime, timezone, timedelta
import pandas as pd

# 台股標準時區 (GMT+8)
TW_TZ = timezone(timedelta(hours=8))

# 確保當前目錄在模組搜尋路徑第一位
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(current_dir, ".env"))

import bot_db
import bot_flex
from kline import get_info, fetch_realtime_bar, analyze_stock, compute_risk_stop

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

import threading
from cachetools import TTLCache

# ── 盤中巡檢快取機制（使用 cachetools.TTLCache 防過度請求外部 API 與記憶體洩漏） ──
# 盤中全量分析快取：最多 128 檔，TTL 60 秒
_WORKER_ANALYSIS_CACHE = TTLCache(maxsize=128, ttl=60)
_WORKER_ANALYSIS_LOCK = threading.Lock()

# 盤中即時撮合現價快取：最多 256 檔，TTL 10 秒
_WORKER_PRICE_CACHE = TTLCache(maxsize=256, ttl=10)
_WORKER_PRICE_LOCK = threading.Lock()

def is_market_open(force_test=False):
    """判斷當前是否為台股開盤時段 (平日 09:00 ~ 13:35，嚴格鎖定台股 GMT+8 時區)"""
    if force_test:
        return True
    now = datetime.now(TW_TZ)
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

    # 批次取得各標的最新現價（優先檢查 10s TTLCache 避免過度頻繁打 TWSE API）
    price_cache = {}
    for t, (market, sname) in ticker_market_map.items():
        with _WORKER_PRICE_LOCK:
            if t in _WORKER_PRICE_CACHE:
                price_cache[t] = _WORKER_PRICE_CACHE[t]
                continue

        rt = fetch_realtime_bar(t, market)
        if rt and rt.get("close") and rt["close"] > 0:
            p_val = float(rt["close"])
            price_cache[t] = p_val
            with _WORKER_PRICE_LOCK:
                _WORKER_PRICE_CACHE[t] = p_val
        else:
            logger.debug(f"標的 {t} 暫無法取得盤中撮合價，跳過本次檢查。")

    # 逐一檢查持倉是否跌破停損線
    for p in active_positions:
        t = p["ticker"]
        if t not in price_cache:
            continue

        cur_p = price_cache[t]
        cost_p = float(p["cost_price"])
        mkt, sname_map = ticker_market_map.get(t, ("tse", t))
        # 波動度自適應警戒價位（回測實證固定 -7% 為淨損失，詳見 kline.compute_risk_stop）
        stop_7, stop_pct, stop_basis = compute_risk_stop(
            t, cost_p, market=mkt, user_pct=p.get("stop_loss_pct")
        )
        user_id = p["user_id"]
        line_user_id = p["line_user_id"]
        sname = sname_map

        # 判定是否跌破浮虧警戒線
        if cur_p <= stop_7:
            # 檢查今日是否已發送過告警（去重防騷擾）
            if bot_db.should_send_alert(user_id, t, "STOP_LOSS_7"):
                diff_pct = (cur_p - cost_p) / cost_p * 100
                logger.warning(f"⚠️ 觸發浮虧警戒！用戶 {line_user_id} 標的 {t} 現價 {cur_p} 跌破警戒線 {stop_7}（-{stop_pct*100:.1f}%，依據 {stop_basis}）({diff_pct:.2f}%)")

                alert_flex = bot_flex.build_stop_loss_alert_flex(
                    sname, t, cur_p, cost_p, stop_7, diff_pct,
                    stop_pct=stop_pct, stop_basis=stop_basis
                )

                if line_bot_api:
                    try:
                        msg = FlexSendMessage(alt_text=f"⚠️【浮虧警戒告警】{sname} ({t}) 跌破 -{stop_pct*100:.1f}% 警戒線", contents=alert_flex)
                        line_bot_api.push_message(line_user_id, msg)
                        logger.info(f"已發送 Push 推播至 LINE 用戶 {line_user_id}")
                    except Exception as e:
                        logger.error(f"發送 LINE Push 失敗: {e}")
                else:
                    logger.info(f"[模擬推播] 發送浮虧警戒卡至用戶 {line_user_id}")

                # 記錄已發送日誌（今日不再重複通知）
                bot_db.record_alert_log(user_id, t, "STOP_LOSS_7", cur_p)
                alerts_triggered += 1

    return alerts_triggered

def check_bottom_confirmation_signals(ticker, market="tse", analysis_res=None):
    """
    評估股票是否觸發 BPA 高勝率底部回測確認買點：
    1. High 2 (H2) 雙重底推動確認（ABC 兩段回檔結束）
    2. 20 EMA 動態支撐回測守穩 (20 EMA Pullback)
    3. S1 (月線/前低) 關鍵支撐回測多頭反轉棒 (Bull Reversal)
    4. 價跌量縮良性洗盤守穩 (Wyckoff / VPA)
    """
    try:
        if analysis_res is not None:
            res = analysis_res
        else:
            with _WORKER_ANALYSIS_LOCK:
                res = _WORKER_ANALYSIS_CACHE.get(ticker)
            if res is None:
                res = analyze_stock(ticker, months=12, generate_html=False, print_report=False)
                if res and "close_now" in res:
                    with _WORKER_ANALYSIS_LOCK:
                        _WORKER_ANALYSIS_CACHE[ticker] = res

        df = res.get("df")
        bpa_res = res.get("bpa_res", {})
        sr = res.get("sr_levels", {})
        close_now = float(res.get("close_now", 0.0))
        sname = res.get("stock_name", ticker)

        if df is None or df.empty or close_now <= 0:
            return {"triggered": False}

        # ── 綜合評分品質門檻 (Composite Quality Gate) ──
        # 回測實證顯示：未過濾之底部訊號 20 日超額為負 (-0.52%)，勝率低於基準。
        # 必須在整體大格局偏多且體質優良之標的方能觸發買點推播。
        comp = res.get("composite_rating")
        if comp is not None and isinstance(comp, dict):
            comp_score = comp.get("score", 0)
            # 價跌量縮良性洗盤 (唯一具正向超額訊號) 要求 >= 65；其餘形態 (H2, EMA PB, S1 反轉) 要求 >= 80
            min_score = 65 if (
                len(df) >= 2 and "vol_ma" in df.columns and float(df["volume"].iloc[-1]) <= 0.65 * float(df["vol_ma"].iloc[-1])
            ) else 80
            if comp_score < min_score:
                logger.info(f"【{ticker}】雖有局部技術形態，但綜合評分 {comp_score} 分未達品質門檻 ({min_score} 分)，攔截推播！")
                return {"triggered": False}

        always_code = bpa_res.get("always_in_code", "TR")
        signals = bpa_res.get("signals", [])
        ema20_val = float(df["ema20"].iloc[-1]) if ("ema20" in df.columns and not df.empty) else close_now
        last_bar = bpa_res.get("last_bar_type", "")

        # ── 籌碼硬門檻審核 (Institutional Hard Gate) ──
        # 若近 3 日三大法人合計大賣超過 300 張，視為主力持續提款，技術面反彈極易破底，嚴格攔截不予推播
        inst_df = res.get("inst_df")
        if inst_df is not None and not inst_df.empty and "total" in inst_df.columns:
            inst_net_3d = int(inst_df["total"].tail(3).sum())
            if inst_net_3d < -300:
                logger.info(f"【{ticker}】雖然可能浮現技術回測，但法人近3日大幅賣超 {inst_net_3d} 張，觸發籌碼硬門檻攔截！")
                return {"triggered": False}

        # ── Conformal 不確定性拒絕機制 (Extreme Volatility Abstention) ──
        # 若當日波幅大於近 20 日平均真實波幅 (ATR) 的 2.5 倍，市場處於極端巨震混亂期，置信度不足，主動放棄開倉推播
        if len(df) >= 5 and "high" in df.columns and "low" in df.columns and "close" in df.columns:
            tr1 = df["high"] - df["low"]
            tr2 = (df["high"] - df["close"].shift(1)).abs()
            tr3 = (df["low"] - df["close"].shift(1)).abs()
            daily_tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr20_d = float(daily_tr.tail(20).mean()) if len(daily_tr) >= 5 else 1.0
            today_rng = float(df["high"].iloc[-1] - df["low"].iloc[-1])
            if atr20_d > 0 and (today_rng / atr20_d) > 2.5:
                logger.info(f"【{ticker}】當日振幅 ({today_rng:.2f}元) 超過 20 日 ATR ({atr20_d:.2f}元) 之 2.5 倍，觸發 Conformal 拒絕開倉門檻！")
                return {"triggered": False}

        # ── 方案二：HMM 市場狀態雙層濾網 (Two-Stage Regime Gate) ──
        # 回測實證：處於 HMM 高波震盪洗盤 (Adverse/Churn) 期間，底部訊號 20 日勝率僅 49.3%、平均報酬僅 +1.33%
        # 徹底攔截惡劣市況下的脆弱抄底推播，大幅節省 LINE 免費推播額度
        regime_info = res.get("regime_info")
        if regime_info and regime_info.get("is_adverse", False):
            logger.info(f"【{ticker}】當前處於 HMM 高波震盪市況 (避開震盪抄底)，觸發市場狀態硬閘道攔截推播！")
            return {"triggered": False}
        regime_status = regime_info.get("regime_name", "🟢 順勢波段環境") if regime_info else "🟢 順勢波段環境"

        # ── 籌碼與雜訊指標標籤 ──
        inst_status = "法人籌碼安全 (未見大額拋售)"
        if inst_df is not None and not inst_df.empty and "total" in inst_df.columns:
            inst_net_3d = int(inst_df["total"].tail(3).sum())
            inst_status = f"法人籌碼安全 (近3日累計 {inst_net_3d:+d}張)"

        conformal_status = "Conformal 雜訊合格 (波動受控)"
        if len(df) >= 5 and "high" in df.columns and "low" in df.columns and "close" in df.columns:
            tr1 = df["high"] - df["low"]
            tr2 = (df["high"] - df["close"].shift(1)).abs()
            tr3 = (df["low"] - df["close"].shift(1)).abs()
            daily_tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr20_d = float(daily_tr.tail(20).mean()) if len(daily_tr) >= 5 else 1.0
            today_rng = float(df["high"].iloc[-1] - df["low"].iloc[-1])
            if atr20_d > 0:
                conformal_status = f"Conformal 雜訊合格 ({today_rng / atr20_d:.2f}x ATR)"

        # 1. High 2 (H2) 雙重底推動確認
        # 時效過濾：bpa_h2 必須在最近 5 根日K 棒內（避免過期訊號觸發推播）
        h2_recent = "bpa_h2" in df.columns and bool(df["bpa_h2"].tail(5).any()) and always_code in ["AIL", "TR"]
        is_h2 = any("High 2" in s or "H2" in s for s in signals) and h2_recent
        if not is_h2:
            is_h2 = h2_recent  # signals 未含關鍵字時，改用 df 欄位判斷（仍需時效過濾）
        if is_h2:
            return {
                "triggered": True,
                "signal_name": "🔥 High 2 (H2) 雙重底回踩買點",
                "signal_desc": "波段回檔 ABC 兩段修正結束，空方兩度向下試探無力跌破，多頭重啟順勢推升！",
                "buy_stop": bpa_res.get("buy_stop", round(close_now * 1.01, 2)),
                "sell_stop": bpa_res.get("sell_stop", round(close_now * 0.98, 2)),
                "target_1r": bpa_res.get("target_long_1r", round(close_now * 1.03, 2)),
                "target_2r": bpa_res.get("target_long_2r", round(close_now * 1.06, 2)),
                "close_now": close_now,
                "stock_name": sname,
                "market": market,
                "inst_status": inst_status,
                "conformal_status": conformal_status,
                "regime_status": regime_status
            }

        # 2. 20 EMA 動態支撐回測守穩
        is_ema_pb = any("20 EMA 動態支撐回測" in s for s in signals) or (
            "bpa_ema_pb" in df.columns and bool(df["bpa_ema_pb"].tail(2).any()) and always_code == "AIL" and close_now >= ema20_val * 0.99
        )
        if is_ema_pb:
            return {
                "triggered": True,
                "signal_name": "🛡️ 20 EMA 動態支撐回踩守穩",
                "signal_desc": f"多頭強勢主升段回踩 20 EMA（{ema20_val:.2f} 元）動態支撐，洗盤沉澱完畢，獲利了結賣壓耗竭！",
                "buy_stop": bpa_res.get("buy_stop", round(close_now * 1.01, 2)),
                "sell_stop": bpa_res.get("sell_stop", round(close_now * 0.98, 2)),
                "target_1r": bpa_res.get("target_long_1r", round(close_now * 1.03, 2)),
                "target_2r": bpa_res.get("target_long_2r", round(close_now * 1.06, 2)),
                "close_now": close_now,
                "stock_name": sname,
                "market": market,
                "inst_status": inst_status,
                "conformal_status": conformal_status,
                "regime_status": regime_status
            }

        # 3. S1 關鍵支撐多頭反轉棒 (Bull Reversal at S1)
        s1 = float(sr.get("s1", 0.0))
        today_low = float(df["low"].iloc[-1])
        if s1 > 0 and today_low <= s1 * 1.015 and close_now >= s1 * 0.995:
            if "多頭反轉棒" in last_bar or "多頭趨勢棒" in last_bar or "High 1" in " ".join(signals):
                return {
                    "triggered": True,
                    "signal_name": "🔨 S1 關鍵支撐回測多頭反轉",
                    "signal_desc": f"股價精確回測 S1（{s1:.2f} 元）重要防守位，浮現顯著下影線拒絕破底，多頭強力承接守穩！",
                    "buy_stop": bpa_res.get("buy_stop", round(close_now * 1.01, 2)),
                    "sell_stop": bpa_res.get("sell_stop", round(close_now * 0.98, 2)),
                    "target_1r": bpa_res.get("target_long_1r", round(close_now * 1.03, 2)),
                    "target_2r": bpa_res.get("target_long_2r", round(close_now * 1.06, 2)),
                    "close_now": close_now,
                    "stock_name": sname,
                    "market": market,
                    "inst_status": inst_status,
                    "conformal_status": conformal_status,
                    "regime_status": regime_status
                }

        # 4. 價跌量縮良性洗盤守穩 (Wyckoff / VPA)
        if len(df) >= 2 and "vol_ma" in df.columns:
            cur_vol = float(df["volume"].iloc[-1])
            vol_ma = float(df["vol_ma"].iloc[-1])
            prev_c = float(df["close"].iloc[-2])
            chg_p = (close_now - prev_c) / prev_c * 100
            # 最低量能護欄：cur_vol > vol_ma * 0.15，避免盤前/盤後極低量誤觸發
            wyckoff_vol_ok = vol_ma > 0 and cur_vol <= 0.65 * vol_ma and cur_vol > vol_ma * 0.15
            if -2.5 <= chg_p < 0 and wyckoff_vol_ok and close_now >= ema20_val * 0.99 and always_code in ["AIL", "TR"]:
                return {
                    "triggered": True,
                    "signal_name": "💤 價跌量縮良性洗盤守穩",
                    "signal_desc": f"回測月線呈現典型窒息量洗盤，量能僅 20MA 的 {(cur_vol/vol_ma)*100:.0f}%，主力惜售無拋壓，守穩關鍵均線！",
                    "buy_stop": bpa_res.get("buy_stop", round(close_now * 1.01, 2)),
                    "sell_stop": bpa_res.get("sell_stop", round(close_now * 0.98, 2)),
                    "target_1r": bpa_res.get("target_long_1r", round(close_now * 1.03, 2)),
                    "target_2r": bpa_res.get("target_long_2r", round(close_now * 1.06, 2)),
                    "close_now": close_now,
                    "stock_name": sname,
                    "market": market,
                    "inst_status": inst_status,
                    "conformal_status": conformal_status,
                    "regime_status": regime_status
                }
    except Exception as e:
        logger.error(f"檢查標的 {ticker} 回測買點信號異常: {e}")

    return {"triggered": False}

def run_watchlist_patrol_cycle(force_test=False):
    """
    執行觀察名單 BPA 高勝率底部回測買點掃描
    僅對當日尚未推播過 BPA_BUY_SETUP 的用戶與標的進行判定
    """
    active_items = bot_db.get_all_active_watchlist()
    if not active_items:
        logger.debug("目前無活躍自選觀察名單需求。")
        return 0

    alerts_triggered = 0
    # 依 ticker 分組待檢查用戶，避免重複運算同一檔股票
    ticker_users_map = {}
    for item in active_items:
        t = item["ticker"]
        uid = item["user_id"]
        # 檢查 5 日內是否已發送過買點通知（5日冷卻去重，經回測實證可創造顯著超額並降低推播頻率）
        if bot_db.should_send_alert(uid, t, "BPA_BUY_SETUP", cooldown_days=5) or force_test:
            if t not in ticker_users_map:
                ticker_users_map[t] = []
            ticker_users_map[t].append(item)

    if not ticker_users_map:
        return 0

    # 針對有推播需求的標的進行信號判定
    for t, user_items in ticker_users_map.items():
        market, _ = get_info(t)
        sig = check_bottom_confirmation_signals(t, market=market)

        if sig.get("triggered"):
            sname = sig.get("stock_name", t)
            close_now = sig.get("close_now", 0.0)
            sig_name = sig.get("signal_name", "高勝率買點")
            sig_desc = sig.get("signal_desc", "")
            buy_stop = sig.get("buy_stop", close_now)
            sell_stop = sig.get("sell_stop", close_now)
            t1 = sig.get("target_1r", close_now)
            t2 = sig.get("target_2r", close_now)

            logger.info(f"🎯 標的 {t} 觸發回測確認買點：{sig_name}！")

            alert_flex = bot_flex.build_buy_signal_alert_flex(
                sname, t, sig_name, sig_desc, close_now,
                buy_stop, sell_stop, t1, t2,
                inst_status=sig.get("inst_status", "法人籌碼安全 (未見大額拋售)"),
                conformal_status=sig.get("conformal_status", "Conformal 雜訊合格 (波動受控)"),
                regime_status=sig.get("regime_status", "🟢 順勢波段環境")
            )

            for u in user_items:
                uid = u["user_id"]
                l_uid = u["line_user_id"]

                if bot_db.should_send_alert(uid, t, "BPA_BUY_SETUP", cooldown_days=5) or force_test:
                    if line_bot_api:
                        try:
                            msg = FlexSendMessage(
                                alt_text=f"🎯【買點通知】{sname} ({t}) 觸發 {sig_name}",
                                contents=alert_flex
                            )
                            line_bot_api.push_message(l_uid, msg)
                            logger.info(f"已發送買點推播至 LINE 用戶 {l_uid} 標的 {t}")
                        except Exception as e:
                            logger.error(f"發送買點 LINE Push 失敗: {e}")
                    else:
                        logger.info(f"[模擬推播] 發送買點通知卡至用戶 {l_uid} 標的 {t}")

                    bot_db.record_alert_log(uid, t, "BPA_BUY_SETUP", close_now)
                    alerts_triggered += 1

    return alerts_triggered

def start_worker_loop(interval_sec=60, force_test=False):
    """巡邏循環主函數：整合持股停損巡邏與觀察名單買點巡邏"""
    logger.info(f"盤中風控巡邏 Worker 啟動！巡邏間隔: {interval_sec} 秒 (測試模式: {force_test})")
    last_watchlist_patrol_ts = 0
    WATCHLIST_INTERVAL_SEC = 900  # 觀察名單每 15 分鐘（900秒）掃描一次

    while True:
        try:
            if is_market_open(force_test=force_test):
                logger.info("執行盤中風控巡邏比對...")
                triggered_stop = run_patrol_cycle(force_test=force_test)
                if triggered_stop > 0:
                    logger.info(f"本次巡邏發出 {triggered_stop} 則停損告警。")

                # 檢查是否達到觀察名單掃描週期
                now_ts = time.time()
                if (now_ts - last_watchlist_patrol_ts >= WATCHLIST_INTERVAL_SEC) or force_test:
                    logger.info("執行觀察名單 BPA 回測買點巡邏比對...")
                    triggered_buy = run_watchlist_patrol_cycle(force_test=force_test)
                    if triggered_buy > 0:
                        logger.info(f"本次觀察名單巡邏發出 {triggered_buy} 則買點通知。")
                    last_watchlist_patrol_ts = now_ts
            else:
                logger.debug("目前非盤中交易時段，休眠中...")
        except Exception as e:
            logger.error(f"巡邏 Worker 異常: {e}", exc_info=True)

        time.sleep(interval_sec)

if __name__ == "__main__":
    # 若直接執行預設為強制測試 1 次
    run_patrol_cycle(force_test=True)
    run_watchlist_patrol_cycle(force_test=True)

