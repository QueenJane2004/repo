import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
import random
import string
import re
import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret")

# INIT DB SAFELY
try:
    db.init_db()
except Exception as e:
    print("DB INIT ERROR:", e)


# =========================
# CHATBOT
# =========================

CHAT_RULES = [
    (r'\b(hi|hello|hey)\b', "Hello! 👋 Ask me about books, borrowing, or fines."),
    (r'\b(fine|overdue)\b', "₱20 per day overdue fee applies."),
    (r'\b(borrow)\b', "You can borrow books from your dashboard."),
    (r'\b(return)\b', "Return books at the library counter."),
]

COMPILED_RULES = [(re.compile(p, re.I), r) for p, r in CHAT_RULES]


def rule_based_reply(msg):
    for p, r in COMPILED_RULES:
        if p.search(msg):
            return r
    return "Ask me about books, borrowing, or fines."


# =========================
# ROUTES
# =========================

@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            user = db.query_db(
                "SELECT * FROM users WHERE username = ? AND password = ?",
                (request.form.get('username'), request.form.get('password')),
                one=True
            )

            if user:
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['firstname'] = user.get('firstname', 'User')

                return redirect('/user')

            flash("Invalid credentials", "danger")

        except Exception as e:
            print("LOGIN ERROR:", e)
            flash("Server error", "danger")

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            db.query_db("""
                INSERT INTO users (username, password, firstname, lastname, role)
                VALUES (?, ?, ?, ?, ?)
            """, (
                request.form.get('username'),
                request.form.get('password'),
                request.form.get('firstname'),
                request.form.get('lastname'),
                request.form.get('role', 'Student')
            ))

            flash("Registered successfully", "success")
            return redirect('/login')

        except Exception as e:
            print("REGISTER ERROR:", e)
            flash("Registration failed", "danger")

    return render_template('register.html')


@app.route('/user')
def user_dashboard():
    if not session.get('user_id'):
        return redirect('/login')

    books = db.query_db("SELECT * FROM books ORDER BY id DESC") or []

    return render_template('user.html', books=books)


@app.route('/add_book', methods=['POST'])
def add_book():
    if session.get('role') != 'admin':
        return redirect('/login')

    try:
        db.query_db("""
            INSERT INTO books (title, author, publisher, image_url, description, barcode, quantity, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            request.form.get('title'),
            request.form.get('author'),
            request.form.get('publisher', 'Unknown'),
            '/static/uploads/default.png',
            request.form.get('title') + " book",
            ''.join(random.choices(string.digits, k=13)),
            int(request.form.get('quantity', 1)),
            'Available'
        ))

        flash("Book added!", "success")

    except Exception as e:
        print("ADD BOOK ERROR:", e)
        flash("Error adding book", "danger")

    return redirect('/user')


@app.route('/checkout/<int:book_id>', methods=['POST'])
def checkout(book_id):
    if not session.get('user_id'):
        return redirect('/login')

    book = db.query_db("SELECT * FROM books WHERE id = ?", (book_id,), one=True)

    if not book:
        flash("Book not found", "danger")
        return redirect('/user')

    if book['quantity'] <= 0:
        flash("Not available", "warning")
        return redirect('/user')

    db.query_db("""
        INSERT INTO loans (book_id, user_id, issue_date, due_date)
        VALUES (?, ?, ?, ?)
    """, (
        book_id,
        session['user_id'],
        datetime.now().date(),
        (datetime.now() + timedelta(days=10)).date()
    ))

    db.query_db(
        "UPDATE books SET quantity = quantity - 1 WHERE id = ?",
        (book_id,)
    )

    flash("Book borrowed!", "success")
    return redirect('/user')


@app.route('/ai_chat', methods=['POST'])
def ai_chat():
    msg = request.json.get('message', '')
    return jsonify({"reply": rule_based_reply(msg)})


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


if __name__ == '__main__':
    app.run(debug=True)