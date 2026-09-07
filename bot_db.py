# -*- coding: utf-8 -*-
"""
bot_db.py - SQLite 個人持倉與風控告警資料庫模組
支援用戶自動登記、持股增刪改查、盤中巡邏持股匯總與每日告警冷卻去重
"""

import os
import sqlite3
from datetime import datetime

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.db")

def get_connection(db_path=None):
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path=None):
    """初始化資料庫表結構"""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        # 1. 用戶表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            line_user_id TEXT UNIQUE NOT NULL,
            display_name TEXT,
            alert_enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 2. 持倉表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            stock_name TEXT,
            shares INTEGER DEFAULT 1000,
            cost_price REAL NOT NULL,
            stop_loss_pct REAL DEFAULT -7.0,
            status TEXT DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, ticker)
        )
        """)

        # 3. 告警紀錄表（防盤中頻繁轟炸冷卻）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            trigger_price REAL NOT NULL,
            alert_date TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)
        conn.commit()

def get_or_create_user(line_user_id, display_name=None, db_path=None):
    """取得或建立 LINE 用戶，回傳用戶 dict"""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE line_user_id = ?", (line_user_id,))
        row = cursor.fetchone()
        if row:
            if display_name and row["display_name"] != display_name:
                cursor.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, row["id"]))
                conn.commit()
            return dict(row)
        
        cursor.execute(
            "INSERT INTO users (line_user_id, display_name) VALUES (?, ?)",
            (line_user_id, display_name or "LineUser")
        )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE id = last_insert_rowid()")
        return dict(cursor.fetchone())

def add_or_update_position(line_user_id, ticker, cost_price, shares=1000, stock_name=None, db_path=None):
    """新增或更新持股，若已存在則覆蓋成本與股數"""
    user = get_or_create_user(line_user_id, db_path=db_path)
    user_id = user["id"]
    t = str(ticker).strip()
    c_p = float(cost_price)
    sh = int(shares)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO positions (user_id, ticker, stock_name, shares, cost_price, status, updated_at)
        VALUES (?, ?, ?, ?, ?, 'OPEN', ?)
        ON CONFLICT(user_id, ticker) DO UPDATE SET
            shares = excluded.shares,
            cost_price = excluded.cost_price,
            stock_name = COALESCE(excluded.stock_name, positions.stock_name),
            status = 'OPEN',
            updated_at = excluded.updated_at
        """, (user_id, t, stock_name, sh, c_p, now_str))
        conn.commit()

        cursor.execute("SELECT * FROM positions WHERE user_id = ? AND ticker = ?", (user_id, t))
        return dict(cursor.fetchone())

def close_position(line_user_id, ticker, db_path=None):
    """將持股標記為結案平倉（CLOSED）"""
    user = get_or_create_user(line_user_id, db_path=db_path)
    user_id = user["id"]
    t = str(ticker).strip()

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE positions SET status = 'CLOSED', updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND ticker = ? AND status = 'OPEN'",
            (user_id, t)
        )
        affected = cursor.rowcount
        conn.commit()
        return affected > 0

def get_user_positions(line_user_id, db_path=None):
    """取得指定用戶的所有開啟中持倉"""
    user = get_or_create_user(line_user_id, db_path=db_path)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM positions WHERE user_id = ? AND status = 'OPEN' ORDER BY id ASC",
            (user["id"],)
        )
        return [dict(r) for r in cursor.fetchall()]

def get_all_active_positions(db_path=None):
    """供盤中巡邏 Worker 批次查詢所有用戶的有效持倉"""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT p.*, u.line_user_id, u.display_name, u.alert_enabled
        FROM positions p
        JOIN users u ON p.user_id = u.id
        WHERE p.status = 'OPEN' AND u.alert_enabled = 1
        """)
        return [dict(r) for r in cursor.fetchall()]

def should_send_alert(user_id, ticker, alert_type, alert_date=None, db_path=None):
    """判斷今日該用戶的該標的是否已發過同類型告警（單日單股冷卻去重）"""
    today_str = alert_date or datetime.now().strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id FROM alert_logs
        WHERE user_id = ? AND ticker = ? AND alert_type = ? AND alert_date = ?
        """, (user_id, str(ticker).strip(), alert_type, today_str))
        return cursor.fetchone() is None

def record_alert_log(user_id, ticker, alert_type, trigger_price, alert_date=None, db_path=None):
    """記錄已發出的告警"""
    today_str = alert_date or datetime.now().strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO alert_logs (user_id, ticker, alert_type, trigger_price, alert_date)
        VALUES (?, ?, ?, ?, ?)
        """, (user_id, str(ticker).strip(), alert_type, float(trigger_price), today_str))
        conn.commit()
