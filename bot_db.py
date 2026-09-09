# -*- coding: utf-8 -*-
"""
bot_db.py - SQLite 個人持倉與風控告警資料庫模組
支援用戶自動登記、持股增刪改查、盤中巡邏持股匯總與每日告警冷卻去重
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

# 台股標準時區 (GMT+8)
TW_TZ = timezone(timedelta(hours=8))

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.db")

@contextmanager
def get_connection(db_path=None):
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

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

        # 4. 觀察清單表（追蹤回測買點）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            stock_name TEXT,
            note TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, ticker)
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
    now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")

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
    # 必須與 add_position 用同一個時區來源：SQLite 的 CURRENT_TIMESTAMP 是 UTC，
    # 而新增持倉寫的是 GMT+8，混用會讓「平倉」的時間戳看起來比「買進」早 8 小時，
    # 雙節點同步以 updated_at 較新者為準時，平倉會被舊的買進紀錄蓋回 OPEN。
    now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE positions SET status = 'CLOSED', updated_at = ? WHERE user_id = ? AND ticker = ? AND status = 'OPEN'",
            (now_str, user_id, t)
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

def should_send_alert(user_id, ticker, alert_type, alert_date=None, db_path=None, cooldown_days=1):
    """判斷今日（或近 N 日內）該用戶的該標的是否已發過同類型告警（冷卻去重）"""
    if alert_date:
        today = datetime.strptime(alert_date, "%Y-%m-%d").date()
    else:
        today = datetime.now(TW_TZ).date()
    today_str = today.strftime("%Y-%m-%d")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        if cooldown_days <= 1:
            cursor.execute("""
            SELECT id FROM alert_logs
            WHERE user_id = ? AND ticker = ? AND alert_type = ? AND alert_date = ?
            """, (user_id, str(ticker).strip(), alert_type, today_str))
        else:
            start_date_str = (today - timedelta(days=cooldown_days - 1)).strftime("%Y-%m-%d")
            cursor.execute("""
            SELECT id FROM alert_logs
            WHERE user_id = ? AND ticker = ? AND alert_type = ? AND alert_date >= ? AND alert_date <= ?
            """, (user_id, str(ticker).strip(), alert_type, start_date_str, today_str))
        return cursor.fetchone() is None

def record_alert_log(user_id, ticker, alert_type, trigger_price, alert_date=None, db_path=None):
    """記錄已發出的告警"""
    today_str = alert_date or datetime.now(TW_TZ).strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO alert_logs (user_id, ticker, alert_type, trigger_price, alert_date)
        VALUES (?, ?, ?, ?, ?)
        """, (user_id, str(ticker).strip(), alert_type, float(trigger_price), today_str))
        conn.commit()

# ── 觀察名單 (Watchlist) 管理 ──────────────────────────────
def add_to_watchlist(line_user_id, ticker, stock_name=None, note=None, max_limit=None, db_path=None):
    """
    將股票加入用戶的觀察名單（預設不設上限）
    回傳: (ok: bool, message: str)
    """
    user = get_or_create_user(line_user_id, db_path=db_path)
    user_id = user["id"]
    t = str(ticker).strip().upper()
    now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        # 若有特別指定 max_limit 則檢查，預設 None 不設數量上限
        if max_limit is not None and max_limit > 0:
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM watchlist WHERE user_id = ? AND active = 1 AND ticker != ?",
                (user_id, t)
            )
            row = cursor.fetchone()
            current_cnt = row["cnt"] if row else 0
            if current_cnt >= max_limit:
                return False, f"⚠️ 您的觀察名單已達上限（{max_limit} 檔）！\n請先輸入「取消關注 [代號]」移出舊標的。"

        cursor.execute("""
        INSERT INTO watchlist (user_id, ticker, stock_name, note, active, updated_at)
        VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT(user_id, ticker) DO UPDATE SET
            stock_name = COALESCE(excluded.stock_name, watchlist.stock_name),
            note = COALESCE(excluded.note, watchlist.note),
            active = 1,
            updated_at = excluded.updated_at
        """, (user_id, t, stock_name, note, now_str))
        conn.commit()
        return True, f"✅ 已成功將【{stock_name or t} ({t})】加入自選觀察名單！"

def remove_from_watchlist(line_user_id, ticker, db_path=None):
    """將股票自用戶觀察名單移除（標記 active=0）"""
    user = get_or_create_user(line_user_id, db_path=db_path)
    user_id = user["id"]
    t = str(ticker).strip().upper()
    # 與 add_to_watchlist 同一時區來源（見 close_position 的說明）
    now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE watchlist SET active = 0, updated_at = ? WHERE user_id = ? AND ticker = ? AND active = 1",
            (now_str, user_id, t)
        )
        affected = cursor.rowcount
        conn.commit()
        return affected > 0

def get_user_watchlist(line_user_id, db_path=None):
    """取得指定用戶的所有有效觀察名單"""
    user = get_or_create_user(line_user_id, db_path=db_path)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM watchlist WHERE user_id = ? AND active = 1 ORDER BY updated_at DESC",
            (user["id"],)
        )
        return [dict(r) for r in cursor.fetchall()]

def get_all_active_watchlist(db_path=None):
    """供盤中巡邏 Worker 批次查詢所有開啟推播用戶的觀察名單標的"""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT w.*, u.line_user_id, u.display_name, u.alert_enabled
        FROM watchlist w
        JOIN users u ON w.user_id = u.id
        WHERE w.active = 1 AND u.alert_enabled = 1
        """)
        return [dict(r) for r in cursor.fetchall()]

# ── 雙節點資料同步 (Database Snapshot Export / Import) ─────
def export_db_snapshot(db_path=None):
    """匯出所有用戶、持倉與自選觀察名單快照字典"""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        users = [dict(r) for r in cursor.execute("SELECT id, line_user_id, display_name, alert_enabled, created_at FROM users").fetchall()]
        positions = [dict(r) for r in cursor.execute("SELECT id, user_id, ticker, stock_name, shares, cost_price, stop_loss_pct, status, created_at, updated_at FROM positions").fetchall()]
        watchlist = [dict(r) for r in cursor.execute("SELECT id, user_id, ticker, stock_name, note, active, created_at, updated_at FROM watchlist").fetchall()]
        return {"users": users, "positions": positions, "watchlist": watchlist}

def import_db_snapshot(data, db_path=None):
    """
    將外部節點的快照合併進本地資料庫。

    以 line_user_id 對映用戶並取用「本地」自增 id，不沿用來源節點的 id：
    兩個節點各自 AUTOINCREMENT，來源 id 直接寫入會撞號，
    或更糟——把持倉掛到同號的另一個用戶身上。
    positions / watchlist 以 (user_id, ticker) 為唯一鍵，updated_at 較新者為準。
    無法對映到本地用戶的資料寧可跳過也不猜。

    回傳各表「接受寫入」筆數 dict（updated_at 較舊而被拒收的不計；
    內容相同的重寫仍會計入，故筆數不等於「實際變動列數」）。合併失敗回傳 False。
    """
    if not isinstance(data, dict):
        return False

    stats = {"users": 0, "positions": 0, "watchlist": 0, "skipped": 0}
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # 1. 用戶對映：來源 id -> 本地 id
        id_map = {}
        for u in data.get("users", []):
            line_uid = u.get("line_user_id")
            if not line_uid:
                stats["skipped"] += 1
                continue
            cursor.execute("SELECT id FROM users WHERE line_user_id = ?", (line_uid,))
            row = cursor.fetchone()
            if row:
                local_id = row["id"]
                if u.get("display_name"):
                    cursor.execute(
                        "UPDATE users SET display_name = ?, alert_enabled = ? WHERE id = ?",
                        (u.get("display_name"), u.get("alert_enabled", 1), local_id)
                    )
            else:
                cursor.execute(
                    "INSERT INTO users (line_user_id, display_name, alert_enabled) VALUES (?, ?, ?)",
                    (line_uid, u.get("display_name") or "LineUser", u.get("alert_enabled", 1))
                )
                local_id = cursor.lastrowid
            if u.get("id") is not None:
                id_map[u["id"]] = local_id
            stats["users"] += 1

        # 2. 持倉（updated_at 較新者為準）
        for pos in data.get("positions", []):
            local_uid = id_map.get(pos.get("user_id"))
            if local_uid is None or not pos.get("ticker"):
                stats["skipped"] += 1
                continue
            cursor.execute("""
            INSERT INTO positions (user_id, ticker, stock_name, shares, cost_price, stop_loss_pct, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
            ON CONFLICT(user_id, ticker) DO UPDATE SET
                stock_name = excluded.stock_name,
                shares = excluded.shares,
                cost_price = excluded.cost_price,
                stop_loss_pct = excluded.stop_loss_pct,
                status = excluded.status,
                updated_at = excluded.updated_at
            WHERE excluded.updated_at >= positions.updated_at
            """, (
                local_uid, pos.get("ticker"), pos.get("stock_name"), pos.get("shares", 1000),
                pos.get("cost_price"), pos.get("stop_loss_pct", -7.0), pos.get("status", "OPEN"),
                pos.get("created_at"), pos.get("updated_at")
            ))
            if cursor.rowcount > 0:
                stats["positions"] += 1

        # 3. 自選觀察名單（updated_at 較新者為準）
        for w in data.get("watchlist", []):
            local_uid = id_map.get(w.get("user_id"))
            if local_uid is None or not w.get("ticker"):
                stats["skipped"] += 1
                continue
            cursor.execute("""
            INSERT INTO watchlist (user_id, ticker, stock_name, note, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
            ON CONFLICT(user_id, ticker) DO UPDATE SET
                stock_name = excluded.stock_name,
                note = excluded.note,
                active = excluded.active,
                updated_at = excluded.updated_at
            WHERE excluded.updated_at >= watchlist.updated_at
            """, (
                local_uid, w.get("ticker"), w.get("stock_name"), w.get("note"),
                w.get("active", 1), w.get("created_at"), w.get("updated_at")
            ))
            if cursor.rowcount > 0:
                stats["watchlist"] += 1

        conn.commit()
    return stats

