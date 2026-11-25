import sqlite3
db = sqlite3.connect("C:/Temp/n8n-db.sqlite")
c = db.cursor()
try:
    c.execute("SELECT label, substr(apiKey,1,8) FROM user_api_keys")
    print("API keys (prefix only):", c.fetchall())
except Exception as e:
    print("API keys table error:", e)

c.execute("SELECT id, name, active FROM workflow_entity ORDER BY updatedAt DESC")
for r in c.fetchall():
    print(r)

try:
    c.execute("SELECT table_name FROM information_schema.tables")
except:
    pass
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", [r[0] for r in c.fetchall()])
