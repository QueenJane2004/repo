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
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_key_123")

# Initialize DB on startup
db.init_db()

# =========================
# CHATBOT LOGIC
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
# AUTH DECORATORS
# =========================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
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
    if not session.get('user_id'): return redirect(url_for('login'))
    return redirect(url_for('admin_dashboard' if session.get('role') == 'admin' else 'user_dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = db.query_db("SELECT * FROM users WHERE username = %s", (username,), one=True)
        
        if user and check_password_hash(user['password'], password):
            session.update({'user_id': user['id'], 'firstname': user['firstname'], 'role': user['role']})
            return redirect(url_for('index'))
        flash("Invalid credentials.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fn, ln = request.form.get('firstname'), request.form.get('lastname')
        un, pw = request.form.get('username'), request.form.get('password')
        role = request.form.get('role', 'Student')

        if db.query_db("SELECT id FROM users WHERE username = %s", (un,), one=True):
            flash("Username exists.", "warning")
        else:
            hashed_pw = generate_password_hash(pw)
            db.query_db("INSERT INTO users (username, password, firstname, lastname, role) VALUES (%s,%s,%s,%s,%s)",
                        (un, hashed_pw, fn, ln, role))
            flash("Registration successful! Login now.", "success")
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------- USER DASHBOARD ----------

@app.route('/user')
@login_required
def user_dashboard():
    books = db.query_db("SELECT * FROM books WHERE quantity > 0") or []
    # MySQL uses RAND(), SQLite/Postgres uses RANDOM()
    recs = db.query_db("SELECT * FROM books ORDER BY RAND() LIMIT 4") or []
    fine_res = db.query_db("SELECT SUM(fine_amount) as total FROM loans WHERE user_id=%s AND return_date IS NULL", 
                           (session['user_id'],), one=True)
    return render_template('user.html', books=books, recommendations=recs, total_fine=fine_res['total'] or 0)

@app.route('/checkout/<int:book_id>', methods=['POST'])
@login_required
def checkout(book_id):
    active = db.query_db("SELECT COUNT(*) as cnt FROM loans WHERE user_id=%s AND return_date IS NULL", 
                         (session['user_id'],), one=True)
    if active['cnt'] >= 5:
        flash("Limit reached (5 books).", "warning")
    else:
        due = (datetime.now() + timedelta(days=10)).date()
        db.query_db("INSERT INTO loans (book_id, user_id, issue_date, due_date, fine_amount) VALUES (%s,%s,CURDATE(),%s,0)",
                    (book_id, session['user_id'], due))
        db.query_db("UPDATE books SET quantity = quantity - 1 WHERE id = %s", (book_id,))
        flash("Book borrowed!", "success")
    return redirect(url_for('user_dashboard'))

# ---------- ADMIN DASHBOARD ----------

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    b_cnt = db.query_db("SELECT COUNT(*) as cnt FROM books", one=True)
    u_cnt = db.query_db("SELECT COUNT(*) as cnt FROM users", one=True)
    l_cnt = db.query_db("SELECT COUNT(*) as cnt FROM loans WHERE return_date IS NULL", one=True)
    users = db.query_db("SELECT * FROM users ORDER BY id DESC LIMIT 8")
    trending = db.query_db("""SELECT b.title, COUNT(l.id) as borrow_count FROM loans l 
                              JOIN books b ON b.id = l.book_id GROUP BY b.id ORDER BY borrow_count DESC LIMIT 5""")
    return render_template('admin.html', books_count=b_cnt['cnt'], users_count=u_cnt['cnt'], 
                           borrowed_count=l_cnt['cnt'], all_users=users, trending_books=trending)

@app.route('/transactions_log')
@login_required
def transactions_log():
    is_admin = session.get('role') == 'admin'
    query = """SELECT l.*, b.title as book_title, b.author as book_author, 
               CONCAT(u.firstname, ' ', u.lastname) as user_name FROM loans l 
               JOIN books b ON b.id = l.book_id JOIN users u ON u.id = l.user_id """
    if is_admin:
        trans = db.query_db(query + "ORDER BY l.id DESC")
    else:
        trans = db.query_db(query + "WHERE l.user_id = %s ORDER BY l.id DESC", (session['user_id'],))
    return render_template('transactions_log.html', transactions=trans, is_admin=is_admin)

@app.route('/return_book/<int:loan_id>', methods=['POST'])
@login_required
@admin_required
def return_book(loan_id):
    loan = db.query_db("SELECT * FROM loans WHERE id = %s", (loan_id,), one=True)
    if loan and not loan['return_date']:
        due = loan['due_date']
        if isinstance(due, str): due = datetime.strptime(due, '%Y-%m-%d').date()
        today = datetime.now().date()
        fine = max(0, (today - due).days * 20)
        
        db.query_db("UPDATE loans SET return_date=CURDATE(), fine_amount=%s WHERE id=%s", (fine, loan_id))
        db.query_db("UPDATE books SET quantity = quantity + 1 WHERE id=%s", (loan['book_id'],))
        flash(f"Returned. Fine: ₱{fine}", "success" if fine == 0 else "warning")
    return redirect(url_for('transactions_log'))

@app.route('/manage_books')
@login_required
@admin_required
def manage_books():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC")
    return render_template('manage_books.html', books=books)

@app.route('/view_users')
@login_required
@admin_required
def view_users():
    users = db.query_db("SELECT * FROM users")
    return render_template('view_users.html', all_users=users)

@app.route('/ai_chat', methods=['POST'])
def ai_chat():
    msg = request.get_json().get('message', '')
    return jsonify({"reply": rule_based_reply(msg)})

if __name__ == '__main__':
    app.run(debug=True)
