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

# Initialize database tables on startup
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
    (r'\b(due|deadline)\b',     "Books are due 10 days after borrowing."),
    (r'\b(available|stock)\b',  "Check the library collection below for available books."),
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
        return redirect(url_for('admin_dashboard') if session.get('role') == 'admin' else url_for('user_dashboard'))
    return redirect(url_for('login'))

# ---------- AUTH ----------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = db.query_db("SELECT * FROM users WHERE username = ? AND password = ?", (username, password), one=True)

        if user:
            session.update({
                'user_id': user['id'],
                'firstname': user.get('firstname', 'User'),
                'lastname': user.get('lastname', ''),
                'role': user.get('role', 'user')
            })
            return redirect(url_for('index'))

        flash("Invalid username or password.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        firstname = request.form.get('firstname', '').strip()
        lastname  = request.form.get('lastname', '').strip()
        username  = request.form.get('username', '').strip()
        password  = request.form.get('password', '').strip()

        if db.query_db("SELECT id FROM users WHERE username = ?", (username,), one=True):
            flash("Username already taken.", "warning")
        else:
            db.query_db("INSERT INTO users (username, password, firstname, lastname, role) VALUES (?, ?, ?, ?, ?)",
                        (username, password, firstname, lastname, 'user'))
            flash("Account created! Please log in.", "success")
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for('login'))

# ---------- USER ROUTES ----------

@app.route('/user')
@login_required
def user_dashboard():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC") or []
    
    fine_res = db.query_db("SELECT SUM(fine_amount) as total FROM loans WHERE user_id = ? AND return_date IS NULL", (session['user_id'],), one=True)
    total_fine = fine_res['total'] if fine_res and fine_res['total'] else 0
    
    recs = db.query_db("SELECT * FROM books WHERE id NOT IN (SELECT book_id FROM loans WHERE user_id = ?) ORDER BY RANDOM() LIMIT 4", (session['user_id'],)) or []
    
    return render_template('user.html', books=books, total_fine=total_fine, recommendations=recs)

@app.route('/checkout/<int:book_id>', methods=['POST'])
@login_required
def checkout(book_id):
    book = db.query_db("SELECT * FROM books WHERE id = ?", (book_id,), one=True)
    
    if not book or book['quantity'] <= 0:
        flash("Out of stock.", "danger")
        return redirect(url_for('user_dashboard'))

    # SQLite dates as strings
    now = datetime.now()
    issue = now.strftime('%Y-%m-%d')
    due = (now + timedelta(days=10)).strftime('%Y-%m-%d')

    db.query_db("INSERT INTO loans (book_id, user_id, issue_date, due_date, fine_amount) VALUES (?, ?, ?, ?, 0)", 
                (book_id, session['user_id'], issue, due))
    db.query_db("UPDATE books SET quantity = quantity - 1 WHERE id = ?", (book_id,))
    
    flash(f"Borrowed '{book['title']}' successfully!", "success")
    return redirect(url_for('user_dashboard'))

# ---------- ADMIN ROUTES ----------

@app.route('/admin')
@admin_required
def admin_dashboard():
    def count(q):
        res = db.query_db(q, one=True)
        return res['cnt'] if res else 0

    return render_template('admin.html', 
        books_count=count("SELECT COUNT(*) as cnt FROM books"),
        users_count=count("SELECT COUNT(*) as cnt FROM users"),
        borrowed_count=count("SELECT COUNT(*) as cnt FROM loans WHERE return_date IS NULL")
    )

@app.route('/manage_books')
@admin_required
def manage_books():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC") or []
    return render_template('manage_books.html', books=books)

@app.route('/add_book', methods=['POST'])
@admin_required
def add_book():
    title = request.form.get('title')
    author = request.form.get('author')
    qty = request.form.get('quantity', 1)
    barcode = 'B' + ''.join(random.choices(string.digits, k=6))
    
    db.query_db("INSERT INTO books (title, author, barcode, quantity) VALUES (?, ?, ?, ?)", (title, author, barcode, qty))
    flash("Book added!", "success")
    return redirect(url_for('manage_books'))

@app.route('/delete_book/<int:book_id>', methods=['POST'])
@admin_required
def delete_book(book_id):
    db.query_db("DELETE FROM books WHERE id = ?", (book_id,))
    flash("Book deleted.", "success")
    return redirect(url_for('manage_books'))

@app.route('/view_users')
@admin_required
def view_users():
    users = db.query_db("SELECT * FROM users ORDER BY id DESC") or []
    return render_template('view_users.html', all_users=users)

@app.route('/return_book/<int:loan_id>', methods=['POST'])
@admin_required
def return_book(loan_id):
    loan = db.query_db("SELECT * FROM loans WHERE id = ?", (loan_id,), one=True)
    if loan:
        today = datetime.now().strftime('%Y-%m-%d')
        db.query_db("UPDATE loans SET return_date = ? WHERE id = ?", (today, loan_id))
        db.query_db("UPDATE books SET quantity = quantity + 1 WHERE id = ?", (loan['book_id'],))
        flash("Book returned.", "success")
    return redirect(url_for('transactions_log'))

@app.route('/transactions_log')
@login_required
def transactions_log():
    is_admin = session.get('role') == 'admin'
    if is_admin:
        # SQLite uses || for concatenation
        tx = db.query_db("""
            SELECT l.*, b.title as book_title, u.firstname || ' ' || u.lastname as user_name 
            FROM loans l JOIN books b ON b.id = l.book_id JOIN users u ON u.id = l.user_id 
            ORDER BY l.issue_date DESC""")
    else:
        tx = db.query_db("SELECT l.*, b.title as book_title FROM loans l JOIN books b ON b.id = l.book_id WHERE l.user_id = ? ORDER BY l.issue_date DESC", (session['user_id'],))
    
    return render_template('transactions_log.html', transactions=tx or [], is_admin=is_admin)

@app.route('/ai_chat', methods=['POST'])
@login_required
def ai_chat():
    data = request.get_json()
    msg = data.get('message', '')
    return jsonify({"reply": rule_based_reply(msg)})

if __name__ == '__main__':
    app.run(debug=True)
