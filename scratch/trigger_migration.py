import sys
import os
sys.path.append(os.getcwd())
from kuro_backend import chat_history
try:
    chat_history.init_db()
    print("Database migration successful.")
except Exception as e:
    print(f"Migration failed: {e}")
