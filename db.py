import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL environment variable is missing.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    firstname TEXT,
                    lastname TEXT,
                    role TEXT DEFAULT 'user'
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    author TEXT,
                    publisher TEXT,
                    image_url TEXT,
                    description TEXT,
                    barcode TEXT UNIQUE,
                    isbn TEXT,
                    quantity INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'Available'
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS loans (
                    id SERIAL PRIMARY KEY,
                    book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    issue_date DATE NOT NULL,
                    due_date DATE NOT NULL,
                    return_date DATE,
                    fine_amount REAL DEFAULT 0
                )
            """)

            # FIX: messages table was missing — caused 500 on admin dashboard
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("ALTER TABLE books ADD COLUMN IF NOT EXISTS isbn TEXT;")
            cur.execute("ALTER TABLE loans ADD COLUMN IF NOT EXISTS fine_amount REAL DEFAULT 0;")

        conn.commit()


def query_db(query, args=(), one=False):
    query = query.replace("?", "%s")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, args)
                if query.strip().upper().startswith("SELECT"):
                    result = cur.fetchall()
                    return result[0] if one and result else (None if one else result)
                else:
                    conn.commit()
                    return None
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"DB ERROR: {e}")
        return None if one else []