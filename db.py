import sqlite3

DB_PATH = "library_v3.db"

def get_conn():
    """Establishes connection with Row factory and Foreign Keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    # Enable Foreign Key constraints to keep data linked correctly
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema and creates a default plain-text admin."""
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
                book_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                issue_date TEXT NOT NULL,
                due_date TEXT NOT NULL,
                return_date TEXT,
                fine_amount REAL DEFAULT 0,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        
        # Create default admin using PLAIN TEXT password
        cur = conn.cursor()
        admin_exists = cur.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        
        if not admin_exists:
            cur.execute("""
                INSERT INTO users (username, password, firstname, role) 
                VALUES (?, ?, ?, ?)
            """, ('admin', 'admin123', 'System', 'admin'))
            
        conn.commit()

def query_db(query, args=(), one=False):
    """
    Robust helper to handle both SELECT and Data Modification queries.
    Returns a dict/list of dicts for SELECTs, or None for others.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, args)
            
            # Checks if the query returned rows (SELECT)
            if cur.description:
                result = cur.fetchall()
                if not result:
                    return None if one else []
                
                if one:
                    return dict(result[0])
                return [dict(row) for row in result]
            
            # For INSERT, UPDATE, DELETE, the 'with' block handles the commit
            return None
            
    except Exception as e:
        print(f"Database Error: {e}")
        return None if one else []

if __name__ == "__main__":
    init_db()
    print(f"Database {DB_PATH} initialized successfully.")
