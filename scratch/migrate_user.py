import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

OLD_USER = "kagetoki"
NEW_USER = "Faikhira"

DATABASES = [
    "kuro_finances.db",
    "kuro_short_term.db",
    "kuro_intelligence.db",
    "kuro_auth.db",
    "kuro_chat_history.db"
]

def migrate():
    for db_name in DATABASES:
        if not os.path.exists(db_name):
            logger.warning(f"Database {db_name} not found, skipping.")
            continue
        
        logger.info(f"Migrating {db_name}...")
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        for table in tables:
            # Check if table has 'username' or 'user_id' column
            cursor.execute(f"PRAGMA table_info({table});")
            columns = [row[1] for row in cursor.fetchall()]
            
            target_col = None
            if "username" in columns:
                target_col = "username"
            elif "user_id" in columns:
                target_col = "user_id"
                
            if target_col:
                logger.info(f"  Updating table {table} column {target_col}")
                cursor.execute(f"UPDATE {table} SET {target_col} = ? WHERE {target_col} = ?", (NEW_USER, OLD_USER))
                logger.info(f"    Affected rows: {cursor.rowcount}")
        
        conn.commit()
        conn.close()
    
    logger.info("Migration complete.")

if __name__ == "__main__":
    migrate()
