import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from chatterbot import ChatBot
from chatterbot.trainers import ChatterBotCorpusTrainer
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename  # Added for secure file uploads
import random
import string
import db

app = Flask(__name__)
app.secret_key = 'library_super_secret_key'

# --- CONFIGURATION FOR FILE UPLOADS ---
UPLOAD_FOLDER = 'static/uploads/books'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload directory exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# Initialize Chatbot
chatbot = ChatBot('LibrarianBot')
trainer = ChatterBotCorpusTrainer(chatbot)
trainer.train("chatterbot.corpus.english.greetings", "chatterbot.corpus.english.conversations")

# Initialize DB
db.init_db()


# --- HELPER: Machine Learning Recommendation Engine ---
def get_recommendations(user_id):
    """
    ML Logic: Simple Content-Based Filtering.
    Analyzes authors from user's borrow history to suggest similar books.
    """
    history = db.query_db("""
        SELECT DISTINCT b.author 
        FROM loans l 
        JOIN books b ON l.book_id = b.id 
        WHERE l.user_id = ? 
        LIMIT 5
    """, (user_id,))

    if not history:
        return db.query_db("SELECT * FROM books ORDER BY id DESC LIMIT 4")

    authors = [h['author'] for h in history]
    placeholders = ', '.join(['?'] * len(authors))
    recommendations = db.query_db(f"""
        SELECT * FROM books 
        WHERE author IN ({placeholders}) 
        AND id NOT IN (SELECT book_id FROM loans WHERE user_id = ?)
        LIMIT 4
    """, (*authors, user_id))

    if not recommendations or len(recommendations) < 2:
        return db.query_db("SELECT * FROM books ORDER BY id DESC LIMIT 4")

    return recommendations


# --- HELPER: Fine Calculation Logic ---
def update_fines(user_id):
    """
    Calculates 20 pesos per day for books kept past the due_date.
    """
    active_loans = db.query_db("SELECT id, due_date FROM loans WHERE user_id = ? AND return_date IS NULL", (user_id,))
    total_unpaid_fine = 0

    for loan in active_loans:
        due_date = datetime.strptime(loan['due_date'], '%Y-%m-%d')
        today = datetime.now()

        if today > due_date:
            overdue_days = (today - due_date).days
            fine = overdue_days * 20  # 20 Pesos rate
            total_unpaid_fine += fine
            # Update the specific loan record with the calculated fine
            db.query_db("UPDATE loans SET fine_amount = ? WHERE id = ?", (fine, loan['id']))

    return total_unpaid_fine


@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = db.query_db("SELECT * FROM users WHERE username = ? AND password = ?", (username, password), one=True)

        if user:
            session['user_id'] = user.get('id')
            session['username'] = user.get('username')
            session['role'] = user.get('role')
            session['firstname'] = user.get('firstname', 'User')
            return redirect(url_for('admin_dashboard' if session['role'] == 'admin' else 'user_dashboard'))

        flash("Invalid credentials, please try again.", "danger")
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fname = request.form['firstname']
        lname = request.form['lastname']
        uname = request.form['username']
        pword = request.form['password']
        role = request.form.get('role', 'Student')

        try:
            db.query_db("INSERT INTO users (username, password, firstname, lastname, role) VALUES (?, ?, ?, ?, ?)",
                        (uname, pword, fname, lname, role))
            flash("Registration successful! You can now login.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            print(f"Error: {e}")
            flash("Username already taken.", "danger")
    return render_template('register.html')


# --- ADMIN / LIBRARIAN SECTION ---

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    u_data = db.query_db("SELECT COUNT(*) as count FROM users", one=True)
    b_data = db.query_db("SELECT COUNT(*) as count FROM books", one=True)

    # FIXED: "Live Borrows" now counts active transactions from the loans table
    br_data = db.query_db("SELECT COUNT(*) as count FROM loans WHERE return_date IS NULL", one=True)

    all_users = db.query_db("SELECT id, username, firstname, lastname, role FROM users")
    messages = db.query_db("SELECT * FROM messages ORDER BY timestamp ASC")

    # Updated: Selection includes barcode and description for admin visibility
    books = db.query_db("SELECT * FROM books ORDER BY id DESC")

    trending_books = db.query_db("""
        SELECT b.title, COUNT(l.id) as borrow_count 
        FROM books b 
        LEFT JOIN loans l ON b.id = l.book_id 
        GROUP BY b.id 
        ORDER BY borrow_count DESC LIMIT 5
    """)

    transactions = db.query_db("""
        SELECT u.username as user_name, b.title as book_title, 'Checkout' as type, l.issue_date as timestamp 
        FROM loans l
        JOIN users u ON l.user_id = u.id
        JOIN books b ON l.book_id = b.id
        ORDER BY l.issue_date DESC LIMIT 10
    """)

    return render_template('admin.html',
                           users_count=u_data['count'] if u_data else 0,
                           books_count=b_data['count'] if b_data else 0,
                           borrowed_count=br_data['count'] if br_data else 0,
                           all_users=all_users,
                           books=books,
                           messages=messages,
                           transactions=transactions,
                           trending_books=trending_books)


# --- UPDATED ADD_BOOK ROUTE ---
@app.route('/add_book', methods=['POST'])
def add_book():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    # 1. Collect Form Data
    title = request.form.get('title')
    author = request.form.get('author')
    publisher = request.form.get('publisher', 'Unknown Library Press')
    quantity = request.form.get('quantity', 1)

    # 2. Automated Barcode Generation (ML/System generated)
    barcode = ''.join(random.choices(string.digits, k=13))

    # 3. Automated Description (AI Analysis placeholder)
    description = f"This resource, '{title}' by {author}, is a valuable addition to our collection. Cataloged under {publisher}, it provides extensive insights into its subject matter. Auto-generated via ML analysis."

    # 4. Handle Image Upload
    image_url = '/static/uploads/books/default_cover.png'  # Default if none uploaded
    if 'book_image' in request.files:
        file = request.files['book_image']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(f"{barcode}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_url = f"/static/uploads/books/{filename}"

    try:
        # 5. Insert into Database
        db.query_db(
            "INSERT INTO books (title, author, publisher, image_url, quantity, status, barcode, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, author, publisher, image_url, quantity, 'Available', barcode, description))

        # 6. Notify All Users via Chat
        all_members = db.query_db("SELECT id FROM users WHERE role != 'admin'")
        for member in all_members:
            db.query_db(
                "INSERT INTO messages (user_id, sender_name, content, is_admin_reply) VALUES (?, ?, ?, 1)",
                (member['id'], 'AI Librarian',
                 f"NEW BOOK ALERT: '{title}' is now available! Barcode: {barcode}. Check your recommendations.")
            )

        flash(f"Book '{title}' added and announced to all members!", "success")
    except Exception as e:
        print(f"Error: {e}")
        flash(f"System error cataloging book. Please check database logs.", "danger")

    return redirect('/admin')


@app.route('/update_book_qty', methods=['POST'])
def update_book_qty():
    if session.get('role') not in ['admin', 'Instructor']:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    book_id = data.get('book_id')
    new_qty = data.get('quantity')

    try:
        db.query_db("UPDATE books SET quantity = ? WHERE id = ?", (new_qty, book_id))
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/admin/transactions')
def admin_transactions():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    query = """
        SELECT u.username as user_name, b.title as book_title, l.issue_date, l.due_date, l.return_date, l.fine_amount 
        FROM loans l
        JOIN users u ON l.user_id = u.id
        JOIN books b ON l.book_id = b.id
        ORDER BY l.issue_date DESC
    """
    history = db.query_db(query)
    return render_template('transactions.html', transactions=history, is_admin=True)


# --- USER / MEMBER SECTION ---

@app.route('/user')
def user_dashboard():
    if not session.get('username'):
        return redirect(url_for('login'))

    user_id = session['user_id']

    # 1. Update and Check Fines
    total_fine = update_fines(user_id)
    if total_fine > 0:
        flash(
            f"OVERDUE WARNING: You have an outstanding fine of ₱{total_fine}. Please return overdue books on time to avoid further charges.",
            "danger")

    user_role = session.get('role', 'Student')
    borrow_limit = 20 if user_role == 'Instructor' else 5
    search_query = request.args.get('search', '')

    # Fetch recommendations using your ML logic
    recs = get_recommendations(user_id)

    # Sync: Fetch books ensuring description and barcode are included for user.html
    if search_query:
        books = db.query_db(
            "SELECT * FROM books WHERE title LIKE ? OR author LIKE ? OR publisher LIKE ? OR barcode LIKE ? ORDER BY id DESC",
            (f'%{search_query}%', f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'))
    else:
        books = db.query_db("SELECT * FROM books ORDER BY id DESC")

    return render_template('user.html',
                           books=books,
                           recommendations=recs,
                           limit=borrow_limit,
                           role=user_role,
                           total_fine=total_fine)


@app.route('/checkout/<int:book_id>', methods=['GET', 'POST'])
def checkout_book(book_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))

    user_role = session.get('role', 'Student')
    borrow_limit = 20 if user_role == 'Instructor' else 5

    try:
        requested_qty = int(request.form.get('quantity', 1)) if request.method == 'POST' else 1
    except ValueError:
        requested_qty = 1

    active_loans = db.query_db("SELECT COUNT(*) as count FROM loans WHERE user_id = ? AND return_date IS NULL",
                               (session['user_id'],), one=True)
    current_borrowed = active_loans['count'] if active_loans else 0

    if current_borrowed + requested_qty > borrow_limit:
        flash(f"Limit exceeded! You can only borrow {borrow_limit} books.", "danger")
        return redirect(url_for('user_dashboard'))

    book_in_db = db.query_db("SELECT quantity, title FROM books WHERE id = ?", (book_id,), one=True)
    if not book_in_db or book_in_db['quantity'] < requested_qty:
        flash(f"Not enough copies available.", "warning")
        return redirect(url_for('user_dashboard'))

    due_date = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d')

    for _ in range(requested_qty):
        db.query_db("INSERT INTO loans (book_id, user_id, issue_date, due_date) VALUES (?, ?, date('now'), ?)",
                    (book_id, session['user_id'], due_date))

    db.query_db("UPDATE books SET quantity = quantity - ? WHERE id = ?", (requested_qty, book_id))

    flash(f"Borrowed '{book_in_db['title']}'. Due: {due_date}", "success")
    return redirect(url_for('user_dashboard'))


# --- AI CHAT LOGIC ---

@app.route('/ai_chat', methods=['POST'])
def ai_chat():
    data = request.json
    user_message = data.get('message', '').strip()
    user_id = session.get('user_id')

    if not user_id:
        return jsonify({"reply": "Session expired."})

    db.query_db("INSERT INTO messages (user_id, sender_name, content, is_admin_reply) VALUES (?, ?, ?, 0)",
                (user_id, session.get('username'), user_message))

    if data.get('is_admin'):
        target_user = data.get('target_user')
        db.query_db("INSERT INTO messages (user_id, sender_name, content, is_admin_reply) VALUES (?, ?, ?, 1)",
                    (target_user, 'Admin', user_message))
        return jsonify({"status": "Admin reply saved"})

    if "borrow" in user_message.lower() or "limit" in user_message.lower():
        role = session.get('role', 'Student')
        limit = 20 if role == 'Instructor' else 5
        reply = f"As an {role}, you can borrow up to {limit} books for 10 days. Fines for overdue items are 20 pesos per day."
    elif "recommend" in user_message.lower():
        reply = "I've updated your recommendations on the dashboard based on your reading history!"
    elif "fine" in user_message.lower() or "pay" in user_message.lower():
        reply = "Our library policy charges 20 pesos per day for overdue returns. You can view your current fine on the dashboard alert."
    else:
        reply = str(chatbot.get_response(user_message))

    db.query_db("INSERT INTO messages (user_id, sender_name, content, is_admin_reply) VALUES (?, ?, ?, 1)",
                (user_id, 'AI Librarian', reply))

    return jsonify({"reply": reply})


@app.route('/get_messages')
def get_messages():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])

    query = "SELECT content, is_admin_reply FROM messages WHERE user_id = ? ORDER BY timestamp ASC"
    messages = db.query_db(query, (user_id,))
    return jsonify(messages)


# --- SYSTEM MANAGEMENT ROUTES ---

@app.route('/manage_books')
def manage_books():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    books = db.query_db("SELECT * FROM books")
    return render_template('manage_books.html', books=books)


@app.route('/view_users')
def view_users():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    users = db.query_db("SELECT id, username, firstname, lastname, role FROM users")
    return render_template('view_users.html', all_users=users)


@app.route('/transactions_log')
def transactions_log():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    query = """
        SELECT u.username AS user_name, b.title AS book_title, b.author AS book_author, 
               l.issue_date, l.due_date, l.return_date, l.fine_amount
        FROM loans l
        JOIN users u ON l.user_id = u.id
        JOIN books b ON l.book_id = b.id
        WHERE u.role != 'admin'
        ORDER BY l.issue_date DESC
    """
    history = db.query_db(query)
    return render_template('transactions.html', transactions=history, is_admin=True)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)