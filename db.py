import sqlite3

DB_PATH = "library_v2.db"  # We changed this to v2 to force Render to create a fresh file

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
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
                description TEXT,
                image_url TEXT,
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
        # Create default admin
        cur = conn.cursor()
        admin = cur.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if not admin:
            cur.execute("INSERT INTO users (username, password, firstname, role) VALUES (?, ?, ?, ?)",
                        ('admin', 'admin123', 'System', 'admin'))
        conn.commit()

def query_db(query, args=(), one=False):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, args)
            if query.strip().upper().startswith("SELECT"):
                result = cur.fetchall()
                return (dict(result[0]) if result else None) if one else [dict(row) for row in result]
            conn.commit()
            return None
    except Exception as e:
        print(f"Database Error: {e}")
        return None if one else []
