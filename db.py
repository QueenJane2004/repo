import os
import psycopg2
import psycopg2.extras

# Get the database URL from environment variable
DATABASE_URL = os.environ.get('DATABASE_URL')


def get_conn():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn


def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    # 1. Users Table
    cursor.execute('''
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
    cursor.execute('''
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
    cursor.execute('''
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            sender_name TEXT,
            content TEXT,
            is_admin_reply INTEGER DEFAULT 0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 5. Ensure default admin exists
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (username, password, firstname, lastname, role) VALUES (%s, %s, %s, %s, %s)",
            ('admin', 'admin123', 'System', 'Administrator', 'admin')
        )

    conn.commit()
    cursor.close()
    conn.close()


def query_db(query, args=(), one=False):
    # Convert SQLite ? placeholders to PostgreSQL %s
    query = query.replace('?', '%s')

    conn = get_conn()
    conn.autocommit = False
    results = []
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(query, args)
        if query.strip().upper().startswith('SELECT'):
            rows = cursor.fetchall()
            results = [dict(row) for row in rows]
        else:
            conn.commit()
            results = []
    except Exception as e:
        print(f"DATABASE ERROR: {e}")
        conn.rollback()
        results = []
    finally:
        cursor.close()
        conn.close()

    if one:
        return results[0] if results else None
    return results