import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename
import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123")

# Configuration for Image Uploads
UPLOAD_FOLDER = 'static/uploads/books'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    if not session.get('user_id'):
        return redirect(url_for('login'))
    return redirect(url_for('admin_dashboard' if session['role'] == 'admin' else 'user_dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = db.query_db("SELECT * FROM users WHERE username = ?", [username], one=True)
        if user and user['password'] == password:
            session['user_id']   = user['id']
            session['firstname'] = user['firstname']
            session['role']      = user['role']
            return redirect(url_for('admin_dashboard' if user['role'] == 'admin' else 'user_dashboard'))
        flash("Invalid username or password", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        f = request.form.get('firstname')
        l = request.form.get('lastname')
        u = request.form.get('username')
        p = request.form.get('password')
        existing = db.query_db("SELECT id FROM users WHERE username = ?", [u], one=True)
        if existing:
            flash("Username already taken. Please choose another.", "danger")
            return render_template('register.html')
        db.query_db(
            "INSERT INTO users (username, password, firstname, lastname, role) VALUES (?, ?, ?, ?, 'user')",
            (u, p, f, l)
        )
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- ADMIN ROUTES ---

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('user_dashboard'))

    b_count = db.query_db("SELECT COUNT(*) as count FROM books", one=True)['count']
    u_count = db.query_db("SELECT COUNT(*) as count FROM users WHERE role='user'", one=True)['count']

    # Only count loans not yet returned
    l_count = db.query_db(
        "SELECT COUNT(*) as count FROM loans WHERE return_date IS NULL", one=True
    )['count']

    all_users = db.query_db("SELECT * FROM users ORDER BY id DESC")

    # Most borrowed books with real borrow counts
    trending = db.query_db("""
        SELECT b.id, b.title, b.author,
               COUNT(l.id) as borrow_count
        FROM books b
        LEFT JOIN loans l ON l.book_id = b.id
        GROUP BY b.id
        ORDER BY borrow_count DESC
        LIMIT 5
    """)

    # Recent activity for dashboard table
    recent_activity = db.query_db("""
        SELECT l.*, b.title as book_title, u.username
        FROM loans l
        JOIN books b ON b.id = l.book_id
        JOIN users u ON u.id = l.user_id
        ORDER BY l.id DESC
        LIMIT 10
    """)

    now = datetime.today().strftime('%Y-%m-%d')

    return render_template('admin.html',
                           books_count=b_count,
                           users_count=u_count,
                           borrowed_count=l_count,
                           all_users=all_users or [],
                           trending_books=trending or [],
                           recent_activity=recent_activity or [],
                           now=now)


@app.route('/manage_books')
@login_required
@admin_required
def manage_books():
    books = db.query_db("SELECT * FROM books ORDER BY id DESC")
    return render_template('manage_books.html', books=books or [])


@app.route('/view_users')
@login_required
@admin_required
def view_users():
    users = db.query_db("SELECT * FROM users ORDER BY id DESC")
    return render_template('view_users.html', all_users=users or [])


@app.route('/transactions_log')
@login_required
@admin_required
def transactions_log():
    logs = db.query_db("""
        SELECT l.*, b.title as book_title, u.username
        FROM loans l
        JOIN books b ON b.id = l.book_id
        JOIN users u ON u.id = l.user_id
        ORDER BY l.id DESC
    """)
    now = datetime.today().strftime('%Y-%m-%d')
    return render_template('activity_logs.html', logs=logs or [], now=now)


# --- ACTION ROUTES ---

@app.route('/checkout/<int:book_id>', methods=['POST'])
@login_required
def checkout(book_id):
    user_id      = session['user_id']
    BORROW_LIMIT = 5
    LOAN_DAYS    = 7

    book = db.query_db("SELECT * FROM books WHERE id = ?", [book_id], one=True)
    if not book:
        flash("Book not found.", "danger")
        return redirect(url_for('user_dashboard'))

    if book['quantity'] <= 0:
        flash("Sorry, this book is out of stock.", "danger")
        return redirect(url_for('user_dashboard'))

    already_borrowed = db.query_db(
        "SELECT id FROM loans WHERE user_id = ? AND book_id = ? AND return_date IS NULL",
        [user_id, book_id], one=True
    )
    if already_borrowed:
        flash("You have already borrowed this book.", "warning")
        return redirect(url_for('user_dashboard'))

    active_count = db.query_db(
        "SELECT COUNT(*) as count FROM loans WHERE user_id = ? AND return_date IS NULL",
        [user_id], one=True
    )
    if active_count and active_count['count'] >= BORROW_LIMIT:
        flash(f"You have reached your borrow limit of {BORROW_LIMIT} books.", "warning")
        return redirect(url_for('user_dashboard'))

    db.query_db("UPDATE books SET quantity = quantity - 1 WHERE id = ?", [book_id])

    today      = datetime.today()
    issue_date = today.strftime('%Y-%m-%d')
    due_date   = (today + timedelta(days=LOAN_DAYS)).strftime('%Y-%m-%d')

    db.query_db(
        "INSERT INTO loans (user_id, book_id, issue_date, due_date) VALUES (?, ?, ?, ?)",
        [user_id, book_id, issue_date, due_date]
    )

    flash(f'You have successfully borrowed "{book["title"]}"! Due back by {due_date}.', "success")
    return redirect(url_for('user_dashboard'))


@app.route('/return_book/<int:loan_id>', methods=['POST'])
@login_required
def return_book(loan_id):
    user_id  = session['user_id']
    is_admin = session.get('role') == 'admin'

    # Admins can return any loan; members only their own
    if is_admin:
        loan = db.query_db(
            "SELECT * FROM loans WHERE id = ? AND return_date IS NULL",
            [loan_id], one=True
        )
    else:
        loan = db.query_db(
            "SELECT * FROM loans WHERE id = ? AND user_id = ? AND return_date IS NULL",
            [loan_id, user_id], one=True
        )

    if not loan:
        flash("Loan not found or already returned.", "danger")
        return redirect(url_for('borrow_books'))

    today       = datetime.today()
    return_date = today.strftime('%Y-%m-%d')
    due         = datetime.strptime(loan['due_date'], '%Y-%m-%d')
    fine        = max(0, (today - due).days) * 5 if today > due else 0

    db.query_db(
        "UPDATE loans SET return_date = ?, fine_amount = ? WHERE id = ?",
        [return_date, fine, loan_id]
    )
    db.query_db("UPDATE books SET quantity = quantity + 1 WHERE id = ?", [loan['book_id']])

    if fine > 0:
        flash(f'Book returned. Fine of ₱{fine} recorded. Please settle at the counter.', "warning")
    else:
        flash("Book returned successfully! Thank you.", "success")

    return redirect(url_for('borrow_books'))


@app.route('/add_book', methods=['POST'])
@login_required
@admin_required
def add_book():
    title       = request.form.get('title')
    author      = request.form.get('author')
    publisher   = request.form.get('publisher')
    description = request.form.get('description')
    quantity    = request.form.get('quantity', 1)
    barcode     = str(uuid.uuid4().hex[:8]).upper()
    image_path  = None

    if 'book_image' in request.files:
        file = request.files['book_image']
        if file and allowed_file(file.filename):
            filename   = secure_filename(f"{barcode}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = f"/static/uploads/books/{filename}"

    db.query_db("""
        INSERT INTO books (title, author, publisher, description, image_url, barcode, quantity)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (title, author, publisher, description, image_path, barcode, quantity))

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
    if data and 'book_id' in data and 'quantity' in data:
        db.query_db(
            "UPDATE books SET quantity = ? WHERE id = ?",
            (data['quantity'], data['book_id'])
        )
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 400


@app.route('/borrow_books')
@login_required
def borrow_books():
    user_id  = session['user_id']
    is_admin = session.get('role') == 'admin'
    today    = datetime.today()
    now      = today.strftime('%Y-%m-%d')

    if is_admin:
        active_loans = db.query_db("""
            SELECT l.*, b.title as book_title, b.author, b.image_url, u.username
            FROM loans l
            JOIN books b ON b.id = l.book_id
            JOIN users u ON u.id = l.user_id
            WHERE l.return_date IS NULL
            ORDER BY l.due_date ASC
        """) or []

        returned_loans = db.query_db("""
            SELECT l.*, b.title as book_title, u.username
            FROM loans l
            JOIN books b ON b.id = l.book_id
            JOIN users u ON u.id = l.user_id
            WHERE l.return_date IS NOT NULL
            ORDER BY l.return_date DESC
            LIMIT 50
        """) or []

    else:
        active_loans = db.query_db("""
            SELECT l.*, b.title as book_title, b.author, b.image_url
            FROM loans l
            JOIN books b ON b.id = l.book_id
            WHERE l.user_id = ? AND l.return_date IS NULL
            ORDER BY l.due_date ASC
        """, [user_id]) or []

        returned_loans = []

    total_fine    = 0
    overdue_count = 0
    for loan in active_loans:
        due = datetime.strptime(loan['due_date'], '%Y-%m-%d')
        if today > due:
            loan['overdue_days'] = (today - due).days
            loan['current_fine'] = loan['overdue_days'] * 5
            total_fine          += loan['current_fine']
            overdue_count       += 1
        else:
            loan['overdue_days'] = 0
            loan['current_fine'] = 0

    return render_template('borrow_books.html',
                           active_loans=active_loans,
                           returned_loans=returned_loans,
                           total_fine=total_fine,
                           overdue_count=overdue_count,
                           now=now)


# --- USER ROUTES ---

@app.route('/user')
def user_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))

    user_id = session['user_id']
    books   = db.query_db("SELECT * FROM books") or []
    recs    = db.query_db("SELECT * FROM books ORDER BY RANDOM() LIMIT 4") or []

    active_count_row = db.query_db(
        "SELECT COUNT(*) as count FROM loans WHERE user_id = ? AND return_date IS NULL",
        [user_id], one=True
    )
    active_count = active_count_row['count'] if active_count_row else 0

    today         = datetime.today()
    overdue_loans = db.query_db(
        "SELECT due_date FROM loans WHERE user_id = ? AND return_date IS NULL AND due_date < ?",
        [user_id, today.strftime('%Y-%m-%d')]
    ) or []

    total_fine = sum(
        (today - datetime.strptime(loan['due_date'], '%Y-%m-%d')).days * 5
        for loan in overdue_loans
    )

    return render_template('user.html',
                           books=books,
                           recommendations=recs,
                           limit=5 - active_count,
                           total_fine=total_fine)


# --- AI CHAT ---

@app.route('/ai_chat', methods=['POST'])
def ai_chat():
    data         = request.get_json()
    user_message = data.get('message', '').lower().strip()

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    if any(w in user_message for w in ['fine', 'overdue', 'penalty', 'fee']):
        reply = "Overdue fines are ₱5 per day past the due date. Please settle at the library counter."
    elif any(w in user_message for w in ['borrow', 'checkout', 'limit']):
        reply = "You can borrow up to 5 books at a time. Books are due 7 days after borrowing."
    elif any(w in user_message for w in ['return', 'give back']):
        reply = "You can return books from your 'My Borrowed Books' page. Return before the due date to avoid fines."
    elif any(w in user_message for w in ['available', 'stock', 'copies']):
        reply = "Book availability is shown on each book card. Green means available, red means out of stock."
    elif any(w in user_message for w in ['hello', 'hi', 'hey']):
        reply = "Hello! I can help with borrowing, returns, fines, and book availability. What do you need?"
    else:
        reply = "I can help with: borrowing limits, due dates, fines, and returning books. What would you like to know?"

    return jsonify({"reply": reply})


# --- USER MANAGEMENT ---

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == session.get('user_id'):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('view_users'))
    db.query_db("DELETE FROM users WHERE id = ?", [user_id])
    flash("User deleted successfully!", "success")
    return redirect(url_for('view_users'))


if __name__ == '__main__':
    app.run(debug=True)