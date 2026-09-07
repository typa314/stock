# -*- coding: utf-8 -*-
"""
bot_flex.py - LINE Flex Message 精美卡片渲染模組
產生深色專業操盤風格的 Flex Message JSON 結構
"""

def get_tw_pnl_color(pnl):
    """台股紅漲綠跌慣例：正值為紅色 #ef4444，負值為綠色 #22c55e"""
    if pnl > 0:
        return "#ef4444"
    elif pnl < 0:
        return "#22c55e"
    return "#94a3b8"

def build_portfolio_flex(user_name, items, total_pnl, total_pnl_pct):
    """
    建立個人持股風控總覽 Flex Bubble
    items: list of dict(ticker, stock_name, shares, cost_price, current_price, pnl, pnl_pct, stop_7, buf_7, tag, tag_color)
    """
    total_color = get_tw_pnl_color(total_pnl)
    total_sign = "+" if total_pnl > 0 else ""

    body_contents = []

    if not items:
        body_contents.append({
            "type": "text",
            "text": "目前尚無持倉記錄。\n請輸入「買 2330 980」建立首檔持股！",
            "wrap": True,
            "color": "#94a3b8",
            "size": "sm",
            "margin": "md"
        })
    else:
        for idx, item in enumerate(items):
            if idx > 0:
                body_contents.append({
                    "type": "separator",
                    "margin": "lg",
                    "color": "#334155"
                })

            item_pnl_color = get_tw_pnl_color(item["pnl"])
            item_sign = "+" if item["pnl"] > 0 else ""

            body_contents.append({
                "type": "box",
                "layout": "vertical",
                "margin": "md",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {
                                "type": "text",
                                "text": f"{item['stock_name']} ({item['ticker']})",
                                "weight": "bold",
                                "size": "md",
                                "color": "#f8fafc",
                                "flex": 3
                            },
                            {
                                "type": "text",
                                "text": item["tag"],
                                "size": "xs",
                                "color": item["tag_color"],
                                "weight": "bold",
                                "align": "end",
                                "flex": 2
                            }
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "sm",
                        "contents": [
                            {
                                "type": "text",
                                "text": f"成本 {item['cost_price']:.2f} ➔ 現價 {item['current_price']:.2f}",
                                "size": "xs",
                                "color": "#94a3b8",
                                "flex": 3
                            },
                            {
                                "type": "text",
                                "text": f"{item_sign}{item['pnl_pct']:+.2f}%",
                                "size": "sm",
                                "color": item_pnl_color,
                                "weight": "bold",
                                "align": "end",
                                "flex": 2
                            }
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "xs",
                        "contents": [
                            {
                                "type": "text",
                                "text": f"強制停損: {item['stop_7']:.2f} 元 (-7%)",
                                "size": "xxs",
                                "color": "#f59e0b",
                                "flex": 3
                            },
                            {
                                "type": "text",
                                "text": f"損益 {item_sign}{int(item['pnl_amount']):,}",
                                "size": "xs",
                                "color": item_pnl_color,
                                "align": "end",
                                "flex": 2
                            }
                        ]
                    }
                ]
            })

    flex_bubble = {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": "💼 個人持股風控總覽",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#38bdf8"
                },
                {
                    "type": "text",
                    "text": f"用戶: {user_name} ｜ 遵循 Minervini -7% 資本保護鐵律",
                    "size": "xxs",
                    "color": "#64748b",
                    "margin": "xs"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "16px",
            "contents": body_contents
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "投資組合總損益",
                            "size": "sm",
                            "color": "#cbd5e1",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "text": f"{total_sign}${int(total_pnl):,} ({total_sign}{total_pnl_pct:+.2f}%)",
                            "size": "md",
                            "color": total_color,
                            "weight": "bold",
                            "align": "end"
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": "💡 提示：輸入「買 [代號] [成本]」加倉 ｜「賣 [代號]」平倉",
                    "size": "xxs",
                    "color": "#64748b",
                    "margin": "md",
                    "align": "center"
                }
            ]
        }
    }
    return flex_bubble

def build_stop_loss_alert_flex(stock_name, ticker, current_price, cost_price, stop_price, pnl_pct):
    """建立觸發 -7% 強制停損的紅色高警戒 Flex Bubble"""
    diff_pct = (current_price - cost_price) / cost_price * 100

    flex_bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#7f1d1d",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": "🚨 BPA 強制停損緊急告警",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#fecaca"
                },
                {
                    "type": "text",
                    "text": "觸發 Minervini 資本保護鐵律，請嚴格執行紀律！",
                    "size": "xs",
                    "color": "#fca5a5",
                    "margin": "xs"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": f"{stock_name} ({ticker})",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#ffffff"
                },
                {
                    "type": "separator",
                    "margin": "md",
                    "color": "#334155"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "md",
                    "contents": [
                        {"type": "text", "text": "買進成本", "size": "sm", "color": "#94a3b8", "flex": 2},
                        {"type": "text", "text": f"{cost_price:.2f} 元", "size": "sm", "color": "#ffffff", "align": "end", "flex": 3}
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "contents": [
                        {"type": "text", "text": "目前現價", "size": "sm", "color": "#94a3b8", "flex": 2},
                        {"type": "text", "text": f"{current_price:.2f} 元 ({diff_pct:+.2f}%)", "size": "sm", "color": "#22c55e", "weight": "bold", "align": "end", "flex": 3}
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "contents": [
                        {"type": "text", "text": "強制停損線", "size": "sm", "color": "#f87171", "weight": "bold", "flex": 2},
                        {"type": "text", "text": f"{stop_price:.2f} 元 (-7.0%)", "size": "sm", "color": "#f87171", "weight": "bold", "align": "end", "flex": 3}
                    ]
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "backgroundColor": "#3b1414",
                    "paddingAll": "10px",
                    "cornerRadius": "6px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "🛡️ 風控指引：\n已跌破 -7% 強制停損底線！強烈建議立即分批減碼或出清離場，嚴防虧損失控，絕不凹單！",
                            "size": "xs",
                            "color": "#fca5a5",
                            "wrap": True
                        }
                    ]
                }
            ]
        }
    }
    return flex_bubble

def build_single_stock_flex(stock_name, ticker, close_now, chg_val, chg_pct, ema20_val, action_tag, action_sub, s1, r1):
    """建立單檔個股 BPA 即時診斷 Flex Bubble"""
    chg_color = get_tw_pnl_color(chg_val)
    chg_sign = "+" if chg_val > 0 else ""

    flex_bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{stock_name} ({ticker})",
                            "weight": "bold",
                            "size": "lg",
                            "color": "#ffffff",
                            "flex": 3
                        },
                        {
                            "type": "text",
                            "text": f"{close_now:.2f}",
                            "weight": "bold",
                            "size": "lg",
                            "color": chg_color,
                            "align": "end",
                            "flex": 2
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": f"漲跌 {chg_sign}{chg_val:.2f} ({chg_sign}{chg_pct:.2f}%) ｜ 20 EMA: {ema20_val:.2f} 元",
                    "size": "xs",
                    "color": "#94a3b8",
                    "margin": "xs"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#0f2942",
                    "paddingAll": "10px",
                    "cornerRadius": "6px",
                    "contents": [
                        {
                            "type": "text",
                            "text": action_tag,
                            "weight": "bold",
                            "size": "sm",
                            "color": "#38bdf8"
                        },
                        {
                            "type": "text",
                            "text": action_sub,
                            "size": "xs",
                            "color": "#cbd5e1",
                            "margin": "xs",
                            "wrap": True
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "lg",
                    "contents": [
                        {"type": "text", "text": f"支撐 S1: {s1:.2f} 元", "size": "xs", "color": "#4ade80"},
                        {"type": "text", "text": f"壓力 R1: {r1:.2f} 元", "size": "xs", "color": "#f87171", "align": "end"}
                    ]
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "backgroundColor": "#0f172a",
            "paddingAll": "12px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#0284c7",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": f"買 {ticker}",
                        "text": f"買 {ticker} {close_now:.2f}"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "color": "#334155",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "查持倉",
                        "text": "持倉"
                    }
                }
            ]
        }
    }
    return flex_bubble
