import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename
import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123")

# Upload config
UPLOAD_FOLDER = 'static/uploads/books'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

db.init_db()

# ================= ACCESS CONTROL =================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("Unauthorized access.", "danger")
            return redirect(url_for('user_dashboard'))
        return f(*args, **kwargs)
    return decorated

# ================= AUTH =================
@app.route('/')
def index():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    return redirect(url_for('admin_dashboard' if session['role']=='admin' else 'user_dashboard'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')

        user = db.query_db("SELECT * FROM users WHERE username=?", [u], one=True)
        if user and user['password'] == p:
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['firstname'] = user['firstname']
            return redirect(url_for('admin_dashboard' if user['role']=='admin' else 'user_dashboard'))

        flash("Invalid login", "danger")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ================= ADMIN DASHBOARD =================
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    b_count = db.query_db("SELECT COUNT(*) as count FROM books", one=True)['count']
    u_count = db.query_db("SELECT COUNT(*) as count FROM users WHERE role='user'", one=True)['count']
    l_count = db.query_db("SELECT COUNT(*) as count FROM loans WHERE return_date IS NULL", one=True)['count']

    all_users = db.query_db("SELECT * FROM users ORDER BY id DESC")

    trending = db.query_db("""
        SELECT b.id, b.title, b.author, COUNT(l.id) as borrow_count
        FROM books b
        LEFT JOIN loans l ON l.book_id = b.id
        GROUP BY b.id
        ORDER BY borrow_count DESC
        LIMIT 5
    """)

    recent_activity = db.query_db("""
        SELECT l.*, b.title as book_title, u.username
        FROM loans l
        JOIN books b ON b.id = l.book_id
        JOIN users u ON u.id = l.user_id
        ORDER BY l.id DESC
        LIMIT 10
    """)

    now = datetime.today().strftime('%Y-%m-%d')

    return render_template(
        'admin_dashboard.html',
        books_count=b_count,
        users_count=u_count,
        borrowed_count=l_count,
        all_users=all_users or [],
        trending_books=trending or [],
        recent_activity=recent_activity or [],
        now=now
    )

# ================= RETURNED BOOKS (NEW) =================
@app.route('/returned_books')
@login_required
@admin_required
def returned_books():
    loans = db.query_db("""
        SELECT l.*, b.title as book_title, b.image_url, u.username
        FROM loans l
        JOIN books b ON b.id = l.book_id
        JOIN users u ON u.id = l.user_id
        WHERE l.return_date IS NOT NULL
        ORDER BY l.return_date DESC
    """) or []

    total_returned = len(loans)
    with_fine_count = sum(1 for l in loans if (l['fine_amount'] or 0) > 0)
    on_time_count = total_returned - with_fine_count
    total_fines_collected = sum((l['fine_amount'] or 0) for l in loans)

    return render_template(
        'return.html',
        returned_loans=loans,
        total_returned=total_returned,
        on_time_count=on_time_count,
        with_fine_count=with_fine_count,
        total_fines_collected=total_fines_collected
    )

# ================= BORROW / RETURN =================
@app.route('/borrow/return')
@login_required
def borrow_return():
    user_id = session['user_id']
    is_admin = session.get('role') == 'admin'
    today = datetime.today()
    now = today.strftime('%Y-%m-%d')

    if is_admin:
        active_loans = db.query_db("""
            SELECT l.*, b.title as book_title, u.username
            FROM loans l
            JOIN books b ON b.id = l.book_id
            JOIN users u ON u.id = l.user_id
            WHERE l.return_date IS NULL
        """) or []

        returned_loans = db.query_db("""
            SELECT l.*, b.title as book_title, u.username
            FROM loans l
            JOIN books b ON b.id = l.book_id
            JOIN users u ON u.id = l.user_id
            WHERE l.return_date IS NOT NULL
        """) or []

    else:
        active_loans = db.query_db("""
            SELECT l.*, b.title as book_title
            FROM loans l
            JOIN books b ON b.id = l.book_id
            WHERE l.user_id=? AND l.return_date IS NULL
        """,[user_id]) or []

        returned_loans = db.query_db("""
            SELECT l.*, b.title as book_title
            FROM loans l
            JOIN books b ON b.id = l.book_id
            WHERE l.user_id=? AND l.return_date IS NOT NULL
        """,[user_id]) or []

    return render_template(
        'borrow_return.html',
        active_loans=active_loans,
        returned_loans=returned_loans,
        now=now
    )

# ================= USER DASHBOARD =================
@app.route('/user')
@login_required
def user_dashboard():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))

    books = db.query_db("SELECT * FROM books") or []
    recs  = db.query_db("SELECT * FROM books ORDER BY RANDOM() LIMIT 4") or []

    return render_template('user.html', books=books, recommendations=recs)

# ================= RUN =================
if __name__ == '__main__':
    app.run(debug=True)