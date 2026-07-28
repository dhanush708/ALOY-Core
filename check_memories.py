import sqlite3
import json

db_path = r'C:\Users\DHANUSH ANBU\AppData\Roaming\ALOY\data\aloy.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute('SELECT id, type, content, importance, tier, created_at FROM memories WHERE content LIKE "%OpenAI%"')
rows = cursor.fetchall()

if not rows:
    print('No memories found about OpenAI.')
else:
    for row in rows:
        print(dict(row))
