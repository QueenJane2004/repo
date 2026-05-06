import os
import uuid
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
        flash("Registration successful!", "success")
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
    b_count = db.query_db("SELECT COUNT(*) as cnt FROM books", one=True)['cnt']
    u_count = db.query_db("SELECT COUNT(*) as cnt FROM users", one=True)['cnt']
    l_count = db.query_db("SELECT COUNT(*) as cnt FROM loans WHERE return_date IS NULL", one=True)['cnt']
    all_users = db.query_db("SELECT * FROM users ORDER BY id DESC LIMIT 8")
    trending = db.query_db("""
        SELECT b.title, COUNT(l.id) as borrow_count 
        FROM books b JOIN loans l ON b.id = l.book_id 
        GROUP BY b.id ORDER BY borrow_count DESC LIMIT 5
    """)
    return render_template('admin.html', books_count=b_count, users_count=u_count, borrowed_count=l_count, all_users=all_users, trending_books=trending)

@app.route('/manage_books')
@login_required
@admin_required
def manage_books():
    # Use db.query_db (not query_db)
    books = db.query_db("SELECT * FROM books ORDER BY id DESC")
    return render_template('manage_books.html', books=books)

@app.route('/view_users')
@login_required
@admin_required
def view_users():
    users = db.query_db("SELECT * FROM users ORDER BY id DESC")
    return render_template('view_users.html', all_users=users)

@app.route('/transactions_log')
@login_required
@admin_required
def transactions_log():
    logs = db.query_db("""
        SELECT l.*, b.title as book_title, u.username 
        FROM loans l JOIN books b ON b.id = l.book_id 
        JOIN users u ON u.id = l.user_id ORDER BY l.id DESC""")
    return render_template('activity_logs.html', logs=logs)

# --- ACTION ROUTES ---

@app.route('/add_book', methods=['POST'])
@login_required
@admin_required
def add_book():
    title = request.form.get('title')
    author = request.form.get('author')
    publisher = request.form.get('publisher')
    description = request.form.get('description')
    quantity = request.form.get('quantity', 1)
    
    # Critical Fix: Generate barcode and image_url since DB needs them
    barcode = str(uuid.uuid4().hex[:8]).upper()
    image_url = None 

    db.query_db("""
        INSERT INTO books (title, author, publisher, description, image_url, barcode, quantity) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (title, author, publisher, description, image_url, barcode, quantity))
    
    flash(f'Added "{title}" successfully!', 'success')
    return redirect(url_for('manage_books'))

@app.route('/delete_book/<int:book_id>', methods=['POST'])
@login_required
@admin_required
def delete_book(book_id):
    db.query_db("DELETE FROM books WHERE id = ?", (book_id,))
    flash("Book deleted.", "success")
    return redirect(url_for('manage_books'))

@app.route('/update_book_qty', methods=['POST'])
@login_required
@admin_required
def update_book_qty():
    data = request.get_json()
    db.query_db("UPDATE books SET quantity = ? WHERE id = ?", (data.get('quantity'), data.get('book_id')))
    return jsonify({"status": "success"})

# --- USER ROUTES ---

@app.route('/user')
@login_required
def user_dashboard():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC")
    recs = db.query_db("SELECT * FROM books ORDER BY RANDOM() LIMIT 4")
    return render_template('user.html', books=books, recommendations=recs)

if __name__ == '__main__':
    app.run(debug=True)
