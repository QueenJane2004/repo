import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get('DATABASE_URL')


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:

            # 1. Users Table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE,
                    password TEXT,
                    firstname TEXT,
                    lastname TEXT,
                    role TEXT
                )
            ''')

            # 2. Books Table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS books (
                    id SERIAL PRIMARY KEY,
                    title TEXT,
                    author TEXT,
                    publisher TEXT,
                    image_url TEXT,
                    description TEXT,
                    barcode TEXT UNIQUE,
                    quantity INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'Available'
                )
            ''')

            # 3. Loans Table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS loans (
                    id SERIAL PRIMARY KEY,
                    book_id INTEGER REFERENCES books(id),
                    user_id INTEGER REFERENCES users(id),
                    issue_date DATE,
                    due_date DATE,
                    return_date DATE,
                    fine_amount REAL DEFAULT 0.0
                )
            ''')

            # 4. Messages Table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    sender_name TEXT,
                    content TEXT,
                    is_admin_reply INTEGER DEFAULT 0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 5. Default admin account
            cur.execute("SELECT id FROM users WHERE username = 'admin'")
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO users (username, password, firstname, lastname, role) VALUES (%s, %s, %s, %s, %s)",
                    ('admin', 'admin123', 'System', 'Administrator', 'admin')
                )

        conn.commit()


def query_db(query, args=(), one=False):
    # Convert SQLite ? placeholders to PostgreSQL %s
    query = query.replace('?', '%s')

    results = []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, args)
                if query.strip().upper().startswith('SELECT'):
                    rows = cur.fetchall()
                    results = [dict(row) for row in rows]
                else:
                    conn.commit()
    except Exception as e:
        print(f"DATABASE ERROR: {e}")
        results = []

    if one:
        return results[0] if results else None
    return results