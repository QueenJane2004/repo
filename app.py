import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import random
import string
import re
import db

app = Flask(__name__)
app.secret_key = 'library_super_secret_key'

# --- FILE UPLOAD CONFIG ---
UPLOAD_FOLDER = 'static/uploads/books'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


db.init_db()


# ============================================================
# RULE-BASED CHATBOT (zero dependencies, ~0 MB RAM)
# ============================================================

CHAT_RULES = [
    (r'\b(hi|hello|hey|good morning|good afternoon|good evening)\b',
     "Hello! 👋 I'm LibrarianBot. How can I help you? Ask me about borrowing, fines, books, or library policies."),

    (r'\b(borrow limit|how many books|maximum borrow|can i borrow)\b',
     "Your borrow limit depends on your role:\n• Student → up to 5 books\n• Instructor → up to 20 books\nAll loans are for 10 days."),

    (r'\b(due date|loan period|how long|return date|when to return)\b',
     "Books are loaned for 10 days from checkout. Check your due dates on the dashboard."),

    (r'\b(fine|fines|overdue|penalty|late fee|late return|charge)\b',
     "The library charges ₱20 per day for overdue books. Your current fine (if any) appears on your dashboard."),

    (r'\b(pay fine|settle fine|clear fine|pay overdue)\b',
     "To settle fines, visit the library counter with your ID. Fines must be cleared before borrowing new books."),

    (r'\b(recommend|suggestion|what should i read|book suggestion|popular books)\b',
     "Your personalized recommendations are on your dashboard under 'Picked For You', based on your reading history!"),

    (r'\b(how to borrow|checkout|check out|borrow a book|get a book)\b',
     "To borrow: 1) Find the book on your dashboard, 2) Click Borrow, 3) Set quantity and confirm. The loan is for 10 days!"),

    (r'\b(how to return|return a book|bring back|give back)\b',
     "Bring the book to the library counter before the due date. Staff will process your return and update your account."),

    (r'\b(search|find a book|look for|available|in stock|do you have)\b',
     "Use the search bar on your dashboard to find books by title, author, publisher, or barcode."),

    (r'\b(my account|profile|username|password|change password)\b',
     "For account or password issues, contact the librarian or system administrator directly."),

    (r'\b(hours|open|close|schedule|library hours|when is the library)\b',
     "Check the library notice board or ask the librarian for current hours. Hours may vary during holidays."),

    (r'\b(contact|librarian|staff|help desk|support)\b',
     "You can message the librarian via Admin Chat on your dashboard, or visit the library counter in person."),

    (r'\b(thank you|thanks|thank|appreciate)\b',
     "You're welcome! 😊 Happy reading!"),

    (r'\b(bye|goodbye|see you|take care)\b',
     "Goodbye! 📚 Remember to return your books on time!"),

    (r'\b(barcode|book id|book code)\b',
     "Each book has a unique 13-digit barcode. You can search by barcode in the search bar."),

    (r'\b(new books|new arrivals|recently added|latest books)\b',
     "New books appear at the top of the collection on your dashboard. You'll also get a chat notification when new titles are added!"),

    (r'\b(rules|policy|policies|regulation|guidelines)\b',
     "Library Policies:\n• Students: 5 books max | Instructors: 20 books max\n• Loan period: 10 days\n• Fine: ₱20/day overdue\n• Return books in good condition\n• Lost books must be replaced or paid for"),
]

COMPILED_RULES = [(re.compile(p, re.IGNORECASE), r) for p, r in CHAT_RULES]

DEFAULT_REPLY = (
    "I'm not sure about that. 🤔 You can ask me about:\n"
    "• Borrowing limits & due dates\n"
    "• Fines & overdue books\n"
    "• How to search or borrow books\n"
    "• Library policies & recommendations"
)


def rule_based_reply(message: str) -> str:
    for pattern, response in COMPILED_RULES:
        if pattern.search(message):
            return response
    return DEFAULT_REPLY


# ============================================================
# HELPERS
# ============================================================

def get_recommendations(user_id):
    history = db.query_db("""
        SELECT DISTINCT b.author FROM loans l
        JOIN books b ON l.book_id = b.id
        WHERE l.user_id = ? LIMIT 5
    """, (user_id,))

    if not history:
        return db.query_db("SELECT * FROM books ORDER BY id DESC LIMIT 4")

    authors = [h['author'] for h in history]
    placeholders = ', '.join(['?'] * len(authors))
    recs = db.query_db(f"""
        SELECT * FROM books
        WHERE author IN ({placeholders})
        AND id NOT IN (SELECT book_id FROM loans WHERE user_id = ?)
        LIMIT 4
    """, (*authors, user_id))

    return recs if recs and len(recs) >= 2 else db.query_db("SELECT * FROM books ORDER BY id DESC LIMIT 4")


def update_fines(user_id):
    active_loans = db.query_db(
        "SELECT id, due_date FROM loans WHERE user_id = ? AND return_date IS NULL", (user_id,))
    total = 0
    for loan in active_loans:
        due = datetime.strptime(loan['due_date'], '%Y-%m-%d')
        if datetime.now() > due:
            days = (datetime.now() - due).days
            fine = days * 20
            total += fine
            db.query_db("UPDATE loans SET fine_amount = ? WHERE id = ?", (fine, loan['id']))
    return total


# ============================================================
# ROUTES
# ============================================================

@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db.query_db(
            "SELECT * FROM users WHERE username = ? AND password = ?",
            (request.form['username'], request.form['password']), one=True)
        if user:
            session.update({
                'user_id': user['id'],
                'username': user['username'],
                'role': user['role'],
                'firstname': user.get('firstname', 'User')
            })
            return redirect(url_for('admin_dashboard' if user['role'] == 'admin' else 'user_dashboard'))
        flash("Invalid credentials, please try again.", "danger")
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            db.query_db(
                "INSERT INTO users (username, password, firstname, lastname, role) VALUES (?, ?, ?, ?, ?)",
                (request.form['username'], request.form['password'],
                 request.form['firstname'], request.form['lastname'],
                 request.form.get('role', 'Student')))
            flash("Registration successful! You can now login.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            print(f"Register error: {e}")
            flash("Username already taken.", "danger")
    return render_template('register.html')


@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    return render_template('admin.html',
        users_count=db.query_db("SELECT COUNT(*) as c FROM users", one=True)['c'],
        books_count=db.query_db("SELECT COUNT(*) as c FROM books", one=True)['c'],
        borrowed_count=db.query_db("SELECT COUNT(*) as c FROM loans WHERE return_date IS NULL", one=True)['c'],
        all_users=db.query_db("SELECT id, username, firstname, lastname, role FROM users"),
        books=db.query_db("SELECT * FROM books ORDER BY id DESC"),
        messages=db.query_db("SELECT * FROM messages ORDER BY timestamp ASC"),
        trending_books=db.query_db("""
            SELECT b.title, COUNT(l.id) as borrow_count FROM books b
            LEFT JOIN loans l ON b.id = l.book_id
            GROUP BY b.id ORDER BY borrow_count DESC LIMIT 5
        """),
        transactions=db.query_db("""
            SELECT u.username as user_name, b.title as book_title,
                   'Checkout' as type, l.issue_date as timestamp
            FROM loans l
            JOIN users u ON l.user_id = u.id
            JOIN books b ON l.book_id = b.id
            ORDER BY l.issue_date DESC LIMIT 10
        """))


@app.route('/add_book', methods=['POST'])
def add_book():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    title = request.form.get('title')
    author = request.form.get('author')
    publisher = request.form.get('publisher', 'Unknown Library Press')
    quantity = request.form.get('quantity', 1)
    barcode = ''.join(random.choices(string.digits, k=13))
    description = (f"'{title}' by {author}, published by {publisher}. "
                   "A valuable addition to the library collection.")

    image_url = '/static/uploads/books/default_cover.png'
    if 'book_image' in request.files:
        file = request.files['book_image']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"{barcode}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_url = f"/static/uploads/books/{filename}"

    try:
        db.query_db(
            "INSERT INTO books (title, author, publisher, image_url, quantity, status, barcode, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, author, publisher, image_url, quantity, 'Available', barcode, description))

        for member in db.query_db("SELECT id FROM users WHERE role != 'admin'"):
            db.query_db(
                "INSERT INTO messages (user_id, sender_name, content, is_admin_reply) VALUES (?, ?, ?, 1)",
                (member['id'], 'AI Librarian',
                 f"📚 NEW BOOK: '{title}' by {author} is now available! Barcode: {barcode}."))

        flash(f"Book '{title}' added successfully!", "success")
    except Exception as e:
        print(f"Add book error: {e}")
        flash("Error adding book. Please try again.", "danger")

    return redirect('/admin')


@app.route('/update_book_qty', methods=['POST'])
def update_book_qty():
    if session.get('role') not in ['admin', 'Instructor']:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.json
    try:
        db.query_db("UPDATE books SET quantity = ? WHERE id = ?", (data.get('quantity'), data.get('book_id')))
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/admin/transactions')
def admin_transactions():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    history = db.query_db("""
        SELECT u.username as user_name, b.title as book_title,
               l.issue_date, l.due_date, l.return_date, l.fine_amount
        FROM loans l
        JOIN users u ON l.user_id = u.id
        JOIN books b ON l.book_id = b.id
        ORDER BY l.issue_date DESC
    """)
    return render_template('transactions.html', transactions=history, is_admin=True)


@app.route('/user')
def user_dashboard():
    if not session.get('username'):
        return redirect(url_for('login'))

    user_id = session['user_id']
    total_fine = update_fines(user_id)
    if total_fine > 0:
        flash(f"⚠️ You have an outstanding fine of ₱{total_fine}. Please return overdue books.", "danger")

    user_role = session.get('role', 'Student')
    search_query = request.args.get('search', '')

    if search_query:
        books = db.query_db(
            "SELECT * FROM books WHERE title LIKE ? OR author LIKE ? OR publisher LIKE ? OR barcode LIKE ? ORDER BY id DESC",
            tuple(f'%{search_query}%' for _ in range(4)))
    else:
        books = db.query_db("SELECT * FROM books ORDER BY id DESC")

    return render_template('user.html',
        books=books,
        recommendations=get_recommendations(user_id),
        limit=20 if user_role == 'Instructor' else 5,
        role=user_role,
        total_fine=total_fine)


@app.route('/checkout/<int:book_id>', methods=['GET', 'POST'])
def checkout_book(book_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))

    user_role = session.get('role', 'Student')
    borrow_limit = 20 if user_role == 'Instructor' else 5

    try:
        requested_qty = int(request.form.get('quantity', 1))
    except ValueError:
        requested_qty = 1

    active = db.query_db(
        "SELECT COUNT(*) as count FROM loans WHERE user_id = ? AND return_date IS NULL",
        (session['user_id'],), one=True)

    if (active['count'] if active else 0) + requested_qty > borrow_limit:
        flash(f"Borrow limit exceeded! Max: {borrow_limit} books.", "danger")
        return redirect(url_for('user_dashboard'))

    book = db.query_db("SELECT quantity, title FROM books WHERE id = ?", (book_id,), one=True)
    if not book or book['quantity'] < requested_qty:
        flash("Not enough copies available.", "warning")
        return redirect(url_for('user_dashboard'))

    due_date = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d')
    for _ in range(requested_qty):
        db.query_db(
            "INSERT INTO loans (book_id, user_id, issue_date, due_date) VALUES (?, ?, date('now'), ?)",
            (book_id, session['user_id'], due_date))
    db.query_db("UPDATE books SET quantity = quantity - ? WHERE id = ?", (requested_qty, book_id))

    flash(f"✅ Borrowed '{book['title']}'. Due: {due_date}", "success")
    return redirect(url_for('user_dashboard'))


@app.route('/ai_chat', methods=['POST'])
def ai_chat():
    data = request.json
    user_message = data.get('message', '').strip()
    user_id = session.get('user_id')

    if not user_id:
        return jsonify({"reply": "Session expired. Please log in again."})
    if not user_message:
        return jsonify({"reply": "Please type a message."})

    db.query_db(
        "INSERT INTO messages (user_id, sender_name, content, is_admin_reply) VALUES (?, ?, ?, 0)",
        (user_id, session.get('username'), user_message))

    if data.get('is_admin'):
        db.query_db(
            "INSERT INTO messages (user_id, sender_name, content, is_admin_reply) VALUES (?, ?, ?, 1)",
            (data.get('target_user'), 'Admin', user_message))
        return jsonify({"status": "Admin reply saved"})

    msg = user_message.lower()
    if any(k in msg for k in ['borrow limit', 'how many', 'maximum', 'can i borrow']):
        role = session.get('role', 'Student')
        limit = 20 if role == 'Instructor' else 5
        reply = f"As a {role}, you can borrow up to {limit} books for 10 days. Fine: ₱20/day overdue."
    elif any(k in msg for k in ['fine', 'overdue', 'penalty', 'late']):
        total_fine = update_fines(user_id)
        reply = (f"You have an outstanding fine of ₱{total_fine}. Visit the counter to settle it."
                 if total_fine > 0 else
                 "Great news — you have no outstanding fines! 😊")
    elif any(k in msg for k in ['recommend', 'suggestion', 'what should i read']):
        reply = "Your personalized picks are on your dashboard under 'Picked For You'. 📚"
    else:
        reply = rule_based_reply(user_message)

    db.query_db(
        "INSERT INTO messages (user_id, sender_name, content, is_admin_reply) VALUES (?, ?, ?, 1)",
        (user_id, 'AI Librarian', reply))
    return jsonify({"reply": reply})


@app.route('/get_messages')
def get_messages():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])
    return jsonify(db.query_db(
        "SELECT content, is_admin_reply FROM messages WHERE user_id = ? ORDER BY timestamp ASC",
        (user_id,)))


@app.route('/manage_books')
def manage_books():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('manage_books.html', books=db.query_db("SELECT * FROM books"))


@app.route('/view_users')
def view_users():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('view_users.html',
        all_users=db.query_db("SELECT id, username, firstname, lastname, role FROM users"))


@app.route('/transactions_log')
def transactions_log():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('transactions.html', is_admin=True, transactions=db.query_db("""
        SELECT u.username AS user_name, b.title AS book_title, b.author AS book_author,
               l.issue_date, l.due_date, l.return_date, l.fine_amount
        FROM loans l
        JOIN users u ON l.user_id = u.id
        JOIN books b ON l.book_id = b.id
        WHERE u.role != 'admin'
        ORDER BY l.issue_date DESC
    """))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)