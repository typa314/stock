# -*- coding: utf-8 -*-
"""
line_server.py - LINE Bot Webhook 服務
整合 FastAPI、bot_db 持倉管理、bot_flex 視覺化卡片與 kline.py 即時撮合
"""

import os
import re
import sys
import logging

# 確保當前目錄在模組搜尋路徑第一位
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(current_dir, ".env"))

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from concurrent.futures import ThreadPoolExecutor
import threading
import requests

import bot_db
import bot_flex
from kline import get_info, fetch_realtime_bar, analyze_stock, analyze_stock_5m, compute_risk_stop

# 設定記錄檔
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("line_bot")

# 初始化資料庫
bot_db.init_db()

# ── 雙節點資料庫自動同步 (Local <-> Render Cloud) ──
RENDER_BACKEND_URL = os.environ.get("RENDER_BACKEND_URL", "https://tw-stock-bpa-bot.onrender.com").strip().rstrip("/")

# 本節點是否為雲端節點（Render 會自帶 RENDER 環境變數）。雲端節點不需要再對自己拉／推快照。
IS_CLOUD_NODE = bool(os.environ.get("RENDER")) or os.environ.get("DISABLE_CLOUD_SYNC", "").strip() == "1"


def _cloud_sync_enabled():
    if IS_CLOUD_NODE:
        return False
    if not RENDER_BACKEND_URL or "127.0.0.1" in RENDER_BACKEND_URL or "localhost" in RENDER_BACKEND_URL:
        return False
    return True


def push_snapshot_to_cloud():
    """（同步）將本地資料庫快照推送到 Render 雲端備援"""
    if not _cloud_sync_enabled():
        return False
    try:
        snapshot = bot_db.export_db_snapshot()
        res = requests.post(f"{RENDER_BACKEND_URL}/api/sync_db", json=snapshot, timeout=(5, 15))
        if res.status_code == 200:
            logger.info("✅ 已成功將本地持倉與自選資料庫同步至 Render 雲端！")
            return True
        logger.warning(f"推送快照至雲端被拒：HTTP {res.status_code}")
    except Exception as e:
        logger.debug(f"雲端資料庫同步略過: {e}")
    return False


def sync_to_cloud_async():
    """在背景非同步將本地資料庫快照推送到 Render 雲端備援"""
    if not _cloud_sync_enabled():
        return
    threading.Thread(target=push_snapshot_to_cloud, daemon=True).start()


def pull_snapshot_from_cloud():
    """
    （同步）自 Render 雲端節點拉回快照並合併進本地資料庫。

    本機非常駐時，離線期間的訊息由 Worker 改派 Render 處理，那段時間新增的持倉／自選
    只存在雲端。本機同步原本是單向（只推不拉），開機後本機視野會缺這些資料，
    導致「持倉」查詢漏列、盤中停損巡邏也不會監控它們。
    合併規則由 bot_db.import_db_snapshot 決定（以 line_user_id 對映用戶、updated_at 較新者為準）。
    """
    if not _cloud_sync_enabled():
        return False
    try:
        # Render 免費方案可能處於休眠，讀取逾時放寬到 40 秒容許冷啟動
        res = requests.get(f"{RENDER_BACKEND_URL}/api/sync_db", timeout=(5, 40))
        if res.status_code != 200:
            logger.warning(f"自雲端拉回快照失敗：HTTP {res.status_code}（沒沿用本地資料庫）")
            return False
        snapshot = res.json()
        if not isinstance(snapshot, dict) or not any(snapshot.get(k) for k in ("users", "positions", "watchlist")):
            logger.info("雲端節點回傳空快照，無需合併")
            return False
        stats = bot_db.import_db_snapshot(snapshot)
        if not stats:
            logger.warning("雲端快照合併失敗（格式不符）")
            return False
        logger.info(
            "✅ 已自 Render 雲端拉回快照並合併（接受筆數，含內容相同的重寫）："
            f"users={stats.get('users', 0)} positions={stats.get('positions', 0)} "
            f"watchlist={stats.get('watchlist', 0)} skipped={stats.get('skipped', 0)}"
        )
        return True
    except Exception as e:
        logger.warning(f"自雲端拉回快照失敗（沒沿用本地資料庫）: {e}")
        return False


def bootstrap_db_sync():
    """
    開機一次性雙向對帳：先「拉回」雲端資料再「推送」本地快照。
    順序固定——先拉後推，本機的舊資料才不會在雲端較新資料還沒合併進來前就被推上去。
    整段在背景執行緒進行，避免 Render 冷啟動拖慢 uvicorn 啟動。
    """
    if not _cloud_sync_enabled():
        return

    def _run():
        pull_snapshot_from_cloud()
        push_snapshot_to_cloud()

    threading.Thread(target=_run, daemon=True, name="db-bootstrap-sync").start()


# 啟動時背景觸發一次雙向對帳（先拉回雲端資料，再推送本地快照）
bootstrap_db_sync()


# ── 記憶體快取機制（加速個股查詢與避免重複請求超時） ──
import time
_STOCK_CACHE = {}  # ticker -> (timestamp, analysis_dict)
CACHE_TTL_SEC = 60  # 快取有效時間 60 秒

def get_cached_stock_analysis(ticker: str, months: int = 12, quick_mode: bool = False):
    """
    獲取個股多維度量化數據，支援 60s 記憶體快取
    """
    now = time.time()
    cache_key = f"{ticker}_{months}_{quick_mode}"
    full_key = f"{ticker}_{months}_False"
    if full_key in _STOCK_CACHE:
        cached_ts, cached_res = _STOCK_CACHE[full_key]
        if now - cached_ts < CACHE_TTL_SEC:
            logger.info(f"快取命中！【{ticker}】(完整快取) 自記憶體即刻回傳（耗時 < 1ms）")
            return cached_res
    if cache_key in _STOCK_CACHE:
        cached_ts, cached_res = _STOCK_CACHE[cache_key]
        if now - cached_ts < CACHE_TTL_SEC:
            logger.info(f"快取命中！【{ticker}】(quick_mode={quick_mode}) 自記憶體即刻回傳（耗時 < 1ms）")
            return cached_res

    res = analyze_stock(ticker, months=months, generate_html=False, print_report=False, quick_mode=quick_mode)
    _STOCK_CACHE[cache_key] = (now, res)
    return res


_STOCK_5M_CACHE = {}  # ticker -> (timestamp, analysis_dict)
CACHE_5M_TTL_SEC = 30  # 5分K 快取有效時間 30 秒

def get_cached_5m_analysis(ticker: str, days: int = 3):
    """
    獲取個股 5 分鐘 K 線當沖多維量化數據，支援 30s 記憶體快取
    """
    now = time.time()
    ticker_key = str(ticker).upper()
    if ticker_key in _STOCK_5M_CACHE:
        cached_ts, cached_res = _STOCK_5M_CACHE[ticker_key]
        if now - cached_ts < CACHE_5M_TTL_SEC:
            logger.info(f"5分K快取命中！【{ticker_key}】自記憶體即刻回傳（耗時 < 1ms）")
            return cached_res

    res = analyze_stock_5m(ticker=ticker_key, days=days)
    _STOCK_5M_CACHE[ticker_key] = (now, res)
    return res


# LINE 設定憑證（優先從環境變數讀取，若未設定則為預設占位字串）
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "YOUR_CHANNEL_SECRET").strip().strip('"').strip("'")
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "YOUR_CHANNEL_ACCESS_TOKEN").strip().strip('"').strip("'")

# LINE SDK 初始化（相容 v3）
line_bot_api = None
handler = None
try:
    from linebot import LineBotApi, WebhookHandler
    from linebot.exceptions import InvalidSignatureError
    from linebot.models import (
        MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, JoinEvent
    )
    if CHANNEL_SECRET != "YOUR_CHANNEL_SECRET" and CHANNEL_ACCESS_TOKEN != "YOUR_CHANNEL_ACCESS_TOKEN":
        line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
        handler = WebhookHandler(CHANNEL_SECRET)
        logger.info("LINE Bot SDK 已成功載入憑證並啟用！")
    else:
        logger.warning("LINE_CHANNEL_SECRET 或 LINE_CHANNEL_ACCESS_TOKEN 尚未設定，以測試模擬模式啟動。")
except Exception as e:
    logger.warning(f"LINE SDK 初始化警告: {e}")

app = FastAPI(title="Stock Quantitative LINE Bot Server", version="3.0.0")

@app.on_event("startup")
def startup_event():
    import threading
    try:
        from monitor_worker import start_worker_loop
        worker_thread = threading.Thread(
            target=start_worker_loop,
            kwargs={"interval_sec": 60, "force_test": False},
            daemon=True
        )
        worker_thread.start()
        logger.info("盤中風控巡邏背景執行緒已成功伴隨 FastAPI 啟動！")
    except Exception as e:
        logger.error(f"啟動背景巡邏失敗: {e}")

@app.get("/")
@app.get("/health")
def health_check():
    return {
        "status": "online",
        "service": "Stock Quantitative LINE Bot",
        "line_sdk_configured": line_bot_api is not None
    }

@app.get("/api/sync_db")
def get_db_snapshot():
    """供雙節點查詢資料庫快照"""
    return bot_db.export_db_snapshot()

@app.post("/api/sync_db")
async def post_db_snapshot(req: Request):
    """供雙節點寫入資料庫快照"""
    try:
        data = await req.json()
        stats = bot_db.import_db_snapshot(data)
        if not stats:
            return JSONResponse({"status": "error", "detail": "invalid snapshot"}, status_code=400)
        return {"status": "ok", "merged": stats}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=400)


def handle_user_command(user_id: str, text: str, user_name: str = "投資人", is_group: bool = False):
    """
    核心指令處理器：
    - 買 [代號] [成本] [股數]
    - 賣 [代號]
    - 持倉 / 庫存 / 損益
    - [純代號] 查 4合1 多維量化研判
    - 說明 / help
    """
    raw_text = text.strip()
    cmd = raw_text.replace("，", " ").replace(",", " ").replace("＋", "+").replace("－", "-")
    tokens = cmd.split()

    if not tokens:
        return "請輸入指令，例如「買 2330 980」或「持倉」查看投資組合。"

    action = tokens[0].lower()

    # 1. 買進 / 建倉
    if action in ["買", "買進", "進場", "add", "buy"]:
        if len(tokens) < 3:
            return "⚠️ 格式錯誤！請輸入：\n買 [股票代號] [成本價] [股數(選填)]\n範例：買 2330 980 或 買 00708L 81.2 1000"
        raw_t = tokens[1].strip()
        cleaned_t = re.sub(r"\.(tw|two)$", "", raw_t, flags=re.IGNORECASE).upper()
        ticker_match = re.search(r"\d{4,6}[a-zA-Z]?", cleaned_t, re.IGNORECASE)
        ticker = ticker_match.group().upper() if ticker_match else cleaned_t
        try:
            cost_p = float(tokens[2])
            shares = int(tokens[3]) if len(tokens) >= 4 else 1000
        except ValueError:
            return "⚠️ 成本或股數必須為數字！範例：買 2330 980 1000"

        market, sname = get_info(ticker)
        bot_db.add_or_update_position(user_id, ticker, cost_p, shares, sname)
        sync_to_cloud_async()
        stop_7, stop_pct, stop_basis = compute_risk_stop(ticker, cost_p, market=market)
        stop_10 = round(cost_p * (1 - stop_pct - 0.03), 2)

        reply_msg = (
            f"✅ 已成功記錄持股【{sname} ({ticker})】！\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• 買進成本：{cost_p:.2f} 元\n"
            f"• 持有股數：{shares:,} 股\n"
            f"• 浮虧警戒 (-{stop_pct*100:.1f}%)：{stop_7:.2f} 元\n"
            f"• 寬幅防守停損 (-{(stop_pct+0.03)*100:.1f}%)：{stop_10:.2f} 元\n"
            f"• 警戒依據：{stop_basis}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ 系統將於平日盤中自動巡邏風控！\n"
            f"隨時輸入「持倉」即可查看即時損益。"
        )
        return reply_msg

    # 2. 賣出 / 平倉
    elif action in ["賣", "賣出", "平倉", "del", "sell"]:
        if len(tokens) < 2:
            return "⚠️ 格式錯誤！請輸入：\n賣 [股票代號]\n範例：賣 2330 或 賣 00708L"
        raw_t = tokens[1].strip()
        cleaned_t = re.sub(r"\.(tw|two)$", "", raw_t, flags=re.IGNORECASE).upper()
        ticker_match = re.search(r"\d{4,6}[a-zA-Z]?", cleaned_t, re.IGNORECASE)
        ticker = ticker_match.group().upper() if ticker_match else cleaned_t
        ok = bot_db.close_position(user_id, ticker)
        if ok:
            sync_to_cloud_async()
            return f"✅ 已成功將【{ticker}】結案平倉，並已移出盤中風控巡邏監控！"
        else:
            return f"⚠️ 找不到【{ticker}】的進行中持倉記錄。"

    # 3. 查詢持倉與即時損益總覽
    elif action in ["持倉", "庫存", "損益", "portfolio", "pos", "p"]:
        positions = bot_db.get_user_positions(user_id)
        if not positions:
            return "💼 您目前尚無任何持倉記錄。\n請輸入「買 2330 980」建立首檔持股！"

        items = []
        total_cost = 0.0
        total_val = 0.0

        for p in positions:
            t = p["ticker"]
            market, sname = get_info(t)
            cost_p = float(p["cost_price"])
            shares = int(p["shares"])

            # 抓取即時行情撮合
            rt = fetch_realtime_bar(t, market)
            if rt and rt.get("close") and rt["close"] > 0:
                cur_p = float(rt["close"])
            else:
                # 備援：若非盤中抓取近期日K最新收盤
                try:
                    res_alt = get_cached_stock_analysis(t, months=12)
                    cur_p = float(res_alt["close_now"]) if res_alt and "close_now" in res_alt else cost_p
                except Exception:
                    cur_p = cost_p

            diff = cur_p - cost_p
            pnl_pct = (diff / cost_p) * 100 if cost_p > 0 else 0.0
            pnl_amt = diff * shares
            stop_7, stop_pct, stop_basis = compute_risk_stop(
                t, cost_p, market=market, user_pct=p.get("stop_loss_pct")
            )
            stop_10 = round(cost_p * (1 - stop_pct - 0.03), 2)
            buf_7 = cur_p - stop_7

            total_cost += cost_p * shares
            total_val += cur_p * shares

            if cur_p <= stop_10:
                tag = "🚨 防守停損"
                tag_color = "#ef4444"
            elif cur_p <= stop_7:
                tag = "⚠️ 浮虧警戒"
                tag_color = "#f59e0b"
            elif diff < 0:
                tag = "🟡 浮虧防守"
                tag_color = "#fbbf24"
            else:
                tag = "🟢 獲利持有"
                tag_color = "#22c55e"

            items.append({
                "ticker": t,
                "stock_name": sname or p.get("stock_name", t),
                "shares": shares,
                "cost_price": cost_p,
                "current_price": cur_p,
                "pnl": diff,
                "pnl_pct": pnl_pct,
                "pnl_amount": pnl_amt,
                "stop_7": stop_7,
                "stop_pct": stop_pct,
                "buf_7": buf_7,
                "tag": tag,
                "tag_color": tag_color
            })

        total_pnl = total_val - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

        # 回傳 Flex Message 結構
        flex_dict = bot_flex.build_portfolio_flex(user_name, items, total_pnl, total_pnl_pct)
        return flex_dict

    # 3.1 加入自選觀察清單 (追蹤回測底部買點，支援 +2330, + 2330, 關注 2330 等)
    elif cmd.startswith("+") or action in ["關注", "追蹤", "自選+", "+", "watch", "w"]:
        if cmd.startswith("+"):
            raw_t = cmd.lstrip("+").strip()
        else:
            raw_t = tokens[1].strip() if len(tokens) >= 2 else ""

        if not raw_t:
            return "⚠️ 格式錯誤！請輸入：\n+2330 或 關注 2330\n範例：+2330 或 +00708L"

        cleaned_t = re.sub(r"\.(tw|two)$", "", raw_t, flags=re.IGNORECASE).upper()
        ticker_match = re.search(r"\d{4,6}[a-zA-Z]?", cleaned_t, re.IGNORECASE)
        ticker = ticker_match.group().upper() if ticker_match else cleaned_t

        market, sname = get_info(ticker)
        ok, msg = bot_db.add_to_watchlist(user_id, ticker, stock_name=sname)
        if not ok:
            return msg

        sync_to_cloud_async()

        # 取得最新現價做為即時回饋
        rt = fetch_realtime_bar(ticker, market)
        cur_p_str = f"{rt['close']:.2f} 元" if (rt and rt.get("close")) else "連線撮合中"

        reply = (
            f"⭐ 已成功將【{sname} ({ticker})】加入自選觀察名單！\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• 目前現價：{cur_p_str}\n"
            f"• 監控模式：多維量化回測底部確認雷達\n"
            f"• 觸發條件：High 2 雙重底 / 20 EMA 支撐回踩 / S1 反轉\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ 盤中一旦確認高勝率買點，系統將主動推播通知！\n"
            f"隨時輸入「自選」或「清單」即可查看追蹤列表。\n"
            f"💡 快捷指令：輸入 -{ticker} 即可隨時取消關注。"
        )
        return reply

    # 3.2 取消關注 / 移出觀察名單 (支援 -2330, - 2330, 取消關注 2330 等)
    elif cmd.startswith("-") or action in ["取消關注", "取消追蹤", "退訂", "自選-", "-", "unwatch", "uw"]:
        if cmd.startswith("-"):
            raw_t = cmd.lstrip("-").strip()
        else:
            raw_t = tokens[1].strip() if len(tokens) >= 2 else ""

        if not raw_t:
            return "⚠️ 格式錯誤！請輸入：\n-2330 或 取消關注 2330\n範例：-2330 或 -00708L"

        cleaned_t = re.sub(r"\.(tw|two)$", "", raw_t, flags=re.IGNORECASE).upper()
        ticker_match = re.search(r"\d{4,6}[a-zA-Z]?", cleaned_t, re.IGNORECASE)
        ticker = ticker_match.group().upper() if ticker_match else cleaned_t

        ok = bot_db.remove_from_watchlist(user_id, ticker)
        if ok:
            sync_to_cloud_async()
            return f"✅ 已成功將【{ticker}】移出觀察清單，停止盤中買點推播！"
        else:
            return f"⚠️ 您的觀察名單中目前沒有【{ticker}】。"

    # 3.3 查詢自選觀察清單
    elif action in ["自選", "自選股", "觀察名單", "清單", "watchlist", "wl"]:
        watch_items = bot_db.get_user_watchlist(user_id)
        if not watch_items:
            return (
                "📋 您的自選觀察名單目前是空的。\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "💡 加入方式：輸入「關注 2330」或「追蹤 00708L」\n"
                "盤中一旦偵測到 20 EMA 支撐回測或 High 2 底部確認，系統將主動震動通知您！"
            )

        def process_one_watch_item(w):
            t = w["ticker"]
            market, sname = get_info(t)
            sname = sname or w.get("stock_name", t)

            # 抓取即時行情撮合
            rt = fetch_realtime_bar(t, market)
            if rt and rt.get("close") and rt["close"] > 0:
                cur_p = float(rt["close"])
                chg_val = cur_p - float(rt["open"]) if rt.get("open") else 0.0
                chg_pct = (chg_val / float(rt["open"])) * 100 if rt.get("open") else 0.0
            else:
                try:
                    res_alt = get_cached_stock_analysis(t, months=12, quick_mode=True)
                    cur_p = float(res_alt["close_now"]) if res_alt and "close_now" in res_alt else 0.0
                    df_alt = res_alt.get("df")
                    prev_c = float(df_alt["close"].iloc[-2]) if (df_alt is not None and len(df_alt) >= 2) else cur_p
                    chg_val = cur_p - prev_c
                    chg_pct = (chg_val / prev_c) * 100 if prev_c > 0 else 0.0
                except Exception:
                    cur_p = 0.0
                    chg_val = 0.0
                    chg_pct = 0.0

            # 取得市場狀態與 20 EMA 距離
            try:
                res_alt = get_cached_stock_analysis(t, months=12, quick_mode=True)
                bpa_res = res_alt.get("bpa_res", {})
                bpa_zh = bpa_res.get("always_in_zh", "箱型震盪")
                bpa_color = "#4ade80" if "多" in bpa_zh else ("#f87171" if "空" in bpa_zh else "#fbbf24")
                df_alt = res_alt.get("df")
                ema_v = float(df_alt["ema20"].iloc[-1]) if (df_alt is not None and "ema20" in df_alt.columns) else cur_p
                dist_pct = ((cur_p - ema_v) / ema_v * 100) if ema_v > 0 else 0.0
                if abs(dist_pct) <= 1.0:
                    dist_desc = "回踩月線有守"
                elif dist_pct > 0:
                    dist_desc = f"距月線 +{dist_pct:.1f}%"
                else:
                    dist_desc = f"距月線 {dist_pct:.1f}%"
            except Exception:
                bpa_zh = "常態整理"
                bpa_color = "#94a3b8"
                dist_desc = "觀察中"

            return {
                "ticker": t,
                "stock_name": sname,
                "current_price": cur_p,
                "chg_val": chg_val,
                "chg_pct": chg_pct,
                "bpa_zh": bpa_zh,
                "bpa_color": bpa_color,
                "dist_desc": dist_desc
            }

        with ThreadPoolExecutor(max_workers=min(len(watch_items), 8)) as executor:
            items = list(executor.map(process_one_watch_item, watch_items))

        flex_dict = bot_flex.build_watchlist_flex(user_name, items)
        return flex_dict

    # 3.9 查詢 5 分鐘 K 線當沖研判 (支援 k2330, K2330, k 2330, 5k 2330, 5m 2330, 5分 2330, 當沖 2330 等)
    m_5m = re.match(r"^(k|5k|5m|5分|當沖)\s*(\d{4,6}[a-zA-Z]?)(\.(tw|two))?$", raw_text, re.IGNORECASE)
    if m_5m or (action in ["k", "5k", "5m", "5分", "當沖"] and len(tokens) >= 2):
        if m_5m and m_5m.group(2):
            ticker_raw = m_5m.group(2)
        elif len(tokens) >= 2:
            ticker_raw = tokens[1].strip()
        else:
            ticker_raw = ""

        cleaned_t = re.sub(r"\.(tw|two)$", "", ticker_raw, flags=re.IGNORECASE).upper()
        ticker_match = re.search(r"\d{4,6}[a-zA-Z]?", cleaned_t, re.IGNORECASE)
        if not ticker_match:
            return "⚠️ 請提供欲查詢 5 分 K 的股票代號，例如「k2330」或「k 00708L」"
        ticker = ticker_match.group().upper()

        try:
            res5 = get_cached_5m_analysis(ticker, days=3)
            flex_dict = bot_flex.build_5m_stock_flex(res5)
            return flex_dict
        except Exception as e:
            logger.error(f"查詢 5分K【{ticker}】失敗: {e}", exc_info=True)
            return f"⚠️ 查詢股票【{ticker}】5 分鐘 K 線失敗：{e}"

    # 4. 單檔股票代號查詢 (支援純代號 2330, 00708L, 查 2330, 診斷 00708L, 2330.TW 等)
    elif (
        re.match(r"^\d{4,6}[a-zA-Z]?(\.(tw|two))?$", action, re.IGNORECASE)
        or (action in ["查", "查詢", "診斷", "分析", "看", "bpa", "stock", "個股"] and len(tokens) >= 2)
        or (len(tokens) == 1 and re.search(r"\d{4,6}[a-zA-Z]?", action, re.IGNORECASE))
        or re.search(r"\d{4,6}[a-zA-Z]?", cmd, re.IGNORECASE)
    ):
        cleaned_cmd = re.sub(r"\.(tw|two)\b", "", cmd, flags=re.IGNORECASE)
        ticker_match = re.search(r"\d{4,6}[a-zA-Z]?", cleaned_cmd, re.IGNORECASE)
        if not ticker_match:
            return "⚠️ 請提供欲查詢的股票代號，例如「2330」或「00708L」"
        ticker = ticker_match.group().upper()

        try:
            import math
            res = get_cached_stock_analysis(ticker, months=12)
            sname = res.get("stock_name", ticker)
            df = res["df"]
            bpa_res = res.get("bpa_res", {})
            sr = res.get("sr_levels", {})
            close_now = float(res.get("close_now", 0.0))
            prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else close_now
            chg_val = close_now - prev_close
            chg_pct = (chg_val / prev_close) * 100 if prev_close > 0 else 0.0

            # 1. 建立日K 4合1 旗艦研判 Bubble
            bubble_daily = bot_flex.build_dashboard_stock_flex(
                stock_name=sname,
                ticker=ticker,
                market=res.get("market", "tse"),
                close_now=close_now,
                chg_val=chg_val,
                chg_pct=chg_pct,
                realtime_info=res.get("realtime_info"),
                df=df,
                bpa_res=bpa_res,
                trend_score=res.get("trend_score", 0),
                trend_stage=res.get("trend_stage", ""),
                rating_badge=res.get("rating_badge", ""),
                comp=res.get("composite_rating"),
                sr=sr
            )

            # 2. 整合 5 分鐘 K 線當沖研判為雙時框 Carousel 輪播 (左右滑動切換)
            try:
                res5 = get_cached_5m_analysis(ticker, days=3)
                bubble_5m = bot_flex.build_5m_stock_flex(res5)
                flex_dict = bot_flex.build_stock_carousel_flex(bubble_daily, bubble_5m)
            except Exception as e5:
                logger.warning(f"取得【{ticker}】5分K當沖資料失敗，降級回傳日K單卡: {e5}")
                flex_dict = bubble_daily

            return flex_dict
        except Exception as e:
            logger.error(f"查詢股票【{ticker}】失敗: {e}", exc_info=True)
            return f"⚠️ 查詢股票【{ticker}】失敗：{e}"

    # 5. 說明 / Help
    elif action in ["說明", "help", "?", "選單", "menu"]:
        return (
            "🤖 【量化操盤秘書指令指南】\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📌 記錄買進：\n"
            "   買 2330 980 (預設1張)\n"
            "   買 2330 980 2000 (買2張)\n\n"
            "📌 標記平倉：\n"
            "   賣 2330\n\n"
            "📌 查詢持倉與損益：\n"
            "   輸入「持倉」或「庫存」\n\n"
            "📌 自選觀察與買點雷達：\n"
            "   +2330 (快速加入追蹤)\n"
            "   -2330 (快速取消關注)\n"
            "📌 個股雙時框 (日K+5分K) 輪播：\n"
            "   直接輸入代號，如「2330」或「00708L」（左右滑動切換波段與當沖）\n\n"
            "📌 單獨查 5分K 當沖：\n"
            "   k2330 或 5k 2330 (查5分鐘K線與當沖掛單)\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🛡️ 盤中跌破 -7% 停損或觸發高勝率買點時主動通知！"
        )

    else:
        if is_group:
            return None  # 群組中非相關指令保持沉默，避免干擾常態聊天
        return f"未能辨識指令「{raw_text}」。\n請輸入「說明」查看指令範例，或直接輸入股票代號（如 2330）查詢行情。"

# ── Webhook 背景處理執行緒池 ──
# LINE reply token 為單次使用且效期極短；上游 Cloudflare Worker 又採瀑布式容錯，
# 本機若未在 LOCAL_TIMEOUT_MS 內回應就會被改派 Render 雲端節點，token 遭雲端先用掉，
# 本機事後回覆必然收到 400 Invalid reply token。
# 因此 /callback 必須「先秒回 200，再於背景執行緒完成運算與回覆」。
_WEBHOOK_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="line-webhook")


def _process_webhook_async(body_text: str, signature: str):
    """在背景執行緒完成事件解析、量化運算與 LINE 回覆"""
    try:
        handler.handle(body_text, signature)
    except InvalidSignatureError:
        logger.error("Webhook 簽章驗證失敗（背景處理階段）")
    except Exception as e:
        logger.error(f"處理 Webhook 錯誤: {e}", exc_info=True)


# safe_reply 回傳狀態
REPLY_OK = "ok"                    # 回覆或 push 補送成功
REPLY_TOKEN_DEAD = "token_dead"    # reply token 已失效（他節點用掉或逾期）且 push 補送亦失敗
REPLY_FAILED = "failed"            # 其他原因失敗（如 Flex JSON 被 LINE 退回），token 仍可用，可改純文字重試


def safe_reply(reply_token, messages, user_id=None, label=""):
    """
    以 reply_message 回覆；若 token 已被其他節點使用或逾期（400 Invalid reply token），
    自動改用 push_message 補送，確保使用者不會收不到結果。
    """
    try:
        line_bot_api.reply_message(reply_token, messages)
        return REPLY_OK
    except Exception as e:
        msg = str(e)
        logger.warning(f"reply_message 失敗（{label}）: {msg}")
        token_dead = "Invalid reply token" in msg
        if token_dead and user_id:
            try:
                line_bot_api.push_message(user_id, messages)
                logger.info(f"reply token 已失效，改用 push_message 成功補送給 {user_id}")
                return REPLY_OK
            except Exception as pe:
                logger.error(f"push_message 補送亦失敗: {pe}")
        return REPLY_TOKEN_DEAD if token_dead else REPLY_FAILED


@app.post("/callback")
async def line_callback(request: Request):
    """LINE Webhook 接收點（秒回 200，運算交由背景執行緒）"""
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    body_text = body.decode("utf-8")

    if not handler or not line_bot_api:
        logger.info(f"收到 Webhook 請求 (未設定 LINE 憑證): {body_text[:100]}")
        return JSONResponse(status_code=200, content={"message": "Server running in standby mode. Please configure LINE credentials."})

    # 先做純 HMAC 簽章驗證（微秒級），僅簽章錯誤才回 400
    try:
        from linebot import SignatureValidator
        if not SignatureValidator(CHANNEL_SECRET).validate(body_text, signature):
            raise HTTPException(status_code=400, detail="Invalid signature")
    except HTTPException:
        raise
    except Exception as e:
        logger.debug(f"獨立簽章驗證略過，改由背景 handler 驗證: {e}")

    # 立即交付背景執行緒，主線程於數毫秒內回 200，避免 Worker 逾時改派雲端節點
    _WEBHOOK_POOL.submit(_process_webhook_async, body_text, signature)
    return "OK"

# 註冊 LINE 訊息事件監聽器
if handler:
    @handler.add(MessageEvent, message=TextMessage)
    def handle_line_text_message(event):
        is_group = event.source.type in ["group", "room"]
        user_id = getattr(event.source, "user_id", None)
        if not user_id:
            user_id = getattr(event.source, "group_id", None) or getattr(event.source, "room_id", "group_chat")

        text = event.message.text
        reply_token = event.reply_token

        # 取得使用者顯示暱稱
        display_name = "投資人"
        if line_bot_api:
            if event.source.type == "user" and user_id:
                try:
                    profile = line_bot_api.get_profile(user_id)
                    display_name = profile.display_name
                except Exception:
                    pass
            elif event.source.type == "group" and getattr(event.source, "user_id", None):
                try:
                    profile = line_bot_api.get_group_member_profile(event.source.group_id, event.source.user_id)
                    display_name = profile.display_name
                except Exception:
                    pass

        result = handle_user_command(user_id, text, display_name, is_group=is_group)
        if result is None:
            return

        if isinstance(result, dict):
            # Flex Message 卡片回傳
            header_text = "📊 個股多維量化診斷"
            alt_txt = "📊 個股多維量化診斷"
            flex_msg = None
            try:
                if result.get("type") == "carousel":
                    alt_txt = f"📊 【{text.strip().upper()}】雙時框量化診斷 (日K + 5分K)"
                else:
                    header_text = result.get("header", {}).get("contents", [{}])[0].get("text", header_text)
                    alt_txt = f"📊 {header_text}" if header_text else "📊 個股多維量化診斷"
                flex_msg = FlexSendMessage(alt_text=alt_txt, contents=result)
            except Exception as fe:
                logger.error(f"組建 Flex Message 失敗，啟動純文字備援: {fe}", exc_info=True)

            status = safe_reply(reply_token, flex_msg, user_id=user_id, label="Flex 卡片") if flex_msg is not None else REPLY_FAILED
            if status == REPLY_FAILED:
                # 卡片組建失敗或被 LINE 退回（此時 token 仍可用），自動降級以純文字回覆
                fallback_txt = f"📊 【量化診斷回報】\n{alt_txt}\n現價與指標已計算完成。"
                safe_reply(reply_token, TextSendMessage(text=fallback_txt), user_id=user_id, label="純文字備援")
            elif status == REPLY_TOKEN_DEAD:
                logger.error("reply token 已失效且 push 補送失敗，放棄本次回覆（請確認上游是否已重複派送給雲端節點）")
        else:
            # 純文字訊息回傳
            txt_msg = TextSendMessage(text=result)
            safe_reply(reply_token, txt_msg, user_id=user_id, label="純文字回覆")

    @handler.add(JoinEvent)
    def handle_line_join_event(event):
        """當機器人被邀請加入群組時發送歡迎引導訊息"""
        welcome_text = (
            "👋 大家好！我是【台股量化操盤秘書】。\n"
            "感謝邀請！已成功加入群組！\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📌 群組快速看盤：\n"
            "• 直接輸入股票代號（如 2330、3042）即可查即時行情與 4合1 多維量化研判\n"
            "• 輸入「說明」可查看完整功能指引\n"
            "• 群內日常閒聊我將保持安靜，不打擾大家！"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=welcome_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    reload_flag = os.environ.get("RELOAD", "false").lower() == "true"
    uvicorn.run("line_server:app", host="0.0.0.0", port=port, reload=reload_flag)
