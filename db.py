import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL is not set in environment variables")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE,
                    password TEXT,
                    firstname TEXT,
                    lastname TEXT,
                    role TEXT
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id SERIAL PRIMARY KEY,
                    title TEXT,
                    author TEXT,
                    publisher TEXT,
                    image_url TEXT,
                    description TEXT,
                    barcode TEXT UNIQUE,
                    isbn TEXT UNIQUE,
                    quantity INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'Available'
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS loans (
                    id SERIAL PRIMARY KEY,
                    book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    issue_date DATE,
                    due_date DATE,
                    return_date DATE,
                    fine_amount REAL DEFAULT 0.0
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    sender_name TEXT,
                    content TEXT,
                    is_admin_reply INTEGER DEFAULT 0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # default admin
            cur.execute("SELECT id FROM users WHERE username = %s", ('admin',))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO users (username, password, firstname, lastname, role)
                    VALUES (%s, %s, %s, %s, %s)
                """, ('admin', 'admin123', 'System', 'Administrator', 'admin'))

        conn.commit()


def query_db(query, args=(), one=False):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, args)

                if cur.description:
                    rows = cur.fetchall()
                    result = [dict(r) for r in rows]
                else:
                    conn.commit()
                    result = []

    except Exception as e:
        print("DATABASE ERROR:", e)
        raise e   # 🔥 show real error in logs

    return result[0] if one and result else result