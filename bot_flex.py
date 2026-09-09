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
                                "text": f"浮虧警戒: {item['stop_7']:.2f} 元 (-{item.get('stop_pct', 0.07) * 100:.1f}%)",
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
                    "text": f"用戶: {user_name} ｜ 警戒幅度依個股 20 日波動度自動調整",
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

def build_stop_loss_alert_flex(stock_name, ticker, current_price, cost_price, stop_price, pnl_pct,
                               stop_pct=0.07, stop_basis="固定 -7%"):
    """
    建立跌破浮虧警戒線的紅色高警戒 Flex Bubble。

    stop_pct / stop_basis 由 kline.compute_risk_stop 提供（波動度自適應）。
    回測實證：固定 -7% 執行停損在本系統訊號下為淨損失，故本卡片定位為風險提示，
    不再宣稱為必須執行的鐵律。
    """
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
                    "text": "⚠️ 浮虧警戒通知",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#fecaca"
                },
                {
                    "type": "text",
                    "text": f"已跌破 {stop_basis} 計算之警戒線，請重新評估持有理由。",
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
                            "text": f"🛡️ 風控指引：\n已跌破 -{stop_pct * 100:.1f}% 浮虧警戒線（依據 {stop_basis}）。\n回測顯示固定 -7% 立即停損在本系統訊號下反而降低期望報酬，因此本通知不建議機械式砍出；請確認當初的進場理由是否已消失（跌破月線、法人轉賣超、評分掉出 80 分），再決定減碼或退出。",
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
    """建立單檔個股即時診斷 Flex Bubble（輕量版相容接口）"""
    chg_color = get_tw_pnl_color(chg_val)
    chg_sign = "+" if chg_val > 0 else ""

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
                    "color": "#d97706",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": f"⭐ 關注 {ticker}",
                        "text": f"+{ticker}"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#2563eb",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "💼 查看持倉",
                        "text": "持倉"
                    }
                }
            ]
        }
    }
    return flex_bubble

def build_dashboard_stock_flex(
    stock_name: str,
    ticker: str,
    market: str,
    close_now: float,
    chg_val: float,
    chg_pct: float,
    realtime_info: dict,
    df,
    bpa_res: dict,
    trend_score: int,
    trend_stage: str,
    rating_badge: str,
    comp: dict,
    sr: dict,
    mtf_status: str = None,
    conformal_status: str = None
):
    """
    建立 1:1 復刻 Web 儀表板的旗艦級 4合1 多維綜合評鑑 Flex Bubble
    包含：
    1. 頂部行情 + 盤中撮合標籤 + 漲跌幅
    2. 行動指引橫幅 (綜合評分 / 星級評等 / 操盤建議)
    3. 4 大核心量化指標 (市場趨勢狀態 / 20 EMA位階 / 多維量化評級 / 當前K線結構)
    4. 巨星多維綜合評級 (Minervini趨勢樣板 / CANSLIM成長動能 / 價格行為Price Action / 量能籌碼法人)
    5. 操盤方針指引與支撐壓力 S1/R1
    6. 一鍵下單買進與持倉查詢按鈕
    """
    m_label = "上市 (TSE)" if str(market).lower() == "tse" else "上櫃 (OTC)"
    is_rt = bool(realtime_info and realtime_info.get("is_realtime"))
    rt_time = realtime_info.get("time", "") if realtime_info else ""
    rt_text = f"⚡ 盤中即時 {rt_time}" if is_rt else "📅 盤後定盤"
    rt_bg = "#064e3b" if is_rt else "#1e293b"
    rt_color = "#34d399" if is_rt else "#94a3b8"

    chg_color = get_tw_pnl_color(chg_val)
    chg_sign = "+" if chg_val > 0 else ""

    # 行動指引與綜合評鑑
    comp = comp or {}
    action_tag = comp.get("action_tag", "🟡 建議觀望")
    action_advice = comp.get("action_sub", "順應 20 EMA 趨勢動態運行")
    score_val = comp.get("score", 70)
    badge_text = comp.get("badge", "⭐⭐⭐⭐ 優質多頭")

    if "買" in action_tag:
        act_bg = "#052e16"
        act_border = "#22c55e"
        act_color = "#4ade80"
    elif "空" in action_tag or "賣" in action_tag or "減" in action_tag:
        act_bg = "#450a0a"
        act_border = "#ef4444"
        act_color = "#f87171"
    elif "持" in action_tag:
        act_bg = "#082f49"
        act_border = "#38bdf8"
        act_color = "#38bdf8"
    else:
        act_bg = "#422006"
        act_border = "#f59e0b"
        act_color = "#fbbf24"

    # 4 大量化指標
    bpa_res = bpa_res or {}
    ai_zh = bpa_res.get("always_in_zh", "箱型震盪")
    ai_desc = bpa_res.get("always_in_desc", "區間高出低進 (突破易失敗)")
    ai_color = "#4ade80" if "多" in ai_zh else ("#f87171" if "空" in ai_zh else "#fbbf24")

    ema_val = float(df["ema20"].iloc[-1]) if (df is not None and hasattr(df, "columns") and "ema20" in df.columns and not df.empty) else close_now
    bias_ema = bpa_res.get("bias_ema20", 0.0)
    slope_ema = bpa_res.get("ema_slope", 0.0)

    last_bar = bpa_res.get("last_bar_type", "普通K線").split("/")[0].strip()
    stage_text = trend_stage.split("（")[0] if trend_stage else "常態整理"
    rating_short = rating_badge.split("（")[0] if rating_badge else "量化平穩"

    # 巨星多維 4 格
    m_passed = comp.get("minervini_passed", 5)
    m_status = comp.get("minervini_status", "符合樣板")
    m_color = comp.get("minervini_color", "#4ade80")

    c_grade = comp.get("canslim_grade", "A+ 卓越")
    c_sub = comp.get("canslim_sub", "動能穩健")
    c_color = comp.get("canslim_color", "#4ade80")

    b_zh = comp.get("bpa_zh", ai_zh)
    b_sub = comp.get("bpa_sub", "區間運行")
    b_color = comp.get("bpa_color", ai_color)

    chip_zh = comp.get("chip_zh", "籌碼常態")
    chip_sub = comp.get("chip_sub", "動向中性")
    chip_color = comp.get("chip_color", "#94a3b8")

    summary_advice = comp.get("summary_advice", "中期架構穩健，順應 20 EMA 支撐防守操作。")

    # 多時框位階 (MTF) 與 Conformal 雜訊評估
    if not mtf_status:
        if "多" in ai_zh:
            mtf_status = f"日線順勢多方 ({ai_zh})"
        elif "空" in ai_zh:
            mtf_status = f"日線偏空防守 ({ai_zh})"
        else:
            mtf_status = f"日線箱型區間 ({ai_zh})"

    if not conformal_status:
        if df is not None and hasattr(df, "columns") and len(df) >= 5 and "high" in df.columns and "low" in df.columns and "close" in df.columns:
            import pandas as pd
            tr1 = df["high"] - df["low"]
            tr2 = (df["high"] - df["close"].shift(1)).abs()
            tr3 = (df["low"] - df["close"].shift(1)).abs()
            daily_tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr20_d = float(daily_tr.tail(20).mean()) if len(daily_tr) >= 5 else 1.0
            today_rng = float(df["high"].iloc[-1] - df["low"].iloc[-1])
            ratio_d = today_rng / (atr20_d + 1e-9)
            if ratio_d > 2.5:
                conformal_status = f"雜訊比 {ratio_d:.2f}x (巨震 ⚠️)"
            else:
                conformal_status = f"雜訊比 {ratio_d:.2f}x (合格 🛡️)"
        else:
            conformal_status = "雜訊比合格 🛡️"

    s1 = float(sr.get("s1", close_now * 0.98)) if sr else close_now * 0.98
    r1 = float(sr.get("r1", close_now * 1.02)) if sr else close_now * 1.02

    flex_bubble = {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0b1120",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 3,
                            "contents": [
                                {
                                    "type": "text",
                                    "text": f"{stock_name} {ticker}",
                                    "weight": "bold",
                                    "size": "xl",
                                    "color": "#f8fafc"
                                },
                                {
                                    "type": "box",
                                    "layout": "horizontal",
                                    "margin": "xs",
                                    "spacing": "xs",
                                    "contents": [
                                        {
                                            "type": "box",
                                            "layout": "vertical",
                                            "backgroundColor": "#1e293b",
                                            "cornerRadius": "4px",
                                            "paddingAll": "2px",
                                            "contents": [
                                                {"type": "text", "text": f" {m_label} ", "size": "xxs", "color": "#94a3b8"}
                                            ]
                                        },
                                        {
                                            "type": "box",
                                            "layout": "vertical",
                                            "backgroundColor": rt_bg,
                                            "cornerRadius": "4px",
                                            "paddingAll": "2px",
                                            "contents": [
                                                {"type": "text", "text": f" {rt_text} ", "size": "xxs", "color": rt_color, "weight": "bold"}
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 2,
                            "contents": [
                                {"type": "text", "text": f"{close_now:.2f}", "weight": "bold", "size": "xl", "color": chg_color, "align": "end"},
                                {"type": "text", "text": f"{chg_sign}{chg_val:.2f} ({chg_sign}{chg_pct:.2f}%)", "weight": "bold", "size": "xs", "color": chg_color, "align": "end"}
                            ]
                        }
                    ]
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "14px",
            "contents": [
                # 行動指引橫幅
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": act_bg,
                    "cornerRadius": "8px",
                    "paddingAll": "10px",
                    "borderWidth": "1px",
                    "borderColor": act_border,
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": action_tag,
                                    "weight": "bold",
                                    "size": "xs",
                                    "color": act_color,
                                    "flex": 2
                                },
                                {
                                    "type": "text",
                                    "text": f"評分: {score_val}/100 ｜ {badge_text}",
                                    "size": "xxs",
                                    "color": "#94a3b8",
                                    "align": "end",
                                    "flex": 3
                                }
                            ]
                        },
                        {
                            "type": "text",
                            "text": action_advice,
                            "size": "xs",
                            "color": "#f1f5f9",
                            "wrap": True,
                            "margin": "xs"
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "xs",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": f"🌐 {mtf_status} ｜ 🎯 {conformal_status}",
                                    "size": "xxs",
                                    "color": "#38bdf8",
                                    "wrap": True
                                }
                            ]
                        }
                    ]
                },
                # 4 大關鍵指標 Grid
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "md",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#1e293b",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "市場趨勢狀態", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": ai_zh, "weight": "bold", "size": "sm", "color": ai_color, "margin": "xs"},
                                {"type": "text", "text": ai_desc, "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#1e293b",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "20 EMA 基準位階", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": f"{ema_val:.2f}", "weight": "bold", "size": "sm", "color": "#f8fafc", "margin": "xs"},
                                {"type": "text", "text": f"乖離 {bias_ema:+.1f}% ｜ 斜率 {slope_ema:+.1f}%", "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#1e293b",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "動能評級 (參考)", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": f"{trend_score:+d} 分", "weight": "bold", "size": "sm", "color": "#38bdf8", "margin": "xs"},
                                {"type": "text", "text": rating_short, "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#1e293b",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "當前 K 線結構", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": last_bar, "weight": "bold", "size": "sm", "color": "#f8fafc", "margin": "xs"},
                                {"type": "text", "text": stage_text, "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        }
                    ]
                },
                # 巨星多維綜合評級 (4合1)
                {
                    "type": "text",
                    "text": f"🌟 多維綜合評級 ｜ 評分：{score_val} / 100",
                    "weight": "bold",
                    "size": "xs",
                    "color": "#38bdf8",
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "xs",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#131f33",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "趨勢樣板 (Minervini)", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": f"{m_passed}/7 項", "weight": "bold", "size": "sm", "color": m_color, "margin": "xs"},
                                {"type": "text", "text": m_status, "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#131f33",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "成長動能 (CANSLIM)", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": c_grade, "weight": "bold", "size": "sm", "color": c_color, "margin": "xs"},
                                {"type": "text", "text": c_sub, "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#131f33",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "價格行為 (Price Action)", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": b_zh, "weight": "bold", "size": "sm", "color": b_color, "margin": "xs"},
                                {"type": "text", "text": b_sub, "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#131f33",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "量能籌碼 (VPA/法人)", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": chip_zh, "weight": "bold", "size": "sm", "color": chip_color, "margin": "xs"},
                                {"type": "text", "text": chip_sub, "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        }
                    ]
                },
                # 操盤方針摘要
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#14243b",
                    "cornerRadius": "6px",
                    "paddingAll": "8px",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"🎯 操盤方針：{action_tag} ｜ {summary_advice}",
                            "size": "xxs",
                            "color": "#cbd5e1",
                            "wrap": True
                        }
                    ]
                },
                # 支撐 S1 與壓力 R1
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "contents": [
                        {"type": "text", "text": f"支撐 S1: {s1:.2f} 元 (月線)", "size": "xxs", "color": "#4ade80", "flex": 1},
                        {"type": "text", "text": f"壓力 R1: {r1:.2f} 元 (前高)", "size": "xxs", "color": "#f87171", "align": "end", "flex": 1}
                    ]
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "backgroundColor": "#0b1120",
            "paddingAll": "12px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#0284c7",
                    "height": "sm",
                    "flex": 2,
                    "action": {
                        "type": "message",
                        "label": "⚡ 5分K 當沖",
                        "text": f"k{ticker}"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#d97706",
                    "height": "sm",
                    "flex": 2,
                    "action": {
                        "type": "message",
                        "label": f"⭐ 關注 {ticker}",
                        "text": f"+{ticker}"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#2563eb",
                    "height": "sm",
                    "flex": 2,
                    "action": {
                        "type": "message",
                        "label": "💼 查看持倉",
                        "text": "持倉"
                    }
                }
            ]
        }
    }
    return flex_bubble

def build_watchlist_flex(user_name, items):
    """
    建立用戶自選觀察清單 Flex Bubble
    items: list of dict(ticker, stock_name, current_price, chg_val, chg_pct, bpa_zh, bpa_color, ema20_dist, dist_desc)
    """
    body_contents = []

    if not items:
        body_contents.append({
            "type": "text",
            "text": "目前尚無觀察股票。\n請輸入「關注 2330」或「追蹤 00708L」將標的加入觀察清單！",
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

            chg_val = item.get("chg_val", 0.0)
            chg_pct = item.get("chg_pct", 0.0)
            chg_color = get_tw_pnl_color(chg_val)
            chg_sign = "+" if chg_val > 0 else ""

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
                                "text": f"{item['current_price']:.2f}",
                                "weight": "bold",
                                "size": "md",
                                "color": chg_color,
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
                                "text": item.get("bpa_zh", "常態運行"),
                                "size": "xs",
                                "color": item.get("bpa_color", "#fbbf24"),
                                "flex": 2
                            },
                            {
                                "type": "text",
                                "text": f"{chg_sign}{chg_val:.2f} ({chg_sign}{chg_pct:.2f}%) ｜ {item.get('dist_desc', '')}",
                                "size": "xs",
                                "color": "#94a3b8",
                                "align": "end",
                                "flex": 3
                            }
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "sm",
                        "spacing": "xs",
                        "contents": [
                            {
                                "type": "button",
                                "style": "primary",
                                "color": "#0284c7",
                                "height": "sm",
                                "flex": 1,
                                "action": {
                                    "type": "message",
                                    "label": "📊 4合1診斷",
                                    "text": item['ticker']
                                }
                            },
                            {
                                "type": "button",
                                "style": "primary",
                                "color": "#475569",
                                "height": "sm",
                                "flex": 1,
                                "action": {
                                    "type": "message",
                                    "label": "➖ 取消關注",
                                    "text": f"-{item['ticker']}"
                                }
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
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📋 自選觀察清單",
                            "weight": "bold",
                            "size": "lg",
                            "color": "#f8fafc",
                            "flex": 3
                        },
                        {
                            "type": "text",
                            "text": f"{len(items)} 檔追蹤中",
                            "size": "xs",
                            "color": "#38bdf8",
                            "align": "end",
                            "flex": 2
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": "⚡ 盤中自動偵測回測 20 EMA / H2 雙重底確認買點",
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
            "contents": body_contents
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
                    "color": "#2563eb",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "💼 查看持倉",
                        "text": "持倉"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#4f46e5",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "📖 指令說明",
                        "text": "說明"
                    }
                }
            ]
        }
    }
    return flex_bubble

def build_buy_signal_alert_flex(
    stock_name: str,
    ticker: str,
    signal_name: str,
    signal_desc: str,
    close_now: float,
    buy_stop: float,
    sell_stop: float,
    target_1r: float,
    target_2r: float,
    inst_status: str = "法人籌碼安全 (未見大額拋售)",
    conformal_status: str = "Conformal 雜訊合格 (波動受控)"
):
    """
    建立觀察名單觸發高勝率底部回測確認買點的專屬綠色推播 Flex Bubble
    """
    flex_bubble = {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#064e3b",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": "🎯 高勝率買點觸發！",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#6ee7b7"
                },
                {
                    "type": "text",
                    "text": "觀察標的回測底部確認，順勢高盈虧比進場機會！",
                    "size": "xs",
                    "color": "#a7f3d0",
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
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{stock_name} ({ticker})",
                            "weight": "bold",
                            "size": "xl",
                            "color": "#ffffff",
                            "flex": 3
                        },
                        {
                            "type": "text",
                            "text": f"{close_now:.2f} 元",
                            "weight": "bold",
                            "size": "xl",
                            "color": "#34d399",
                            "align": "end",
                            "flex": 2
                        }
                    ]
                },
                {
                    "type": "separator",
                    "margin": "md",
                    "color": "#334155"
                },
                # 訊號名稱與形態解析
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#022c22",
                    "cornerRadius": "6px",
                    "paddingAll": "10px",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": signal_name,
                            "weight": "bold",
                            "size": "sm",
                            "color": "#34d399"
                        },
                        {
                            "type": "text",
                            "text": signal_desc,
                            "size": "xs",
                            "color": "#cbd5e1",
                            "margin": "xs",
                            "wrap": True
                        }
                    ]
                },
                # 雙重風控驗證標籤（法人籌碼硬門檻 + Conformal 雜訊過濾）
                {
                    "type": "box",
                    "layout": "horizontal",
                    "backgroundColor": "#022c22",
                    "cornerRadius": "6px",
                    "paddingAll": "6px",
                    "margin": "xs",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"🛡️ {inst_status} ｜ 🎯 {conformal_status}",
                            "size": "xxs",
                            "color": "#6ee7b7",
                            "align": "center",
                            "weight": "bold",
                            "wrap": True
                        }
                    ]
                },
                # 風控掛單指標
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "建議突破買進 (Buy Stop)", "size": "xs", "color": "#94a3b8", "flex": 3},
                                {"type": "text", "text": f"{buy_stop:.2f} 元", "size": "xs", "color": "#38bdf8", "weight": "bold", "align": "end", "flex": 2}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "xs",
                            "contents": [
                                {"type": "text", "text": "防守停損線 (Stop Loss)", "size": "xs", "color": "#94a3b8", "flex": 3},
                                {"type": "text", "text": f"{sell_stop:.2f} 元", "size": "xs", "color": "#f87171", "weight": "bold", "align": "end", "flex": 2}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "xs",
                            "contents": [
                                {"type": "text", "text": "等距獲利目標 (1R / 2R)", "size": "xs", "color": "#94a3b8", "flex": 3},
                                {"type": "text", "text": f"{target_1r:.2f} / {target_2r:.2f} 元", "size": "xs", "color": "#fbbf24", "weight": "bold", "align": "end", "flex": 2}
                            ]
                        }
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
                        "label": "📊 4合1 診斷",
                        "text": ticker
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#2563eb",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "📋 查看自選",
                        "text": "自選"
                    }
                }
            ]
        }
    }
    return flex_bubble


def build_5m_stock_flex(res5: dict) -> dict:
    """
    建立 5 分鐘 K 線 (5m) 日內當沖多維研判 Flex Bubble
    包含：
    1. 行情報頭（現價、今日高低振幅、時間）
    2. 操盤方針 & 主力異動雷達橫幅
    3. 4 大量化指標矩陣（5m 市場架構、20 EMA 乖離、最新 K 棒形態、量能倍數）
    4. 當沖風控掛單指引卡（Buy Stop、Sell Stop、硬停損、1R、2R）
    5. 快捷操作按鈕（日K 4合1診斷、關注、持倉，無買入按鈕）
    """
    ticker = str(res5.get("ticker", "")).upper()
    stock_name = res5.get("stock_name", ticker)
    market = str(res5.get("market", "tse")).lower()
    m_label = "上市 (TSE)" if market == "tse" else "上櫃 (OTC)"

    close_now = float(res5.get("close_now", 0.0))
    chg_today = float(res5.get("change_today", 0.0))
    chg_today_pct = float(res5.get("change_today_pct", 0.0))
    chg_color = get_tw_pnl_color(chg_today)
    chg_sign = "+" if chg_today > 0 else ""

    high_today = float(res5.get("high_today", close_now))
    low_today = float(res5.get("low_today", close_now))
    range_today = float(res5.get("range_today", 0.0))
    data_time_str = res5.get("data_time_str", "")

    ema_now = float(res5.get("ema_now", close_now))
    ema_bias_pct = float(res5.get("ema_bias_pct", 0.0))
    ema_bias_sign = "+" if ema_bias_pct > 0 else ""

    bpa_status = res5.get("bpa_status", "箱型震盪")
    bpa_color = res5.get("bpa_status_color", "#fbbf24")

    last_bar_type = res5.get("last_bar_type", "⚪ 普通震盪棒")
    vol_now = float(res5.get("vol_now", 0.0))
    vol_ratio_5m = float(res5.get("vol_ratio_5m", 1.0))

    action_tag = res5.get("action_tag", "🟡 建議觀望整理")
    action_sub = res5.get("action_sub", "")
    action_color = res5.get("action_color", "#fbbf24")

    whale_tag = res5.get("whale_tag", "⚪ 常態量能流動")
    whale_color = res5.get("whale_color", "#94a3b8")
    whale_advice = res5.get("whale_advice", "")
    mtf_status = res5.get("mtf_status", "中性整理")
    conformal_status = res5.get("conformal_status", "充足 (合格)")
    noise_ratio = float(res5.get("noise_ratio", 1.0))

    buy_stop = float(res5.get("buy_stop", close_now))
    sell_stop = float(res5.get("sell_stop", close_now))
    stop_loss = float(res5.get("stop_loss", close_now))
    stop_type = res5.get("stop_type", "防守停損")
    r_val = float(res5.get("r_val", 0.0))
    target_1r = float(res5.get("target_1r", close_now))
    target_2r = float(res5.get("target_2r", close_now))
    pct_stop = abs(close_now - stop_loss) / close_now * 100 if close_now > 0 else 0.0
    pct_1r = abs(target_1r - close_now) / close_now * 100 if close_now > 0 else 0.0
    pct_2r = abs(target_2r - close_now) / close_now * 100 if close_now > 0 else 0.0

    flex_bubble = {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0b1329",
            "paddingAll": "16px",
            "contents": [
                # 代號與名稱
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
                            "flex": 4
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#1e293b",
                            "cornerRadius": "4px",
                            "paddingStart": "6px",
                            "paddingEnd": "6px",
                            "paddingTop": "2px",
                            "paddingBottom": "2px",
                            "contents": [
                                {"type": "text", "text": m_label, "size": "xxs", "color": "#94a3b8"}
                            ]
                        }
                    ]
                },
                # 現價與漲跌幅
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{close_now:.2f}",
                            "size": "xxl",
                            "weight": "bold",
                            "color": "#ffffff",
                            "flex": 3
                        },
                        {
                            "type": "text",
                            "text": f"{chg_sign}{chg_today:.2f} ({chg_sign}{chg_today_pct:.2f}%)",
                            "size": "sm",
                            "weight": "bold",
                            "color": chg_color,
                            "align": "end",
                            "gravity": "bottom",
                            "flex": 4
                        }
                    ]
                },
                # 日內區間與時間
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"⚡ 5分K ｜ 振幅 {range_today:.2f}元 ({low_today:.2f}~{high_today:.2f})",
                            "size": "xxs",
                            "color": "#94a3b8",
                            "flex": 5
                        },
                        {
                            "type": "text",
                            "text": data_time_str.split(" ")[-1] if data_time_str else "",
                            "size": "xxs",
                            "color": "#64748b",
                            "align": "end",
                            "flex": 3
                        }
                    ]
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "14px",
            "contents": [
                # 操盤方針與主力雷達橫幅
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#162235",
                    "cornerRadius": "8px",
                    "paddingAll": "10px",
                    "borderColor": "#1e3a5f",
                    "borderWidth": "1px",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": action_tag,
                                    "weight": "bold",
                                    "size": "sm",
                                    "color": action_color,
                                    "flex": 5
                                },
                                {
                                    "type": "text",
                                    "text": whale_tag,
                                    "weight": "bold",
                                    "size": "xs",
                                    "color": whale_color,
                                    "align": "end",
                                    "flex": 4
                                }
                            ]
                        },
                        {
                            "type": "text",
                            "text": f"💡 {action_sub}",
                            "size": "xxs",
                            "color": "#cbd5e1",
                            "wrap": True,
                            "margin": "sm"
                        },
                        {
                            "type": "text",
                            "text": f"🌐 多時框位階：{mtf_status}",
                            "size": "xxs",
                            "color": "#38bdf8",
                            "wrap": True,
                            "margin": "xs"
                        },
                        {
                            "type": "text",
                            "text": f"🎯 Conformal 雜訊比：{noise_ratio:.2f}x ATR ｜ {conformal_status}",
                            "size": "xxs",
                            "color": "#fbbf24" if ("過大" in conformal_status or "不足" in conformal_status or "過低" in conformal_status) else "#34d399",
                            "wrap": True,
                            "margin": "xs"
                        },
                        {
                            "type": "text",
                            "text": f"📢 {whale_advice}",
                            "size": "xxs",
                            "color": "#94a3b8",
                            "wrap": True,
                            "margin": "xs"
                        }
                    ]
                },
                # 4 大量化核心指標 (2x2 Grid)
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "md",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#131f33",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "5m 市場多空架構", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": bpa_status, "weight": "bold", "size": "xs", "color": bpa_color, "margin": "xs", "wrap": True}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#131f33",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "5m 20 EMA 基準", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": f"{ema_now:.2f} 元", "weight": "bold", "size": "xs", "color": "#38bdf8", "margin": "xs"},
                                {"type": "text", "text": f"乖離 {ema_bias_sign}{ema_bias_pct:.1f}%", "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#131f33",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "最新 5分K 棒形態", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": last_bar_type, "weight": "bold", "size": "xs", "color": "#ffffff", "margin": "xs", "wrap": True}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": "#131f33",
                            "cornerRadius": "6px",
                            "paddingAll": "8px",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "5m 量能倍數", "size": "xxs", "color": "#94a3b8"},
                                {"type": "text", "text": f"{vol_ratio_5m:.1f}倍 均量", "weight": "bold", "size": "xs", "color": whale_color, "margin": "xs"},
                                {"type": "text", "text": f"現量 {int(vol_now)} 張", "size": "xxs", "color": "#64748b", "margin": "xs"}
                            ]
                        }
                    ]
                },
                # 當沖風控掛單指引卡
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#14243b",
                    "cornerRadius": "8px",
                    "paddingAll": "10px",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "⚡ 5分K 當沖風控掛單指引",
                            "weight": "bold",
                            "size": "xs",
                            "color": "#38bdf8"
                        },
                        {
                            "type": "separator",
                            "margin": "xs",
                            "color": "#1e3a5f"
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "sm",
                            "contents": [
                                {"type": "text", "text": f"突破進場: {buy_stop:.2f}", "size": "xxs", "color": "#ef4444", "weight": "bold", "flex": 1},
                                {"type": "text", "text": f"跌破放空: {sell_stop:.2f}", "size": "xxs", "color": "#22c55e", "weight": "bold", "align": "end", "flex": 1}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "xs",
                            "contents": [
                                {"type": "text", "text": f"防守停損: {stop_loss:.2f} (風險 {r_val:.2f}元/{pct_stop:.1f}%)", "size": "xxs", "color": "#f59e0b", "flex": 1}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "xs",
                            "contents": [
                                {"type": "text", "text": f"目標 1R: {target_1r:.2f} (+{pct_1r:.1f}%)", "size": "xxs", "color": "#4ade80", "flex": 1},
                                {"type": "text", "text": f"目標 2R: {target_2r:.2f} (+{pct_2r:.1f}%)", "size": "xxs", "color": "#4ade80", "align": "end", "flex": 1}
                            ]
                        }
                    ]
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "backgroundColor": "#0b1120",
            "paddingAll": "12px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#0284c7",
                    "height": "sm",
                    "flex": 2,
                    "action": {
                        "type": "message",
                        "label": "📊 查日K (4合1)",
                        "text": ticker
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#d97706",
                    "height": "sm",
                    "flex": 2,
                    "action": {
                        "type": "message",
                        "label": f"⭐ 關注 {ticker}",
                        "text": f"+{ticker}"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#2563eb",
                    "height": "sm",
                    "flex": 2,
                    "action": {
                        "type": "message",
                        "label": "💼 查看持倉",
                        "text": "持倉"
                    }
                }
            ]
        }
    }
    return flex_bubble


