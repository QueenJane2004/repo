import sqlite3
from datetime import datetime


def init_db():
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()

    # 1. Users Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                       username TEXT UNIQUE, 
                       password TEXT, 
                       firstname TEXT,
                       lastname TEXT,
                       role TEXT)''')

    # 2. Updated Books Table
    # Added: publisher, image_url, description
    cursor.execute('''CREATE TABLE IF NOT EXISTS books 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                       title TEXT, 
                       author TEXT,
                       publisher TEXT,
                       image_url TEXT,
                       description TEXT,
                       barcode TEXT UNIQUE,
                       quantity INTEGER DEFAULT 1,
                       status TEXT DEFAULT 'Available')''')

    # --- AUTOMATIC MIGRATION LOGIC ---
    # This checks for new columns and adds them to your existing database
    # if they don't exist yet.
    columns_to_check = [
        ('publisher', 'TEXT'),
        ('image_url', 'TEXT'),
        ('description', 'TEXT'),
        ('barcode', 'TEXT UNIQUE')
    ]

    for col_name, col_type in columns_to_check:
        try:
            cursor.execute(f"SELECT {col_name} FROM books LIMIT 1")
        except sqlite3.OperationalError:
            print(f"Migrating database: Adding '{col_name}' column to books table...")
            try:
                cursor.execute(f"ALTER TABLE books ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError as e:
                print(f"Migration skip for {col_name}: {e}")

    # 3. Loans Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS loans 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                       book_id INTEGER, 
                       user_id INTEGER, 
                       issue_date DATE,
                       due_date DATE,
                       return_date DATE,
                       fine_amount REAL DEFAULT 0.0,
                       FOREIGN KEY(book_id) REFERENCES books(id),
                       FOREIGN KEY(user_id) REFERENCES users(id))''')

    # 4. Messages Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                       user_id INTEGER, 
                       sender_name TEXT, 
                       content TEXT, 
                       is_admin_reply INTEGER DEFAULT 0,
                       timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                       FOREIGN KEY(user_id) REFERENCES users(id))''')

    # 5. Ensure Admin Account Exists
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password, firstname, lastname, role) VALUES (?, ?, ?, ?, ?)",
                       ('admin', 'admin123', 'System', 'Administrator', 'admin'))

    conn.commit()
    conn.close()


def query_db(query, args=(), one=False):
    conn = sqlite3.connect('library.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    results = []
    try:
        cur.execute(query, args)
        rv = cur.fetchall()
        # Convert row objects to dictionaries for easy use in Flask
        results = [dict(row) for row in rv]
        conn.commit()
    except Exception as e:
        print(f"DATABASE ERROR: {e}")
        conn.rollback()
        results = []
    finally:
        conn.close()

    if one:
        return results[0] if results else None
    return results