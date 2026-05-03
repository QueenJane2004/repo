import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
import random
import string
import re
import db

app = Flask(__name__)
app.secret_key = "library_super_secret_key"

db.init_db()

# =========================
# CHATBOT RULES
# =========================

CHAT_RULES = [
    (r'\b(hi|hello|hey)\b', "Hello! 👋 Ask me about books, borrowing, or fines."),
    (r'\b(fine|overdue)\b', "₱20 per day overdue fee applies."),
    (r'\b(borrow)\b', "You can borrow books from your dashboard."),
    (r'\b(return)\b', "Return books at the library counter."),
]

COMPILED_RULES = [(re.compile(p, re.IGNORECASE), r) for p, r in CHAT_RULES]


def rule_based_reply(msg):
    for p, r in COMPILED_RULES:
        if p.search(msg):
            return r
    return "Ask me about borrowing, books, or fines."


# =========================
# ROUTES
# =========================

@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db.query_db(
            "SELECT * FROM users WHERE username = %s AND password = %s",
            (request.form.get('username'), request.form.get('password')),
            one=True
        )

        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['firstname'] = user.get('firstname', 'User')

            return redirect(url_for(
                'admin_dashboard' if user['role'] == 'admin' else 'user_dashboard'
            ))

        flash("Invalid credentials", "danger")

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            db.query_db("""
                INSERT INTO users (username, password, firstname, lastname, role)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                request.form.get('username'),
                request.form.get('password'),
                request.form.get('firstname'),
                request.form.get('lastname'),
                request.form.get('role', 'Student')
            ))

            flash("Registered successfully", "success")
            return redirect(url_for('login'))

        except Exception as e:
            print(e)
            flash("Registration failed", "danger")

    return render_template('register.html')


@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    return render_template('admin.html',
        users=db.query_db("SELECT COUNT(*) as c FROM users", one=True)['c'],
        books=db.query_db("SELECT COUNT(*) as c FROM books", one=True)['c'],
        loans=db.query_db("SELECT COUNT(*) as c FROM loans WHERE return_date IS NULL", one=True)['c'],
        all_users=db.query_db("SELECT * FROM users"),
        books_list=db.query_db("SELECT * FROM books ORDER BY id DESC")
    )


@app.route('/add_book', methods=['POST'])
def add_book():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    title = request.form.get('title')
    author = request.form.get('author')

    if not title or not author:
        flash("Title and Author required", "danger")
        return redirect('/admin')

    barcode = ''.join(random.choices(string.digits, k=13))

    try:
        db.query_db("""
            INSERT INTO books (title, author, publisher, image_url, description, barcode, isbn, quantity, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            title,
            author,
            request.form.get('publisher', 'Unknown'),
            '/static/uploads/default.png',
            f"{title} by {author}",
            barcode,
            request.form.get('isbn'),
            request.form.get('quantity', 1),
            'Available'
        ))

        flash("Book added!", "success")

    except Exception as e:
        print(e)
        flash("Error adding book", "danger")

    return redirect('/admin')


@app.route('/user')
def user_dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    books = db.query_db("SELECT * FROM books ORDER BY id DESC")

    return render_template('user.html', books=books)


@app.route('/checkout/<int:book_id>', methods=['POST'])
def checkout(book_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))

    book = db.query_db(
        "SELECT * FROM books WHERE id = %s",
        (book_id,),
        one=True
    )

    if not book:
        flash("Book not found", "danger")
        return redirect('/user')

    if book['quantity'] <= 0:
        flash("Not available", "warning")
        return redirect('/user')

    db.query_db("""
        INSERT INTO loans (book_id, user_id, issue_date, due_date)
        VALUES (%s,%s,%s,%s)
    """, (
        book_id,
        session['user_id'],
        datetime.now().date(),
        (datetime.now() + timedelta(days=10)).date()
    ))

    db.query_db(
        "UPDATE books SET quantity = quantity - 1 WHERE id = %s",
        (book_id,)
    )

    flash("Book borrowed!", "success")
    return redirect('/user')


@app.route('/ai_chat', methods=['POST'])
def ai_chat():
    msg = request.json.get('message', '')

    reply = rule_based_reply(msg)

    return jsonify({"reply": reply})


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


if __name__ == '__main__':
    app.run(debug=True)