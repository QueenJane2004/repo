import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
import random
import string
import re
import db

app = Flask(__name__)

# IMPORTANT: Render-safe secret key
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret")

db.init_db()

# =========================
# CHATBOT RULES
# =========================
CHAT_RULES = [
    (r'\b(hi|hello|hey)\b', "Hello! 👋 Ask me about books, borrowing, or fines."),
    (r'\b(fine|overdue)\b', "₱20 per day overdue fee applies."),
    (r'\b(borrow)\b', "You can borrow books from the dashboard."),
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
            session['firstname'] = user.get('firstname', 'User')
            session['role'] = user['role']

            return redirect(url_for('user_dashboard'))

        flash("Invalid credentials", "danger")

    return render_template('login.html')


@app.route('/user')
def user_dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    books = db.query_db("SELECT * FROM books ORDER BY id DESC")

    # SAFE DEFAULT (FIXES YOUR ERROR)
    total_fine = 0
    limit = 5

    try:
        result = db.query_db("""
            SELECT COALESCE(SUM(fine), 0) as total
            FROM loans
            WHERE user_id = %s AND return_date IS NULL
        """, (session['user_id'],), one=True)

        total_fine = result['total'] if result else 0

    except Exception as e:
        print("Fine error:", e)

    return render_template(
        'user.html',
        books=books,
        total_fine=total_fine,
        limit=limit
    )


@app.route('/checkout/<int:book_id>', methods=['POST'])
def checkout(book_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))

    book = db.query_db("SELECT * FROM books WHERE id = %s", (book_id,), one=True)

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
    return jsonify({"reply": rule_based_reply(msg)})


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


if __name__ == '__main__':
    app.run(debug=True)