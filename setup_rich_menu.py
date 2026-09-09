# -*- coding: utf-8 -*-
"""
setup_rich_menu.py - 自動建立並綁定 LINE Bot 底部「服務選單列 (Rich Menu)」
使用 Pillow 生成高解析度 2500x1686 專業操盤深色風格選單圖，
並透過 LINE Messaging API 上傳並設為所有用戶預設選單。
"""

import os
import sys
import io
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

load_dotenv(os.path.join(current_dir, ".env"))

from PIL import Image, ImageDraw, ImageFont
from linebot import LineBotApi
from linebot.models import (
    RichMenu, RichMenuSize, RichMenuArea, RichMenuBounds, MessageAction
)

CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
if not CHANNEL_ACCESS_TOKEN or CHANNEL_ACCESS_TOKEN == "YOUR_CHANNEL_ACCESS_TOKEN":
    print("❌ 請先在 .env 中設定 LINE_CHANNEL_ACCESS_TOKEN！")
    sys.exit(1)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

def generate_rich_menu_image():
    """使用 Pillow 繪製專業 2500x1686 深色操盤風格 Rich Menu 圖片"""
    width = 2500
    height = 1686
    img = Image.new("RGB", (width, height), color="#0f172a") # 深 slate 底色
    draw = ImageDraw.Draw(img)

    font_path = "C:/Windows/Fonts/msjhbd.ttc"
    if not os.path.exists(font_path):
        font_path = "C:/Windows/Fonts/msjh.ttc"

    font_title = ImageFont.truetype(font_path, 82)
    font_sub = ImageFont.truetype(font_path, 42)
    font_badge = ImageFont.truetype(font_path, 36)

    cols = 3
    rows = 2
    tile_w = width // cols # 833
    tile_h = height // rows # 843

    tiles_data = [
        # Row 1
        {
            "tag": "PORTFOLIO", "tag_bg": "#0284c7",
            "title": "💼 我的持倉", "sub": "即時損益 ｜ -7% 停損監控",
            "border": "#38bdf8", "glow": "rgba(56, 189, 248, 0.15)"
        },
        {
            "tag": "HOT TSMC", "tag_bg": "#10b981",
            "title": "📈 台積電 2330", "sub": "4合1多維診斷 ｜ 20 EMA",
            "border": "#34d399", "glow": "rgba(16, 185, 129, 0.15)"
        },
        {
            "tag": "HOT TXC", "tag_bg": "#8b5cf6",
            "title": "⚡ 晶技 3042", "sub": "5分K 日內架構 ｜ 支撐壓力",
            "border": "#a78bfa", "glow": "rgba(139, 92, 246, 0.15)"
        },
        # Row 2
        {
            "tag": "BUY ORDER", "tag_bg": "#ea580c",
            "title": "➕ 記錄買進", "sub": "自動建立持股與風控底線",
            "border": "#fb923c", "glow": "rgba(234, 88, 12, 0.15)"
        },
        {
            "tag": "SELL ORDER", "tag_bg": "#dc2626",
            "title": "➖ 標記平倉", "sub": "獲利了結 ｜ 移出盤中巡邏",
            "border": "#f87171", "glow": "rgba(220, 38, 38, 0.15)"
        },
        {
            "tag": "GUIDE & HELP", "tag_bg": "#475569",
            "title": "🛡️ 指令指南", "sub": "功能介紹 ｜ 操盤語法說明",
            "border": "#94a3b8", "glow": "rgba(148, 163, 184, 0.15)"
        },
    ]

    margin_card = 28
    for i, data in enumerate(tiles_data):
        r = i // cols
        c = i % cols
        x1 = c * tile_w + margin_card
        y1 = r * tile_h + margin_card
        x2 = (c + 1) * tile_w - margin_card if c < cols - 1 else width - margin_card
        y2 = (r + 1) * tile_h - margin_card

        # 卡片本體圓角矩形
        draw.rounded_rectangle(
            [x1, y1, x2, y2],
            radius=36,
            fill="#1e293b",
            outline=data["border"],
            width=5
        )

        # 頂部小標籤徽章
        badge_text = data["tag"]
        badge_w = len(badge_text) * 22 + 40
        badge_x1 = x1 + 50
        badge_y1 = y1 + 60
        badge_x2 = badge_x1 + badge_w
        badge_y2 = badge_y1 + 55
        draw.rounded_rectangle(
            [badge_x1, badge_y1, badge_x2, badge_y2],
            radius=16,
            fill=data["tag_bg"]
        )
        draw.text((badge_x1 + 20, badge_y1 + 8), badge_text, fill="#ffffff", font=font_badge)

        # 大標題
        title_y = y1 + 270
        draw.text((x1 + 50, title_y), data["title"], fill="#f8fafc", font=font_title)

        # 副標題
        sub_y = title_y + 160
        draw.text((x1 + 52, sub_y), data["sub"], fill="#94a3b8", font=font_sub)

        # 底部裝飾點線
        draw.line([x1 + 50, y2 - 80, x2 - 50, y2 - 80], fill="#334155", width=3)

    return img

def setup_rich_menu():
    print("🎨 正在使用 Pillow 繪製 2500x1686 專業操盤 Rich Menu 圖片...")
    img = generate_rich_menu_image()
    img_path = os.path.join(current_dir, "rich_menu.png")
    img.save(img_path, format="PNG")
    print(f"✅ 圖片繪製完成並儲存至: {img_path}")

    # 1. 刪除舊的 Rich Menu (若有)
    print("🔍 檢查並清理舊的 Rich Menu...")
    try:
        old_menus = line_bot_api.get_rich_menu_list()
        for m in old_menus:
            line_bot_api.delete_rich_menu(m.rich_menu_id)
            print(f"🗑️ 已清除舊選單: {m.rich_menu_id}")
    except Exception as e:
        print(f"清理警告: {e}")

    # 2. 定義 Rich Menu 物件
    cols = 3
    rows = 2
    tile_w = 2500 // cols
    tile_h = 1686 // rows

    areas = [
        # 0: 💼 持倉
        RichMenuArea(
            bounds=RichMenuBounds(x=0, y=0, width=tile_w, height=tile_h),
            action=MessageAction(label="我的持倉", text="持倉")
        ),
        # 1: 📈 台積電 2330
        RichMenuArea(
            bounds=RichMenuBounds(x=tile_w, y=0, width=tile_w, height=tile_h),
            action=MessageAction(label="台積電 2330", text="2330")
        ),
        # 2: ⚡ 晶技 3042
        RichMenuArea(
            bounds=RichMenuBounds(x=tile_w * 2, y=0, width=tile_w, height=tile_h),
            action=MessageAction(label="晶技 3042", text="3042")
        ),
        # 3: ➕ 記錄買進
        RichMenuArea(
            bounds=RichMenuBounds(x=0, y=tile_h, width=tile_w, height=tile_h),
            action=MessageAction(label="記錄買進", text="買 2330 980")
        ),
        # 4: ➖ 標記平倉
        RichMenuArea(
            bounds=RichMenuBounds(x=tile_w, y=tile_h, width=tile_w, height=tile_h),
            action=MessageAction(label="標記平倉", text="賣 2330")
        ),
        # 5: 🛡️ 指令指南
        RichMenuArea(
            bounds=RichMenuBounds(x=tile_w * 2, y=tile_h, width=tile_w, height=tile_h),
            action=MessageAction(label="指令指南", text="說明")
        )
    ]

    rich_menu_to_create = RichMenu(
        size=RichMenuSize(width=2500, height=1686),
        selected=True,
        name="Quant_Trading_Menu",
        chat_bar_text="⚡ 智能操盤選單",
        areas=areas
    )

    print("🚀 正在向 LINE 官方 API 註冊 Rich Menu...")
    rich_menu_id = line_bot_api.create_rich_menu(rich_menu=rich_menu_to_create)
    print(f"✅ Rich Menu 建立成功，ID: {rich_menu_id}")

    # 3. 上傳圖片
    print("📤 正在上傳選單圖片至 LINE CDN...")
    with open(img_path, "rb") as f:
        line_bot_api.set_rich_menu_image(rich_menu_id, "image/png", f)
    print("✅ 圖片上傳成功！")

    # 4. 設為預設選單
    print("📌 正在將選單設為所有用戶預設選單 (Default)...")
    line_bot_api.set_default_rich_menu(rich_menu_id)
    print(f"🎉 大功告成！所有加入 LINE Bot 的用戶現在打開對話框，底部都會自動顯示「⚡ 智能操盤選單」！")

if __name__ == "__main__":
    setup_rich_menu()
