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

import bot_db
import bot_flex
from kline import get_info, fetch_realtime_bar, analyze_stock

# 設定記錄檔
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("line_bot")

# 初始化資料庫
bot_db.init_db()

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

app = FastAPI(title="BPA Stock LINE Bot Webhook Server", version="1.0.0")

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
        "service": "BPA Stock LINE Bot",
        "line_sdk_configured": line_bot_api is not None
    }

def handle_user_command(user_id: str, text: str, user_name: str = "投資人", is_group: bool = False):
    """
    核心指令處理器：
    - 買 [代號] [成本] [股數]
    - 賣 [代號]
    - 持倉 / 庫存 / 損益
    - [純代號] 查 BPA
    - 說明 / help
    """
    raw_text = text.strip()
    cmd = raw_text.replace("，", " ").replace(",", " ")
    tokens = cmd.split()

    if not tokens:
        return "請輸入指令，例如「買 2330 980」或「持倉」查看投資組合。"

    action = tokens[0].lower()

    # 1. 買進 / 建倉
    if action in ["買", "買進", "進場", "add", "buy"]:
        if len(tokens) < 3:
            return "⚠️ 格式錯誤！請輸入：\n買 [股票代號] [成本價] [股數(選填)]\n範例：買 2330 980 或 買 2330 980 1000"
        ticker = tokens[1].strip()
        try:
            cost_p = float(tokens[2])
            shares = int(tokens[3]) if len(tokens) >= 4 else 1000
        except ValueError:
            return "⚠️ 成本或股數必須為數字！範例：買 2330 980 1000"

        market, sname = get_info(ticker)
        bot_db.add_or_update_position(user_id, ticker, cost_p, shares, sname)
        stop_7 = round(cost_p * 0.93, 2)
        stop_8 = round(cost_p * 0.92, 2)

        reply_msg = (
            f"✅ 已成功記錄持股【{sname} ({ticker})】！\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• 買進成本：{cost_p:.2f} 元\n"
            f"• 持有股數：{shares:,} 股\n"
            f"• 強制停損 (-7%)：{stop_7:.2f} 元\n"
            f"• 極限斷頭 (-8%)：{stop_8:.2f} 元\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ 系統將於平日盤中自動巡邏風控！\n"
            f"隨時輸入「持倉」即可查看即時損益。"
        )
        return reply_msg

    # 2. 賣出 / 平倉
    elif action in ["賣", "賣出", "平倉", "del", "sell"]:
        if len(tokens) < 2:
            return "⚠️ 格式錯誤！請輸入：\n賣 [股票代號]\n範例：賣 2330"
        ticker = tokens[1].strip()
        ok = bot_db.close_position(user_id, ticker)
        if ok:
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
                    df_alt, _, _, _ = analyze_stock(t, months=1, generate_html=False, print_report=False)
                    cur_p = float(df_alt["close"].iloc[-1]) if df_alt is not None and not df_alt.empty else cost_p
                except Exception:
                    cur_p = cost_p

            diff = cur_p - cost_p
            pnl_pct = (diff / cost_p) * 100 if cost_p > 0 else 0.0
            pnl_amt = diff * shares
            stop_7 = round(cost_p * 0.93, 2)
            stop_8 = round(cost_p * 0.92, 2)
            buf_7 = cur_p - stop_7

            total_cost += cost_p * shares
            total_val += cur_p * shares

            if cur_p <= stop_8:
                tag = "🚨 極限斷頭"
                tag_color = "#ef4444"
            elif cur_p <= stop_7:
                tag = "⚠️ 強制停損"
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
                "buf_7": buf_7,
                "tag": tag,
                "tag_color": tag_color
            })

        total_pnl = total_val - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

        # 回傳 Flex Message 結構
        flex_dict = bot_flex.build_portfolio_flex(user_name, items, total_pnl, total_pnl_pct)
        return flex_dict

    # 4. 單檔股票代號查詢 (4~6碼數字)
    elif re.match(r"^\d{4,6}$", action):
        ticker = action
        try:
            market, sname = get_info(ticker)
            df, bpa_res, sr, _ = analyze_stock(ticker, months=1, generate_html=False, print_report=False)
            close_now = float(df["close"].iloc[-1])
            prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else close_now
            chg_val = close_now - prev_close
            chg_pct = (chg_val / prev_close) * 100
            ema20_val = float(df["ema20"].iloc[-1]) if "ema20" in df.columns else close_now

            action_tag = "🟢 建議買入" if bpa_res.get("always_in_code") == "AIL" else ("🔴 建議逢高做空" if bpa_res.get("always_in_code") == "AIS" else "🟡 建議觀望")
            action_sub = f"順應 20 EMA（{ema20_val:.2f} 元）趨勢運行"

            flex_dict = bot_flex.build_single_stock_flex(
                sname, ticker, close_now, chg_val, chg_pct, ema20_val,
                action_tag, action_sub, sr["s1"], sr["r1"]
            )
            return flex_dict
        except Exception as e:
            return f"⚠️ 查詢股票【{ticker}】失敗：{e}"

    # 5. 說明 / Help
    elif action in ["說明", "help", "?", "選單", "menu"]:
        return (
            "🤖 【BPA 操盤秘書指令指南】\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📌 記錄買進：\n"
            "   買 2330 980 (預設1張)\n"
            "   買 2330 980 2000 (買2張)\n\n"
            "📌 標記平倉：\n"
            "   賣 2330\n\n"
            "📌 查詢持倉與損益：\n"
            "   輸入「持倉」或「庫存」\n\n"
            "📌 單股 BPA 研判：\n"
            "   直接輸入代號，如「2330」\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🛡️ 盤中跌破 -7% 強制停損時將主動震動通知！"
        )

    else:
        if is_group:
            return None  # 群組中非相關指令保持沉默，避免干擾常態聊天
        return f"未能辨識指令「{raw_text}」。\n請輸入「說明」查看指令範例，或直接輸入股票代號（如 2330）查詢行情。"

@app.post("/callback")
async def line_callback(request: Request):
    """LINE Webhook 接收點"""
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    body_text = body.decode("utf-8")

    if not handler or not line_bot_api:
        logger.info(f"收到 Webhook 請求 (未設定 LINE 憑證): {body_text[:100]}")
        return JSONResponse(status_code=200, content={"message": "Server running in standby mode. Please configure LINE credentials."})

    try:
        handler.handle(body_text, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"處理 Webhook 錯誤: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

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
            flex_msg = FlexSendMessage(alt_text="📊 BPA 個人持股風控總覽", contents=result)
            line_bot_api.reply_message(reply_token, flex_msg)
        else:
            # 純文字訊息回傳
            txt_msg = TextSendMessage(text=result)
            line_bot_api.reply_message(reply_token, txt_msg)

    @handler.add(JoinEvent)
    def handle_line_join_event(event):
        """當機器人被邀請加入群組時發送歡迎引導訊息"""
        welcome_text = (
            "👋 大家好！我是【台股 BPA 操盤秘書】。\n"
            "感謝邀請！已成功加入群組！\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📌 群組快速看盤：\n"
            "• 直接輸入股票代號（如 2330、3042）即可查即時行情與 BPA 價格行為分析\n"
            "• 輸入「說明」可查看完整功能指引\n"
            "• 群內日常閒聊我將保持安靜，不打擾大家！"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=welcome_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("line_server:app", host="0.0.0.0", port=port, reload=True)
