import sqlite3

def up(conn: sqlite3.Connection) -> None:
    # Create the vec0 table
    conn.execute("DROP TABLE IF EXISTS memory_embeddings")
    conn.execute("""
        CREATE VIRTUAL TABLE memory_embeddings USING vec0(
            embedding float[768]
        )
    """)

def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS memory_embeddings")
