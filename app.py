import os
import re
import random
import string
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key_2026")

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
    (r'\b(due|deadline)\b',     "Books are due 10 days after borrowing. Check your history for dates."),
]
COMPILED_RULES = [(re.compile(p, re.IGNORECASE), r) for p, r in CHAT_RULES]

def rule_based_reply(msg):
    for pattern, response in COMPILED_RULES:
        if pattern.search(msg): return response
    return "I can help with borrowing, returns, and fines. What's on your mind?"

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
        return redirect(url_for('admin_dashboard' if session.get('role') == 'admin' else 'user_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'): return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        user = db.query_db("SELECT * FROM users WHERE username = %s", (username,), one=True)
        
        # Verify using secure hashing
        if user and check_password_hash(user['password'], password):
            session.update({
                'user_id': user['id'],
                'firstname': user.get('firstname', 'User'),
                'lastname': user.get('lastname', ''),
                'role': user.get('role', 'Student').lower()
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
        role      = request.form.get('role', 'Student')

        if not all([firstname, lastname, username, password]):
            flash("All fields are required.", "warning")
            return render_template('register.html')

        if db.query_db("SELECT id FROM users WHERE username = %s", (username,), one=True):
            flash("Username already taken.", "warning")
        else:
            hashed_pw = generate_password_hash(password)
            db.query_db(
                "INSERT INTO users (username, password, firstname, lastname, role) VALUES (%s, %s, %s, %s, %s)",
                (username, hashed_pw, firstname, lastname, role)
            )
            flash("Account created! Please log in.", "success")
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

# ---------- USER DASHBOARD ----------

@app.route('/user')
@login_required
def user_dashboard():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC") or []
    # Use RAND() for MySQL, RANDOM() for SQLite
    recs = db.query_db("SELECT * FROM books ORDER BY RAND() LIMIT 4") or []
    
    result = db.query_db("SELECT SUM(fine_amount) as total FROM loans WHERE user_id = %s AND return_date IS NULL", 
                         (session['user_id'],), one=True)
    total_fine = result['total'] if result and result['total'] else 0

    return render_template('user.html', books=books, total_fine=total_fine, recommendations=recs)

@app.route('/checkout/<int:book_id>', methods=['POST'])
@login_required
def checkout(book_id):
    book = db.query_db("SELECT * FROM books WHERE id = %s", (book_id,), one=True)
    if not book or book['quantity'] <= 0:
        flash("Book unavailable.", "warning")
        return redirect(url_for('user_dashboard'))

    active = db.query_db("SELECT COUNT(*) as cnt FROM loans WHERE user_id = %s AND return_date IS NULL", 
                         (session['user_id'],), one=True)
    if active['cnt'] >= 5:
        flash("Limit reached (5 books).", "warning")
    else:
        due = (datetime.now() + timedelta(days=10)).date()
        db.query_db("INSERT INTO loans (book_id, user_id, issue_date, due_date, fine_amount) VALUES (%s, %s, CURDATE(), %s, 0)",
                    (book_id, session['user_id'], due))
        db.query_db("UPDATE books SET quantity = quantity - 1 WHERE id = %s", (book_id,))
        flash(f"Borrowed '{book['title']}'. Due: {due}", "success")
    
    return redirect(url_for('user_dashboard'))

# ---------- ADMIN DASHBOARD ----------

@app.route('/admin')
@admin_required
def admin_dashboard():
    b_cnt = db.query_db("SELECT COUNT(*) as cnt FROM books", one=True)
    u_cnt = db.query_db("SELECT COUNT(*) as cnt FROM users", one=True)
    l_cnt = db.query_db("SELECT COUNT(*) as cnt FROM loans WHERE return_date IS NULL", one=True)
    all_users = db.query_db("SELECT * FROM users ORDER BY id DESC LIMIT 10")
    trending = db.query_db("""SELECT b.title, COUNT(l.id) as borrow_count FROM loans l 
                              JOIN books b ON b.id = l.book_id GROUP BY b.title ORDER BY borrow_count DESC LIMIT 5""")
    
    return render_template('admin.html', books_count=b_cnt['cnt'], users_count=u_cnt['cnt'], 
                           borrowed_count=l_cnt['cnt'], trending_books=trending, all_users=all_users)

@app.route('/manage_books')
@admin_required
def manage_books():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC")
    return render_template('manage_books.html', books=books)

@app.route('/add_book', methods=['POST'])
@admin_required
def add_book():
    title = request.form.get('title', '').strip()
    author = request.form.get('author', '').strip()
    publisher = request.form.get('publisher', '').strip()
    qty = int(request.form.get('quantity', 1))
    
    barcode = 'B' + ''.join(random.choices(string.digits, k=6))
    img_url = '/static/uploads/books/default_cover.png'
    
    file = request.files.get('book_image')
    if file and file.filename:
        os.makedirs('static/uploads/books', exist_ok=True)
        file_path = os.path.join('static/uploads/books', file.filename)
        file.save(file_path)
        img_url = '/' + file_path

    db.query_db("INSERT INTO books (title, author, publisher, image_url, barcode, quantity, status) VALUES (%s,%s,%s,%s,%s,%s,'Available')",
                (title, author, publisher, img_url, barcode, qty))
    flash(f"Added {title}", "success")
    return redirect(url_for('manage_books'))

@app.route('/delete_book/<int:book_id>', methods=['POST'])
@admin_required
def delete_book(book_id):
    db.query_db("DELETE FROM books WHERE id = %s", (book_id,))
    flash("Book deleted.", "success")
    return redirect(url_for('manage_books'))

@app.route('/transactions_log')
@login_required
def transactions_log():
    is_admin = session.get('role') == 'admin'
    # Use CONCAT for MySQL, or || for SQLite
    query = """SELECT l.*, b.title as book_title, b.author as book_author, 
               CONCAT(u.firstname, ' ', u.lastname) as user_name FROM loans l 
               JOIN books b ON b.id = l.book_id JOIN users u ON u.id = l.user_id """
    
    if is_admin:
        trans = db.query_db(query + "ORDER BY l.id DESC")
    else:
        trans = db.query_db(query + "WHERE l.user_id = %s ORDER BY l.id DESC", (session['user_id'],))
    
    return render_template('transactions_log.html', transactions=trans, is_admin=is_admin)

@app.route('/return_book/<int:loan_id>', methods=['POST'])
@admin_required
def return_book(loan_id):
    loan = db.query_db("SELECT * FROM loans WHERE id = %s", (loan_id,), one=True)
    if loan and not loan['return_date']:
        due = loan['due_date']
        if isinstance(due, str): due = datetime.strptime(due, '%Y-%m-%d').date()
        
        fine = max(0, (datetime.now().date() - due).days * 20)
        db.query_db("UPDATE loans SET return_date=CURDATE(), fine_amount=%s WHERE id=%s", (fine, loan_id))
        db.query_db("UPDATE books SET quantity = quantity + 1 WHERE id=%s", (loan['book_id'],))
        flash("Book returned successfully.", "success")
    return redirect(url_for('transactions_log'))

@app.route('/view_users')
@admin_required
def view_users():
    users = db.query_db("SELECT * FROM users ORDER BY id DESC")
    return render_template('view_users.html', all_users=users)

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    if user_id != session['user_id']:
        db.query_db("DELETE FROM users WHERE id = %s", (user_id,))
        flash("User deleted.", "success")
    return redirect(url_for('view_users'))

@app.route('/ai_chat', methods=['POST'])
def ai_chat():
    data = request.get_json()
    reply = rule_based_reply(data.get('message', ''))
    return jsonify({"reply": reply})

if __name__ == '__main__':
    app.run(debug=True)
