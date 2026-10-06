import bot_db
import firestore_sync

print("開始遷移現有的 SQLite 資料 (portfolio.db) 到 Firestore (database='default')...")
firestore_sync.force_upload_all(bot_db.DEFAULT_DB_PATH)
print("遷移結束！")
