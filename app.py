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

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
        # ... (your existing code to fetch user and check password)
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['firstname'] = user['firstname']
            session['role'] = user['role']  # Make sure role is in session!

            # Redirect based on role
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))
    
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
def admin_dashboard():
    # Force Login
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Redirect Members away from Admin page
    if session.get('role') != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('user_dashboard'))

    # Fetch data for admin.html
    b_count = db.query_db("SELECT COUNT(*) as count FROM books", one=True)['count']
    u_count = db.query_db("SELECT COUNT(*) as count FROM users WHERE role='member'", one=True)['count']
    l_count = db.query_db("SELECT COUNT(*) as count FROM loans", one=True)['count']
    all_users = db.query_db("SELECT * FROM users")
    trending = db.query_db("SELECT * FROM books LIMIT 5")

    return render_template('admin.html', 
                           books_count=b_count, 
                           users_count=u_count, 
                           borrowed_count=l_count, 
                           all_users=all_users, 
                           trending_books=trending)

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
    # Synchronized with your filename: activity_logs.html
    return render_template('activity_logs.html', logs=logs)

# --- ACTION ROUTES ---


@app.route('/checkout/<int:book_id>', methods=['POST'])
def checkout(book_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # For now, just a success message
    flash(f"Book {book_id} requested!", "success")
    return redirect(url_for('user_dashboard'))



@app.route('/add_book', methods=['POST'])
@login_required
@admin_required
def add_book():
    title = request.form.get('title')
    author = request.form.get('author')
    publisher = request.form.get('publisher')
    description = request.form.get('description')
    quantity = request.form.get('quantity', 1)
    
    barcode = str(uuid.uuid4().hex[:8]).upper()
    image_path = None 

    # Handle Image Upload
    if 'book_image' in request.files:
        file = request.files['book_image']
        if file and allowed_file(file.filename):
            filename = secure_filename(f"{barcode}_{file.filename}")
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
        db.query_db("UPDATE books SET quantity = ? WHERE id = ?", (data.get('quantity'), data.get('book_id')))
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 400


@app.route('/borrow_books')
@login_required
def borrow_books():
    # Your logic here
    return render_template('borrow.html')



# --- USER ROUTES ---

@app.route('/user')
def user_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Security: If an admin tries to go to /user, send them back to /admin
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))

    # Get the books from the database
    books = db.query_db("SELECT * FROM books")
    recs = db.query_db("SELECT * FROM books ORDER BY RANDOM() LIMIT 4")
    
    # FIX: Define the variables your HTML is asking for
    user_limit = 5 
    fines = 0  # You can replace this with a SQL query later
    
    return render_template('user.html', 
                           books=books, 
                           recommendations=recs, 
                           limit=user_limit, 
                           total_fine=fines)

if __name__ == '__main__':
    app.run(debug=True)
