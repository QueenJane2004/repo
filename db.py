import sqlite3
import os

# SQLite uses a local file instead of a URL
DB_PATH = "library.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    # This crucial line allows us to access data like a dictionary: user['id']
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        # SQLite uses INTEGER PRIMARY KEY AUTOINCREMENT instead of SERIAL
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                firstname TEXT,
                lastname TEXT,
                role TEXT DEFAULT 'user'
            );

            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT,
                publisher TEXT,
                image_url TEXT,
                description TEXT,
                barcode TEXT UNIQUE,
                isbn TEXT,
                quantity INTEGER DEFAULT 1,
                status TEXT DEFAULT 'Available'
            );

            CREATE TABLE IF NOT EXISTS loans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                issue_date TEXT NOT NULL,
                due_date TEXT NOT NULL,
                return_date TEXT,
                fine_amount REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

def query_db(query, args=(), one=False):
    # SQLite uses '?' as placeholders. We convert '%s' to '?' just in case.
    query = query.replace("%s", "?")
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, args)
            
            if query.strip().upper().startswith("SELECT"):
                result = cur.fetchall()
                # Convert SQLite rows to real dictionaries for app.py
                dict_result = [dict(row) for row in result]
                return dict_result[0] if one and dict_result else (None if one else dict_result)
            else:
                conn.commit()
                return None
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"DB ERROR: {e}")
        return None if one else []
