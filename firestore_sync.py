# -*- coding: utf-8 -*-
"""
firestore_sync.py - 負責 SQLite 與 Firestore 的增量同步 (Delta Sync)
遵守 GEMINI.md 最高原則：禁止頻繁輪詢，嚴控免費額度。
"""
import os
import threading
import logging
from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))
_firestore_db = None
_last_sync_time = None
_sync_lock = threading.Lock()

def is_test_env():
    import sys
    return "unittest" in sys.modules.keys() or "pytest" in sys.modules.keys()

def _get_firestore_client():
    if is_test_env():
        return None
    global _firestore_db
    if _firestore_db is not None:
        return _firestore_db
    
    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase_key.json")
    if not os.path.exists(key_path):
        return None
    
    try:
        from google.cloud import firestore
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
        # 使用原生模式的預設資料庫名稱 "default" (使用者截圖確認的命名)
        _firestore_db = firestore.Client(project="stock-8c97b", database="default")
        return _firestore_db
    except Exception as e:
        logging.error(f"Firestore Client Init Error: {e}")
        return None

def trigger_delta_write(collection_type, line_user_id, doc_id, data_dict):
    """
    增量寫入 Firestore，並更新 system/metadata
    collection_type: 'users', 'positions', 'watchlist'
    """
    db = _get_firestore_client()
    if not db:
        return

    try:
        batch = db.batch()
        
        # 準備資料與時間戳
        data = dict(data_dict)
        if 'id' in data:
            del data['id'] # 本地自增 ID 不上雲
        
        # 根據類別決定寫入路徑
        if collection_type == 'users':
            doc_ref = db.collection('users').document(line_user_id)
        elif collection_type == 'positions':
            doc_ref = db.collection('users').document(line_user_id).collection('positions').document(doc_id)
        elif collection_type == 'watchlist':
            doc_ref = db.collection('users').document(line_user_id).collection('watchlist').document(doc_id)
        else:
            return

        batch.set(doc_ref, data, merge=True)
        
        # 更新系統最後變動時間
        now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
        meta_ref = db.collection('system').document('metadata')
        batch.set(meta_ref, {'last_updated_str': now_str}, merge=True)
        
        batch.commit()
    except Exception as e:
        logging.error(f"Firestore Delta Write Error: {e}")

def sync_from_firestore(db_path):
    """
    從 Firestore 增量拉取最新變動，合併至本地 SQLite。
    透過比對 system/metadata，若無變動則只消耗 1 次 Read。
    """
    global _last_sync_time
    db = _get_firestore_client()
    if not db:
        return False
        
    with _sync_lock:
        try:
            meta_doc = db.collection('system').document('metadata').get()
            if not meta_doc.exists:
                return False
                
            remote_last_updated = meta_doc.to_dict().get('last_updated_str', '')
            
            # 若本地時間等於或大於遠端，代表沒有新資料需要拉取
            if _last_sync_time and remote_last_updated <= _last_sync_time:
                return False

            # 拉取變動的資料 (這裡採用全量拉取，但只會拉取 collection 的快照，未來可優化為依據時間戳)
            # 因為機器人資料量極小，全拉取也在幾十次 Read 內，滿足免費用量
            users_ref = db.collection('users').stream()
            
            snapshot_data = {"users": [], "positions": [], "watchlist": []}
            
            for u_doc in users_ref:
                u_data = u_doc.to_dict()
                u_data['line_user_id'] = u_doc.id
                snapshot_data["users"].append(u_data)
                
                pos_ref = u_doc.reference.collection('positions').stream()
                for p_doc in pos_ref:
                    p_data = p_doc.to_dict()
                    p_data['line_user_id'] = u_doc.id
                    p_data['ticker'] = p_doc.id
                    snapshot_data["positions"].append(p_data)
                    
                wl_ref = u_doc.reference.collection('watchlist').stream()
                for w_doc in wl_ref:
                    w_data = w_doc.to_dict()
                    w_data['line_user_id'] = u_doc.id
                    w_data['ticker'] = w_doc.id
                    snapshot_data["watchlist"].append(w_data)

            # 匯入本地
            import bot_db
            bot_db.import_db_snapshot(snapshot_data, db_path=db_path)
            
            _last_sync_time = remote_last_updated
            return True
        except Exception as e:
            logging.error(f"Firestore Sync Error: {e}")
            return False

def force_upload_all(db_path):
    """將現有 SQLite 全量上傳至 Firestore (僅供初始化遷移使用)"""
    import bot_db
    db = _get_firestore_client()
    if not db:
        print("未配置 Firestore")
        return

    snapshot = bot_db.export_db_snapshot(db_path)
    batch = db.batch()
    count = 0
    
    # 建立 users 映射
    users_map = {u['id']: u for u in snapshot['users']}
    
    for u in snapshot['users']:
        ref = db.collection('users').document(u['line_user_id'])
        u_copy = dict(u)
        del u_copy['id']
        batch.set(ref, u_copy, merge=True)
        count += 1
        
    for p in snapshot['positions']:
        line_uid = users_map.get(p['user_id'], {}).get('line_user_id')
        if not line_uid: continue
        ref = db.collection('users').document(line_uid).collection('positions').document(p['ticker'])
        p_copy = dict(p)
        del p_copy['id']
        del p_copy['user_id']
        batch.set(ref, p_copy, merge=True)
        count += 1
        
    for w in snapshot['watchlist']:
        line_uid = users_map.get(w['user_id'], {}).get('line_user_id')
        if not line_uid: continue
        ref = db.collection('users').document(line_uid).collection('watchlist').document(w['ticker'])
        w_copy = dict(w)
        del w_copy['id']
        del w_copy['user_id']
        batch.set(ref, w_copy, merge=True)
        count += 1
        
    now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
    meta_ref = db.collection('system').document('metadata')
    batch.set(meta_ref, {'last_updated_str': now_str}, merge=True)
    
    # Commit batch (限制：Firestore batch 最大 500 次寫入，若超過需要切分。本專案初期通常遠小於500)
    if count > 0:
        batch.commit()
        print(f"成功遷移 {count} 筆資料至 Firestore！")
    else:
        print("沒有資料需要遷移。")
