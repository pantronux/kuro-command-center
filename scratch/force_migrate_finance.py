import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

OLD_USER = "kagetoki"
NEW_USER = "Faikhira"

# Update these to match the actual file names
FINANCE_DB = "kuro_finances.db"

def force_migrate_finance():
    if not os.path.exists(FINANCE_DB):
        logger.warning(f"Database {FINANCE_DB} not found.")
        return
    
    conn = sqlite3.connect(FINANCE_DB)
    c = conn.cursor()
    
    tables = [
        "monthly_budget", "financial_goals", "recurring_expenses",
        "api_usage_daily", "watched_symbols", "prediction_watch",
        "market_hud_snapshot"
    ]
    
    for tbl in tables:
        c.execute(f"PRAGMA table_info({tbl})")
        cols = [row[1] for row in c.fetchall()] # row[1] is the column name
        if "username" not in cols:
            logger.info(f"Adding username column to {tbl}")
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN username TEXT NOT NULL DEFAULT 'Pantronux'")
        
        logger.info(f"Updating {tbl} for renaming")
        c.execute(f"UPDATE {tbl} SET username = ? WHERE username = ?", (NEW_USER, OLD_USER))
        logger.info(f"  Rows updated: {c.rowcount}")
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    force_migrate_finance()
    # Run the previous migration for other DBs too just in case
    import subprocess
    subprocess.run(["python3", "scratch/migrate_user.py"])
