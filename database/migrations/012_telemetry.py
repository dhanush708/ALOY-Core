import sqlite3

def up(conn: sqlite3.Connection) -> None:
    # Note: telemetry and telemetry_aggregates tables are already created in 001_initial.py
    pass

def down(conn: sqlite3.Connection) -> None:
    # Handled by 001_initial.py
    pass
