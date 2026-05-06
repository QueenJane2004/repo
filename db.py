import sqlite3
import os

DB_PATH = "library.db"

def get_conn():
    # SQLite uses a local file, no need for DATABASE_URL
    conn = sqlite3.connect(DB_PATH)
    # This line is CRITICAL: it allows accessing columns by name like user['id']
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
                barcode TEXT UNIQUE,
                quantity INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS loans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER REFERENCES books(id),
                user_id INTEGER REFERENCES users(id),
                issue_date TEXT,
                due_date TEXT,
                return_date TEXT,
                fine_amount REAL DEFAULT 0
            );
        """)
        
        # Create a default admin if none exists
        cur = conn.cursor()
        admin_exists = cur.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if not admin_exists:
            cur.execute("INSERT INTO users (username, password, firstname, role) VALUES (?, ?, ?, ?)",
                        ('admin', 'admin123', 'Admin', 'admin'))
        conn.commit()

def query_db(query, args=(), one=False):
    # Standardize placeholders for SQLite
    query = query.replace("%s", "?")
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, args)
            if query.strip().upper().startswith("SELECT"):
                result = cur.fetchall()
                # Convert SQLite rows to dictionaries
                dict_result = [dict(row) for row in result]
                return dict_result[0] if one and dict_result else (None if one else dict_result)
            conn.commit()
            return None
    except Exception as e:
        print(f"DATABASE ERROR: {e}")
        return None if one else []
