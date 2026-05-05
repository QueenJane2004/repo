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

db.init_db()

# =========================
# CHATBOT RULES
# =========================
CHAT_RULES = [
    (r'\b(hi|hello|hey)\b',     "Hello! 👋 Ask me about books, borrowing, returns, or fines."),
    (r'\b(fine|overdue)\b',     "A ₱20 per day overdue fee applies after the due date."),
    (r'\b(borrow)\b',           "You can borrow books directly from the dashboard. Click 'Borrow' on any available book."),
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

        user = db.query_db(
            "SELECT * FROM users WHERE username = %s AND password = %s",
            (username, password),
            one=True
        )

        if user:
            session['user_id']   = user['id']
            session['firstname'] = user.get('firstname', 'User')
            session['lastname']  = user.get('lastname', '')
            session['role']      = user.get('role', 'user')

            if user['role'] == 'admin':
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
        role      = request.form.get('role', 'Student')
        username  = request.form.get('username', '').strip()
        password  = request.form.get('password', '').strip()

        if not all([firstname, lastname, username, password]):
            flash("All fields are required.", "warning")
            return render_template('register.html')

        existing = db.query_db("SELECT id FROM users WHERE username = %s", (username,), one=True)
        if existing:
            flash("Username already taken. Please choose another.", "warning")
            return render_template('register.html')

        db.query_db(
            "INSERT INTO users (username, password, firstname, lastname, role) VALUES (%s, %s, %s, %s, %s)",
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
        result = db.query_db("""
            SELECT COALESCE(SUM(fine_amount), 0) AS total
            FROM loans
            WHERE user_id = %s AND return_date IS NULL
        """, (session['user_id'],), one=True)
        total_fine = float(result['total']) if result and result['total'] else 0
    except Exception as e:
        print("Fine calc error:", e)

    # FIX: RANDOM() works in PostgreSQL; wrapped in try/except for safety
    recommendations = []
    try:
        recommendations = db.query_db("""
            SELECT * FROM books
            WHERE id NOT IN (
                SELECT book_id FROM loans WHERE user_id = %s
            )
            ORDER BY RANDOM() LIMIT 4
        """, (session['user_id'],)) or []
    except Exception as e:
        print("Recommendations error:", e)

    return render_template(
        'user.html',
        books=books,
        total_fine=total_fine,
        limit=limit,
        recommendations=recommendations
    )

@app.route("/transactions_log")
@login_required
def transactions_log():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    transactions = db.query_db("""
        SELECT b.title, b.author, l.issue_date, l.due_date, l.return_date
        FROM loans l
        JOIN books b ON l.book_id = b.id
        WHERE l.user_id = %s
        ORDER BY l.issue_date DESC
    """, (user_id,))
    
    return render_template("transactions_log.html", transactions=transactions)

@app.route('/checkout/<int:book_id>', methods=['POST'])
@login_required
def checkout(book_id):
    book = db.query_db("SELECT * FROM books WHERE id = %s", (book_id,), one=True)

    if not book:
        flash("Book not found.", "danger")
        return redirect(url_for('user_dashboard'))

    if book['quantity'] <= 0:
        flash("This book is currently out of stock.", "warning")
        return redirect(url_for('user_dashboard'))

    active_loans = db.query_db(
        "SELECT COUNT(*) AS cnt FROM loans WHERE user_id = %s AND return_date IS NULL",
        (session['user_id'],), one=True
    )
    if active_loans and active_loans['cnt'] >= 5:
        flash("You have reached your borrowing limit of 5 books.", "warning")
        return redirect(url_for('user_dashboard'))

    try:
        issue_date = datetime.now().date()
        due_date   = (datetime.now() + timedelta(days=10)).date()

        db.query_db(
            "INSERT INTO loans (book_id, user_id, issue_date, due_date, fine_amount) VALUES (%s, %s, %s, %s, 0)",
            (book_id, session['user_id'], issue_date, due_date)
        )
        db.query_db(
            "UPDATE books SET quantity = quantity - 1 WHERE id = %s",
            (book_id,)
        )
        flash(f"✅ '{book['title']}' borrowed successfully! Due on {due_date}.", "success")

    except Exception as e:
        print("Checkout error:", e)
        flash("Something went wrong while borrowing. Please try again.", "danger")

    return redirect(url_for('user_dashboard'))


# ---------- ADMIN ----------

@app.route('/admin')
@admin_required
def admin_dashboard():
    books_count    = db.query_db("SELECT COUNT(*) AS cnt FROM books", one=True)
    users_count    = db.query_db("SELECT COUNT(*) AS cnt FROM users", one=True)
    borrowed_count = db.query_db("SELECT COUNT(*) AS cnt FROM loans WHERE return_date IS NULL", one=True)
    all_users      = db.query_db("SELECT * FROM users ORDER BY id DESC") or []

    trending_books = db.query_db("""
        SELECT b.title, COUNT(l.id) AS borrow_count
        FROM loans l
        JOIN books b ON b.id = l.book_id
        GROUP BY b.title
        ORDER BY borrow_count DESC
        LIMIT 10
    """) or []

    # FIX: messages table now created in init_db so this won't crash
    messages = db.query_db("""
        SELECT m.*, u.firstname || ' ' || u.lastname AS sender_name
        FROM messages m
        LEFT JOIN users u ON u.id = m.user_id
        ORDER BY m.created_at ASC
        LIMIT 50
    """) or []

    return render_template(
        'admin.html',
        books_count    = books_count['cnt'] if books_count else 0,
        users_count    = users_count['cnt'] if users_count else 0,
        borrowed_count = borrowed_count['cnt'] if borrowed_count else 0,
        trending_books = trending_books,
        all_users      = all_users,
        messages       = messages
    )


@app.route('/manage_books')
@admin_required
def manage_books():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC") or []
    return render_template('manage_books.html', books=books)


@app.route('/add_book', methods=['POST'])
@admin_required
def add_book():
    title       = request.form.get('title', '').strip()
    author      = request.form.get('author', '').strip()
    publisher   = request.form.get('publisher', '').strip()
    description = request.form.get('description', '').strip()
    quantity    = int(request.form.get('quantity', 1))

    if not title:
        flash("Book title is required.", "warning")
        return redirect(url_for('manage_books'))

    barcode = 'B' + ''.join(random.choices(string.digits, k=6))

    image_url = '/static/uploads/books/default_cover.png'
    file = request.files.get('book_image')
    if file and file.filename:
        upload_folder = os.path.join('static', 'uploads', 'books')
        os.makedirs(upload_folder, exist_ok=True)
        safe_name = ''.join(c if c.isalnum() or c in '._-' else '_' for c in file.filename)
        file_path = os.path.join(upload_folder, safe_name)
        file.save(file_path)
        image_url = '/' + file_path

    db.query_db(
        "INSERT INTO books (title, author, publisher, description, image_url, barcode, quantity, status) VALUES (%s,%s,%s,%s,%s,%s,%s,'Available')",
        (title, author, publisher, description, image_url, barcode, quantity)
    )

    flash(f"✅ '{title}' added to the collection.", "success")
    return redirect(url_for('manage_books'))


@app.route('/delete_book/<int:book_id>', methods=['POST'])
@admin_required
def delete_book(book_id):
    book = db.query_db("SELECT title FROM books WHERE id = %s", (book_id,), one=True)
    if book:
        db.query_db("DELETE FROM books WHERE id = %s", (book_id,))
        flash(f"🗑️ '{book['title']}' has been deleted.", "success")
    else:
        flash("Book not found.", "danger")
    return redirect(url_for('manage_books'))


@app.route('/update_book_qty', methods=['POST'])
@admin_required
def update_book_qty():
    data     = request.get_json()
    book_id  = data.get('book_id')
    quantity = data.get('quantity')

    if book_id is None or quantity is None:
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    db.query_db(
        "UPDATE books SET quantity = %s WHERE id = %s",
        (int(quantity), int(book_id))
    )
    return jsonify({"status": "success"})


@app.route('/return_book/<int:loan_id>', methods=['POST'])
@admin_required
def return_book(loan_id):
    loan = db.query_db("SELECT * FROM loans WHERE id = %s", (loan_id,), one=True)
    if not loan:
        flash("Loan record not found.", "danger")
        return redirect(url_for('transactions_log'))

    if loan['return_date']:
        flash("This book has already been returned.", "warning")
        return redirect(url_for('transactions_log'))

    today    = datetime.now().date()
    due_date = loan['due_date']
    fine     = 0

    if isinstance(due_date, str):
        due_date = datetime.strptime(due_date, '%Y-%m-%d').date()

    if today > due_date:
        overdue_days = (today - due_date).days
        fine = overdue_days * 20  # ₱20 per day

    db.query_db(
        "UPDATE loans SET return_date = %s, fine_amount = %s WHERE id = %s",
        (today, fine, loan_id)
    )
    db.query_db(
        "UPDATE books SET quantity = quantity + 1 WHERE id = %s",
        (loan['book_id'],)
    )

    if fine > 0:
        flash(f"✅ Book returned with ₱{fine} fine ({(today - due_date).days} days overdue).", "warning")
    else:
        flash("✅ Book returned successfully. No fine.", "success")

    return redirect(url_for('transactions_log'))


@app.route('/view_users')
@admin_required
def view_users():
    all_users = db.query_db("SELECT * FROM users ORDER BY id DESC") or []
    return render_template('view_users.html', all_users=all_users)


@app.route('/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    if user_id == session.get('user_id'):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('view_users'))
    user = db.query_db("SELECT * FROM users WHERE id = %s", (user_id,), one=True)
    if user:
        db.query_db("DELETE FROM users WHERE id = %s", (user_id,))
        flash(f"User '{user['username']}' deleted.", "success")
    else:
        flash("User not found.", "danger")
    return redirect(url_for('view_users'))


@app.route('/transactions_log')
@login_required
def transactions_log():
    is_admin = session.get('role') == 'admin'

    if is_admin:
        transactions = db.query_db("""
            SELECT
                l.id, l.issue_date, l.due_date, l.return_date, l.fine_amount,
                b.title AS book_title, b.author AS book_author,
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
                b.title AS book_title, b.author AS book_author
            FROM loans l
            JOIN books b ON b.id = l.book_id
            WHERE l.user_id = %s
            ORDER BY l.issue_date DESC
        """, (session['user_id'],)) or []

    return render_template('transactions_log.html',
                           transactions=transactions,
                           is_admin=is_admin)


# ---------- CHAT ----------

@app.route('/ai_chat', methods=['POST'])
@login_required
def ai_chat():
    data  = request.get_json()
    msg   = data.get('message', '').strip()
    reply = rule_based_reply(msg)
    return jsonify({"reply": reply})


@app.route('/get_messages')
@login_required
def get_messages():
    return jsonify([])


if __name__ == '__main__':
    app.run(debug=True)
