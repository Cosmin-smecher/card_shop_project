from pathlib import Path
import sqlite3

# ✅ Point this to YOUR existing SQLite file name/location
# If your DB is in the same folder as this file (recommended),
# just put the filename below, e.g. "cards_database.db"
DB_PATH = Path(__file__).with_name("cards.db")


def get_conn():
    """Return a connection to your existing SQLite database.
    Row factory returns dict-like rows for easy JSON conversion.
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con
