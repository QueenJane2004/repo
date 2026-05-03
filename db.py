import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL missing")

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        sslmode="require"
    )


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
                    quantity INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'Available'
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS loans (
                    id SERIAL PRIMARY KEY,
                    book_id INTEGER,
                    user_id INTEGER,
                    issue_date DATE,
                    due_date DATE,
                    return_date DATE,
                    fine_amount REAL DEFAULT 0
                )
            """)

        conn.commit()


def query_db(query, args=(), one=False):
    query = query.replace("?", "%s")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, args)

                if query.strip().upper().startswith("SELECT"):
                    result = cur.fetchall()
                else:
                    conn.commit()
                    result = []

    except Exception as e:
        print("DB ERROR:", e)
        return None if one else []

    return result[0] if one and result else result