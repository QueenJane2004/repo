import os
import re
import random
import string
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
from functools import wraps
import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key_change_in_prod")

# Initialize the SQLite database
db.init_db()

# =========================
# CHATBOT RULES
# =========================
CHAT_RULES = [
    (r'\b(hi|hello|hey)\b',     "Hello! 👋 Ask me about books, borrowing, returns, or fines."),
    (r'\b(fine|overdue)\b',     "A ₱20 per day overdue fee applies after the due date."),
    (r'\b(borrow)\b',            "You can borrow books directly from the dashboard. Click 'Borrow' on any available book."),
    (r'\b(return)\b',           "Please return books at the library counter before or on the due date."),
    (r'\b(limit)\b',            "Members can borrow up to 5 books at a time."),
    (r'\b(due|deadline)\b',     "Books are due 10 days after borrowing. Check your borrowing history for exact dates."),
    (r'\b(history|records)\b',  "You can view your borrowing history by clicking 'History' in the top navigation."),
    (r'\b(available|stock)\b',  "Check the library collection below for available books. Green badge means available!"),
]

COMPILED_RULES = [(re.compile(p, re.IGNORECASE), r) for p, r in CHAT_RULES]

def rule_based_reply(msg):
    for pattern, response in COMPILED_RULES:
        if pattern.search(msg):
            return response
    return "I can help with borrowing, returns, fines, and book availability. What would you like to know?"

# =========================
# AUTH HELPERS
# =========================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            flash("Please log in to continue.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            flash("Please log in to continue.", "warning")
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash("Admin access required.", "danger")
            return redirect(url_for('user_dashboard'))
        return f(*args, **kwargs)
    return decorated

# =========================
# ROUTES
# =========================

@app.route('/')
def index():
    if session.get('user_id'):
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('user_dashboard'))
    return redirect(url_for('login'))

# ---------- AUTH ----------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        # Use '?' for SQLite placeholders
        user = db.query_db(
            "SELECT * FROM users WHERE username = ? AND password = ?",
            (username, password),
            one=True
        )

        if user:
            # Ensure session values exist to avoid KeyErrors
            session['user_id']   = user['id']
            session['firstname'] = user.get('firstname', 'User')
            session['lastname']  = user.get('lastname', '')
            session['role']      = user.get('role', 'user')

            if session['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('user_dashboard'))

        flash("Invalid username or password.", "danger")

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        firstname = request.form.get('firstname', '').strip()
        lastname  = request.form.get('lastname', '').strip()
        role      = request.form.get('role', 'user')
        username  = request.form.get('username', '').strip()
        password  = request.form.get('password', '').strip()

        if not all([firstname, lastname, username, password]):
            flash("All fields are required.", "warning")
            return render_template('register.html')

        existing = db.query_db("SELECT id FROM users WHERE username = ?", (username,), one=True)
        if existing:
            flash("Username already taken.", "warning")
            return render_template('register.html')

        db.query_db(
            "INSERT INTO users (username, password, firstname, lastname, role) VALUES (?, ?, ?, ?, ?)",
            (username, password, firstname, lastname, role)
        )
        flash("Account created! Please log in.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

# ---------- USER ----------

@app.route('/user')
@login_required
def user_dashboard():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC") or []
    total_fine = 0
    limit = 5

    try:
        # SQLite: use '?' and COALESCE
        result = db.query_db("""
            SELECT COALESCE(SUM(fine_amount), 0) AS total
            FROM loans
            WHERE user_id = ? AND return_date IS NULL
        """, (session['user_id'],), one=True)
        total_fine = float(result['total']) if result and result['total'] else 0
    except:
        total_fine = 0

    recommendations = []
    try:
        # SQLite uses RANDOM()
        recommendations = db.query_db("""
            SELECT * FROM books
            WHERE id NOT IN (
                SELECT book_id FROM loans WHERE user_id = ?
            )
            ORDER BY RANDOM() LIMIT 4
        """, (session['user_id'],)) or []
    except:
        recommendations = []

    return render_template(
        'user.html',
        books=books,
        total_fine=total_fine,
        limit=limit,
        recommendations=recommendations
    )

@app.route('/checkout/<int:book_id>', methods=['POST'])
@login_required
def checkout(book_id):
    book = db.query_db("SELECT * FROM books WHERE id = ?", (book_id,), one=True)

    if not book:
        flash("Book not found.", "danger")
        return redirect(url_for('user_dashboard'))

    if book['quantity'] <= 0:
        flash("This book is out of stock.", "warning")
        return redirect(url_for('user_dashboard'))

    active_loans = db.query_db(
        "SELECT COUNT(*) AS cnt FROM loans WHERE user_id = ? AND return_date IS NULL",
        (session['user_id'],), one=True
    )
    
    if active_loans and active_loans['cnt'] >= 5:
        flash("You have reached your borrowing limit.", "warning")
        return redirect(url_for('user_dashboard'))

    try:
        issue_date = datetime.now().strftime('%Y-%m-%d')
        due_date   = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d')

        db.query_db(
            "INSERT INTO loans (book_id, user_id, issue_date, due_date, fine_amount) VALUES (?, ?, ?, ?, 0)",
            (book_id, session['user_id'], issue_date, due_date)
        )
        db.query_db(
            "UPDATE books SET quantity = quantity - 1 WHERE id = ?",
            (book_id,)
        )
        flash(f"✅ '{book['title']}' borrowed successfully!", "success")
    except Exception as e:
        flash("Error during checkout.", "danger")

    return redirect(url_for('user_dashboard'))

# ---------- ADMIN ----------

@app.route('/admin')
@admin_required
def admin_dashboard():
    # Helper to get counts safely
    def get_count(q):
        res = db.query_db(q, one=True)
        return res['cnt'] if res else 0

    books_count    = get_count("SELECT COUNT(*) AS cnt FROM books")
    users_count    = get_count("SELECT COUNT(*) AS cnt FROM users")
    borrowed_count = get_count("SELECT COUNT(*) AS cnt FROM loans WHERE return_date IS NULL")
    
    trending_books = db.query_db("""
        SELECT b.title, COUNT(l.id) AS borrow_count
        FROM loans l
        JOIN books b ON b.id = l.book_id
        GROUP BY b.title
        ORDER BY borrow_count DESC
        LIMIT 10
    """) or []

    return render_template(
        'admin.html',
        books_count=books_count,
        users_count=users_count,
        borrowed_count=borrowed_count,
        trending_books=trending_books
    )

@app.route('/manage_books')
@admin_required
def manage_books():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC") or []
    return render_template('manage_books.html', books=books)

@app.route('/add_book', methods=['POST'])
@admin_required
def add_book():
    title = request.form.get('title', '').strip()
    author = request.form.get('author', '').strip()
    quantity = int(request.form.get('quantity', 1))

    if not title:
        flash("Title is required.", "warning")
        return redirect(url_for('manage_books'))

    barcode = 'B' + ''.join(random.choices(string.digits, k=6))
    
    db.query_db(
        "INSERT INTO books (title, author, barcode, quantity) VALUES (?, ?, ?, ?)",
        (title, author, barcode, quantity)
    )

    flash(f"✅ '{title}' added.", "success")
    return redirect(url_for('manage_books'))

@app.route('/transactions_log')
@login_required
def transactions_log():
    is_admin = session.get('role') == 'admin'

    if is_admin:
        # SQLite uses || for concatenation
        transactions = db.query_db("""
            SELECT
                l.id, l.issue_date, l.due_date, l.return_date, l.fine_amount,
                b.title AS book_title,
                u.firstname || ' ' || u.lastname AS user_name
            FROM loans l
            JOIN books b ON b.id = l.book_id
            JOIN users u ON u.id = l.user_id
            ORDER BY l.issue_date DESC
        """) or []
    else:
        transactions = db.query_db("""
            SELECT
                l.id, l.issue_date, l.due_date, l.return_date, l.fine_amount,
                b.title AS book_title
            FROM loans l
            JOIN books b ON b.id = l.book_id
            WHERE l.user_id = ?
            ORDER BY l.issue_date DESC
        """, (session['user_id'],)) or []

    return render_template('transactions_log.html', transactions=transactions, is_admin=is_admin)

@app.route('/ai_chat', methods=['POST'])
@login_required
def ai_chat():
    data = request.get_json()
    msg = data.get('message', '').strip()
    reply = rule_based_reply(msg)
    return jsonify({"reply": reply})

if __name__ == '__main__':
    app.run(debug=True)
