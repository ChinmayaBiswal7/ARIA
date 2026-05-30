import sqlite3
conn = sqlite3.connect("aria_memory.db")
print("User preferences schema:", [r for r in conn.execute("PRAGMA table_info(user_preferences)")])
print("User preferences sample:", list(conn.execute("SELECT * FROM user_preferences LIMIT 5")))
print("Preferences sample:", list(conn.execute("SELECT * FROM preferences LIMIT 5")))
