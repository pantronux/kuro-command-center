import sqlite3
conn = sqlite3.connect("kuro_chat_history.db")
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(chat_history)")
columns = cursor.fetchall()
for col in columns:
    print(col)
conn.close()
