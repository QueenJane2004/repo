import os
import re
import random
import string
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
from functools import wraps
import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123")

# Initialize database
db.init_db()

# --- ACCESS CONTROL ---
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

# --- AUTH ROUTES ---
@app.route('/')
def index():
    if not session.get('user_id'): return redirect(url_for('login'))
    return redirect(url_for('admin_dashboard' if session['role'] == 'admin' else 'user_dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u, p = request.form.get('username'), request.form.get('password')
        user = db.query_db("SELECT * FROM users WHERE username = ? AND password = ?", (u, p), one=True)
        if user:
            session.update({'user_id': user['id'], 'role': user['role'], 'firstname': user['firstname']})
            return redirect(url_for('index'))
        flash("Invalid username or password.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        f, l, u, p = request.form.get('firstname'), request.form.get('lastname'), request.form.get('username'), request.form.get('password')
        db.query_db("INSERT INTO users (username, password, firstname, lastname, role) VALUES (?, ?, ?, ?, 'user')", (u, p, f, l))
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- ADMIN ROUTES ---
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    # Counters
    b_count = db.query_db("SELECT COUNT(*) as cnt FROM books", one=True)['cnt']
    u_count = db.query_db("SELECT COUNT(*) as cnt FROM users", one=True)['cnt']
    l_count = db.query_db("SELECT COUNT(*) as cnt FROM loans WHERE return_date IS NULL", one=True)['cnt']
    
    # Data for dashboard tables
    all_users = db.query_db("SELECT * FROM users ORDER BY id DESC LIMIT 8")
    trending = db.query_db("""
        SELECT b.title, COUNT(l.id) as borrow_count 
        FROM books b JOIN loans l ON b.id = l.book_id 
        GROUP BY b.id ORDER BY borrow_count DESC LIMIT 5
    """)
    
    return render_template('admin.html', 
                           books_count=b_count, 
                           users_count=u_count, 
                           borrowed_count=l_count, 
                           all_users=all_users, 
                           trending_books=trending)

@app.route('/manage_books')
@login_required
@admin_required
def manage_books():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC")
    return render_template('manage_books.html', books=books)

@app.route('/add_book', methods=['POST'])
@login_required
@admin_required
def add_book():
    t, a, q = request.form.get('title'), request.form.get('author'), request.form.get('quantity')
    barcode = 'B' + ''.join(random.choices(string.digits, k=6))
    db.query_db("INSERT INTO books (title, author, barcode, quantity) VALUES (?, ?, ?, ?)", (t, a, barcode, q))
    flash("Book added successfully.", "success")
    return redirect(url_for('manage_books'))

@app.route('/view_users')
@login_required
@admin_required
def view_users():
    users = db.query_db("SELECT * FROM users ORDER BY id DESC")
    return render_template('view_users.html', all_users=users)

@app.route('/transactions')
@login_required
def transactions_log():
    if session['role'] == 'admin':
        tx = db.query_db("""
            SELECT l.*, b.title as book_title, u.username 
            FROM loans l JOIN books b ON b.id = l.book_id 
            JOIN users u ON u.id = l.user_id ORDER BY l.id DESC""")
    else:
        tx = db.query_db("SELECT l.*, b.title as book_title FROM loans l JOIN books b ON b.id = l.book_id WHERE l.user_id = ?", (session['user_id'],))
    return render_template('transactions_log.html', transactions=tx, is_admin=(session['role'] == 'admin'))

# --- USER ROUTES ---
@app.route('/user')
@login_required
def user_dashboard():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC")
    recs = db.query_db("SELECT * FROM books ORDER BY RANDOM() LIMIT 4")
    return render_template('user.html', books=books, recommendations=recs)

@app.route('/borrow/<int:book_id>', methods=['POST'])
@login_required
def checkout(book_id):
    book = db.query_db("SELECT * FROM books WHERE id = ?", (book_id,), one=True)
    if book and book['quantity'] > 0:
        now = datetime.now().strftime('%Y-%m-%d')
        due = (datetime.now() + timedelta(days=14)).strftime('%Y-%m-%d')
        db.query_db("INSERT INTO loans (book_id, user_id, issue_date, due_date) VALUES (?, ?, ?, ?)", (book_id, session['user_id'], now, due))
        db.query_db("UPDATE books SET quantity = quantity - 1 WHERE id = ?", (book_id,))
        flash(f"Successfully borrowed {book['title']}!", "success")
    else:
        flash("Book unavailable.", "warning")
    return redirect(url_for('user_dashboard'))

@app.route('/return/<int:loan_id>', methods=['POST'])
@login_required
@admin_required
def return_book(loan_id):
    loan = db.query_db("SELECT * FROM loans WHERE id = ?", (loan_id,), one=True)
    if loan:
        db.query_db("UPDATE loans SET return_date = ? WHERE id = ?", (datetime.now().strftime('%Y-%m-%d'), loan_id))
        db.query_db("UPDATE books SET quantity = quantity + 1 WHERE id = ?", (loan['book_id'],))
        flash("Book returned.", "success")
    return redirect(url_for('transactions_log'))

if __name__ == '__main__':
    app.run(debug=True)
