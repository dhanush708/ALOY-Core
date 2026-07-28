import sqlite3
import json

db_path = r'C:\Users\DHANUSH ANBU\AppData\Roaming\ALOY\data\aloy.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

conv_ids = [
    'cd9a900b-b58c-487e-afd1-ab6d41f719ad',
    'cb41ddaf-00f1-467e-be5d-64b09d78b1d1',
    '4916b7a9-8df6-4f59-ac9c-e6d08afd05c2'
]

for cid in conv_ids:
    print(f'\n--- Conversation {cid} ---')
    cursor.execute('SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = ?', (cid,))
    count = cursor.fetchone()[0]
    print(f'Total messages: {count}')
    
    cursor.execute('SELECT id, created_at, content, metadata FROM conversation_messages WHERE conversation_id = ? AND role = "system"', (cid,))
    for row in cursor.fetchall():
        try:
            meta = json.loads(row['metadata'])
            if meta.get('is_summary'):
                print(f'Compaction executed: YES, timestamp: {row["created_at"]}, trigger: message limit exceeded.')
                print(f'Summary content: {row["content"]}')
        except:
            pass
