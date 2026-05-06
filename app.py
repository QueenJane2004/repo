import os
import re
import random
import string
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
from functools import wraps
import db

app = Flask(__name__)
# Fallback secret key for development
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key_123")

# Initialize DB on start
db.init_db()

# =========================
# CHATBOT RULES
# =========================
CHAT_RULES = [
    (r'\b(hi|hello|hey)\b',     "Hello! 👋 Ask me about books, borrowing, or fines."),
    (r'\b(fine|overdue)\b',     "A ₱20 per day overdue fee applies after the due date."),
    (r'\b(borrow)\b',           "Click 'Borrow' on any available book in your dashboard."),
    (r'\b(return)\b',           "Please return books at the library counter."),
    (r'\b(limit)\b',            "Members can borrow up to 5 books at a time."),
]

COMPILED_RULES = [(re.compile(p, re.IGNORECASE), r) for p, r in CHAT_RULES]

def rule_based_reply(msg):
    for pattern, response in COMPILED_RULES:
        if pattern.search(msg):
            return response
    return "I can help with borrowing and fines. What's on your mind?"

# =========================
# AUTH HELPERS
# =========================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            flash("Please log in first.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id') or session.get('role') != 'admin':
            flash("Admin access required.", "danger")
            return redirect(url_for('index'))
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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        # SQLite Placeholder: ?
        user = db.query_db("SELECT * FROM users WHERE username = ? AND password = ?", (username, password), one=True)

        if user:
            session.update({
                'user_id': user['id'],
                'firstname': user.get('firstname', 'User'),
                'role': user.get('role', 'user')
            })
            return redirect(url_for('index'))
        
        flash("Invalid credentials.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = (
            request.form.get('username'),
            request.form.get('password'),
            request.form.get('firstname'),
            request.form.get('lastname'),
            request.form.get('role', 'user')
        )
        
        if db.query_db("SELECT id FROM users WHERE username = ?", (data[0],), one=True):
            flash("Username taken.", "warning")
        else:
            db.query_db("INSERT INTO users (username, password, firstname, lastname, role) VALUES (?,?,?,?,?)", data)
            flash("Registered! Please log in.", "success")
            return redirect(url_for('login'))
            
    return render_template('register.html')

@app.route('/user')
@login_required
def user_dashboard():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC") or []
    
    # Fine Calculation
    fine_res = db.query_db("SELECT SUM(fine_amount) as total FROM loans WHERE user_id = ? AND return_date IS NULL", (session['user_id'],), one=True)
    total_fine = fine_res['total'] if fine_res and fine_res['total'] else 0
    
    # Recommendations using SQLite RANDOM()
    recs = db.query_db("SELECT * FROM books WHERE id NOT IN (SELECT book_id FROM loans WHERE user_id = ?) ORDER BY RANDOM() LIMIT 4", (session['user_id'],)) or []
    
    return render_template('user.html', books=books, total_fine=total_fine, recommendations=recs)

@app.route('/checkout/<int:book_id>', methods=['POST'])
@login_required
def checkout(book_id):
    book = db.query_db("SELECT * FROM books WHERE id = ?", (book_id,), one=True)
    
    if not book or book['quantity'] <= 0:
        flash("Book unavailable.", "danger")
        return redirect(url_for('user_dashboard'))

    # Check limit
    count = db.query_db("SELECT COUNT(*) as cnt FROM loans WHERE user_id = ? AND return_date IS NULL", (session['user_id'],), one=True)
    if count and count['cnt'] >= 5:
        flash("Limit reached (5 books).", "warning")
        return redirect(url_for('user_dashboard'))

    # Dates as strings for SQLite
    now = datetime.now()
    issue = now.strftime('%Y-%m-%d')
    due = (now + timedelta(days=10)).strftime('%Y-%m-%d')

    db.query_db("INSERT INTO loans (book_id, user_id, issue_date, due_date) VALUES (?, ?, ?, ?)", (book_id, session['user_id'], issue, due))
    db.query_db("UPDATE books SET quantity = quantity - 1 WHERE id = ?", (book_id,))
    
    flash(f"Borrowed '{book['title']}'!", "success")
    return redirect(url_for('user_dashboard'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    b_count = db.query_db("SELECT COUNT(*) as cnt FROM books", one=True)['cnt']
    u_count = db.query_db("SELECT COUNT(*) as cnt FROM users", one=True)['cnt']
    l_count = db.query_db("SELECT COUNT(*) as cnt FROM loans WHERE return_date IS NULL", one=True)['cnt']
    
    return render_template('admin.html', books_count=b_count, users_count=u_count, borrowed_count=l_count)

@app.route('/transactions_log')
@login_required
def transactions_log():
    if session['role'] == 'admin':
        # SQLite String Concatenation: ||
        sql = """SELECT l.*, b.title as book_title, u.firstname || ' ' || u.lastname as user_name 
                 FROM loans l JOIN books b ON b.id = l.book_id JOIN users u ON u.id = l.user_id 
                 ORDER BY l.issue_date DESC"""
        tx = db.query_db(sql)
    else:
        tx = db.query_db("SELECT l.*, b.title as book_title FROM loans l JOIN books b ON b.id = l.book_id WHERE l.user_id = ? ORDER BY l.issue_date DESC", (session['user_id'],))
    
    return render_template('transactions_log.html', transactions=tx or [], is_admin=(session['role'] == 'admin'))

@app.route('/ai_chat', methods=['POST'])
@login_required
def ai_chat():
    msg = request.get_json().get('message', '')
    return jsonify({"reply": rule_based_reply(msg)})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
