"""
Personal Blog Website - Flask Backend
Level 1 - Easy Project

Features:
- User authentication (register/login/logout)
- Blog CRUD (create, read, update, delete)
- SQLite database via SQLAlchemy
- Server-rendered templates + small JS enhancements
"""

import os
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import DictLoader
from flask import Response

TEMPLATES ={
    'create_post.html':
      '{% extends "base.html" %}\n{% block title %}New Post | MyBlog{% endblock %}\n\n{% block content %}\n    <div class="form-card">\n        <h1>Create New Post</h1>\n        <form method="POST" id="postForm">\n            <label for="title">Title</label>\n            <input type="text" id="title" name="title" placeholder="Enter a catchy title" required>\n\n            <label for="content">Content</label>\n            <textarea id="content" name="content" rows="12" placeholder="Write your post here..." required></textarea>\n            <p class="char-count"><span id="charCount">0</span> characters</p>\n\n            <div class="form-actions">\n                <button type="submit" class="btn btn-primary">Publish Post</button>\n                <a href="{{ url_for(\'index\') }}" class="btn btn-secondary">Cancel</a>\n            </div>\n        </form>\n    </div>\n{% endblock %}\n', 'login.html': '{% extends "base.html" %}\n{% block title %}Login | MyBlog{% endblock %}\n\n{% block content %}\n    <div class="form-card form-narrow">\n        <h1>Welcome Back</h1>\n        <form method="POST">\n            <label for="username">Username</label>\n            <input type="text" id="username" name="username" required autofocus>\n\n            <label for="password">Password</label>\n            <input type="password" id="password" name="password" required>\n\n            <div class="form-actions">\n                <button type="submit" class="btn btn-primary btn-block">Log In</button>\n            </div>\n        </form>\n        <p class="form-footnote">Don\'t have an account? <a href="{{ url_for(\'register\') }}">Sign up</a></p>\n    </div>\n{% endblock %}\n', 'index.html': '{% extends "base.html" %}\n{% block title %}Home | MyBlog{% endblock %}\n\n{% block content %}\n    <section class="hero">\n        <h1>Welcome to MyBlog</h1>\n        <p>Thoughts, stories, and ideas — all in one place.</p>\n    </section>\n\n    <section class="post-grid">\n        {% if posts %}\n            {% for post in posts %}\n                <article class="post-card">\n                    <h2><a href="{{ url_for(\'view_post\', post_id=post.id) }}">{{ post.title }}</a></h2>\n                    <p class="post-meta">By {{ post.author.username }} · {{ post.created_at.strftime(\'%b %d, %Y\') }}</p>\n                    <p class="post-excerpt">{{ post.excerpt() }}</p>\n                    <a class="read-more" href="{{ url_for(\'view_post\', post_id=post.id) }}">Read more →</a>\n                </article>\n            {% endfor %}\n        {% else %}\n            <p class="empty-state">No posts yet. {% if current_user.is_authenticated %}<a href="{{ url_for(\'create_post\') }}">Write the first one!</a>{% else %}<a href="{{ url_for(\'login\') }}">Log in</a> to write the first one.{% endif %}</p>\n        {% endif %}\n    </section>\n{% endblock %}\n', 'edit_post.html': '{% extends "base.html" %}\n{% block title %}Edit Post | MyBlog{% endblock %}\n\n{% block content %}\n    <div class="form-card">\n        <h1>Edit Post</h1>\n        <form method="POST" id="postForm">\n            <label for="title">Title</label>\n            <input type="text" id="title" name="title" value="{{ post.title }}" required>\n\n            <label for="content">Content</label>\n            <textarea id="content" name="content" rows="12" required>{{ post.content }}</textarea>\n            <p class="char-count"><span id="charCount">0</span> characters</p>\n\n            <div class="form-actions">\n                <button type="submit" class="btn btn-primary">Save Changes</button>\n                <a href="{{ url_for(\'view_post\', post_id=post.id) }}" class="btn btn-secondary">Cancel</a>\n            </div>\n        </form>\n    </div>\n{% endblock %}\n', 'error.html': '{% extends "base.html" %}\n{% block title %}Error {{ code }} | MyBlog{% endblock %}\n\n{% block content %}\n    <div class="error-page">\n        <h1>{{ code }}</h1>\n        <p>{{ message }}</p>\n        <a class="btn btn-primary" href="{{ url_for(\'index\') }}">Back to Home</a>\n    </div>\n{% endblock %}\n', 'register.html': '{% extends "base.html" %}\n{% block title %}Sign Up | MyBlog{% endblock %}\n\n{% block content %}\n    <div class="form-card form-narrow">\n        <h1>Create Account</h1>\n        <form method="POST">\n            <label for="username">Username</label>\n            <input type="text" id="username" name="username" required autofocus>\n\n            <label for="email">Email</label>\n            <input type="email" id="email" name="email" required>\n\n            <label for="password">Password</label>\n            <input type="password" id="password" name="password" required minlength="6">\n\n            <label for="confirm_password">Confirm Password</label>\n            <input type="password" id="confirm_password" name="confirm_password" required minlength="6">\n\n            <div class="form-actions">\n                <button type="submit" class="btn btn-primary btn-block">Sign Up</button>\n            </div>\n        </form>\n        <p class="form-footnote">Already have an account? <a href="{{ url_for(\'login\') }}">Log in</a></p>\n    </div>\n{% endblock %}\n', 'base.html': '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>{% block title %}My Blog{% endblock %}</title>\n    <link rel="stylesheet" href="{{ url_for(\'static\', filename=\'css/style.css\') }}">\n</head>\n<body>\n    <header class="navbar">\n        <div class="navbar-inner">\n            <a href="{{ url_for(\'index\') }}" class="brand">✍️ MyBlog</a>\n            <nav class="nav-links">\n                {% if current_user.is_authenticated %}\n                    <a href="{{ url_for(\'create_post\') }}">New Post</a>\n                    <span class="nav-user">Hi, {{ current_user.username }}</span>\n                    <a href="{{ url_for(\'logout\') }}">Logout</a>\n                {% else %}\n                    <a href="{{ url_for(\'login\') }}">Login</a>\n                    <a href="{{ url_for(\'register\') }}" class="btn-link">Sign Up</a>\n                {% endif %}\n            </nav>\n            <button class="nav-toggle" id="navToggle" aria-label="Toggle menu">☰</button>\n        </div>\n    </header>\n\n    <main class="container">\n        {% with messages = get_flashed_messages(with_categories=true) %}\n            {% if messages %}\n                <div class="flash-container">\n                    {% for category, message in messages %}\n                        <div class="flash flash-{{ category }}">{{ message }}</div>\n                    {% endfor %}\n                </div>\n            {% endif %}\n        {% endwith %}\n\n        {% block content %}{% endblock %}\n    </main>\n\n    <footer class="footer">\n        <p>&copy; 2026 MyBlog — Built with Flask</p>\n    </footer>\n\n    <script src="{{ url_for(\'static\', filename=\'js/script.js\') }}"></script>\n</body>\n</html>\n', 'post.html': '{% extends "base.html" %}\n{% block title %}{{ post.title }} | MyBlog{% endblock %}\n\n{% block content %}\n    <article class="post-detail">\n        <h1>{{ post.title }}</h1>\n        <p class="post-meta">\n            By {{ post.author.username }} · Published {{ post.created_at.strftime(\'%b %d, %Y at %I:%M %p\') }}\n            {% if post.updated_at and post.updated_at != post.created_at %}\n                · Updated {{ post.updated_at.strftime(\'%b %d, %Y\') }}\n            {% endif %}\n        </p>\n        <div class="post-content">{{ post.content|replace(\'\\n\', \'<br>\')|safe }}</div>\n\n        {% if current_user.is_authenticated and current_user.id == post.user_id %}\n            <div class="post-actions">\n                <a class="btn btn-secondary" href="{{ url_for(\'edit_post\', post_id=post.id) }}">Edit</a>\n                <form action="{{ url_for(\'delete_post\', post_id=post.id) }}" method="POST" class="inline-form" onsubmit="return confirm(\'Delete this post permanently?\');">\n                    <button type="submit" class="btn btn-danger">Delete</button>\n                </form>\n            </div>\n        {% endif %}\n\n        <a class="back-link" href="{{ url_for(\'index\') }}">← Back to all posts</a>\n    </article>\n{% endblock %}\n'}
CSS_CONTENT = '     :root {\n    --primary: #2b3a67;\n    --primary-light: #496ddb;\n    --accent: #ff7e5f;\n    --bg: #f7f8fc;\n    --card-bg: #ffffff;\n    --text: #232a3b;\n    --muted: #6b7280;\n    --border: #e3e6ee;\n    --danger: #e0554b;\n    --success: #2e8b57;\n    --radius: 10px;\n}\n\n* {\n    box-sizing: border-box;\n}\n\nbody {\n    margin: 0;\n    font-family: \'Segoe UI\', system-ui, -apple-system, Roboto, sans-serif;\n    background: var(--bg);\n    color: var(--text);\n    line-height: 1.6;\n    min-height: 100vh;\n    display: flex;\n    flex-direction: column;\n}\n\na {\n    color: var(--primary-light);\n    text-decoration: none;\n}\n\na:hover {\n    text-decoration: underline;\n}\n\n/* Navbar */\n.navbar {\n    background: var(--primary);\n    color: white;\n    position: sticky;\n    top: 0;\n    z-index: 10;\n}\n\n.navbar-inner {\n    max-width: 1000px;\n    margin: 0 auto;\n    display: flex;\n    align-items: center;\n    justify-content: space-between;\n    padding: 0.9rem 1.5rem;\n}\n\n.brand {\n    color: white;\n    font-weight: 700;\n    font-size: 1.25rem;\n}\n\n.brand:hover {\n    text-decoration: none;\n    opacity: 0.9;\n}\n\n.nav-links {\n    display: flex;\n    align-items: center;\n    gap: 1.25rem;\n}\n\n.nav-links a {\n    color: #dce3ff;\n}\n\n.nav-links a:hover {\n    color: white;\n}\n\n.nav-user {\n    color: #aab8f5;\n    font-size: 0.9rem;\n}\n\n.btn-link {\n    background: var(--accent);\n    color: white !important;\n    padding: 0.4rem 0.9rem;\n    border-radius: 20px;\n}\n\n.nav-toggle {\n    display: none;\n    background: none;\n    border: none;\n    color: white;\n    font-size: 1.5rem;\n    cursor: pointer;\n}\n\n/* Container */\n.container {\n    max-width: 1000px;\n    margin: 0 auto;\n    padding: 2rem 1.5rem;\n    flex: 1;\n    width: 100%;\n}\n\n/* Flash messages */\n.flash-container {\n    margin-bottom: 1.5rem;\n}\n\n.flash {\n    padding: 0.8rem 1.1rem;\n    border-radius: var(--radius);\n    margin-bottom: 0.6rem;\n    font-size: 0.95rem;\n}\n\n.flash-success {\n    background: #e3f6ea;\n    color: var(--success);\n    border: 1px solid #b9e6c9;\n}\n\n.flash-danger {\n    background: #fdeceb;\n    color: var(--danger);\n    border: 1px solid #f7c6c2;\n}\n\n.flash-info {\n    background: #eaf0ff;\n    color: var(--primary-light);\n    border: 1px solid #c9d6ff;\n}\n\n/* Hero */\n.hero {\n    text-align: center;\n    margin-bottom: 2.5rem;\n}\n\n.hero h1 {\n    font-size: 2.2rem;\n    margin-bottom: 0.3rem;\n    color: var(--primary);\n}\n\n.hero p {\n    color: var(--muted);\n}\n\n/* Post grid */\n.post-grid {\n    display: grid;\n    gap: 1.25rem;\n}\n\n.post-card {\n    background: var(--card-bg);\n    border: 1px solid var(--border);\n    border-radius: var(--radius);\n    padding: 1.5rem;\n    transition: box-shadow 0.2s, transform 0.2s;\n}\n\n.post-card:hover {\n    box-shadow: 0 6px 18px rgba(43, 58, 103, 0.08);\n    transform: translateY(-2px);\n}\n\n.post-card h2 {\n    margin: 0 0 0.3rem;\n    font-size: 1.3rem;\n}\n\n.post-meta {\n    color: var(--muted);\n    font-size: 0.85rem;\n    margin: 0 0 0.6rem;\n}\n\n.post-excerpt {\n    color: var(--text);\n    margin-bottom: 0.6rem;\n}\n\n.read-more {\n    font-weight: 600;\n    font-size: 0.9rem;\n}\n\n.empty-state {\n    text-align: center;\n    color: var(--muted);\n    padding: 2rem 0;\n}\n\n/* Post detail */\n.post-detail {\n    background: var(--card-bg);\n    border: 1px solid var(--border);\n    border-radius: var(--radius);\n    padding: 2rem;\n}\n\n.post-detail h1 {\n    margin-top: 0;\n    color: var(--primary);\n}\n\n.post-content {\n    margin: 1.5rem 0;\n    white-space: pre-wrap;\n}\n\n.post-actions {\n    display: flex;\n    gap: 0.7rem;\n    margin: 1.5rem 0;\n}\n\n.inline-form {\n    display: inline;\n}\n\n.back-link {\n    display: inline-block;\n    margin-top: 1rem;\n}\n\n/* Forms */\n.form-card {\n    background: var(--card-bg);\n    border: 1px solid var(--border);\n    border-radius: var(--radius);\n    padding: 2rem;\n    max-width: 650px;\n    margin: 0 auto;\n}\n\n.form-narrow {\n    max-width: 400px;\n}\n\n.form-card h1 {\n    margin-top: 0;\n    color: var(--primary);\n    font-size: 1.6rem;\n}\n\nlabel {\n    display: block;\n    font-weight: 600;\n    margin: 1rem 0 0.4rem;\n    font-size: 0.9rem;\n}\n\ninput[type="text"],\ninput[type="email"],\ninput[type="password"],\ntextarea {\n    width: 100%;\n    padding: 0.7rem 0.9rem;\n    border: 1px solid var(--border);\n    border-radius: 8px;\n    font-size: 1rem;\n    font-family: inherit;\n}\n\ninput:focus,\ntextarea:focus {\n    outline: none;\n    border-color: var(--primary-light);\n    box-shadow: 0 0 0 3px rgba(73, 109, 219, 0.15);\n}\n\ntextarea {\n    resize: vertical;\n}\n\n.char-count {\n    font-size: 0.8rem;\n    color: var(--muted);\n    margin-top: 0.3rem;\n}\n\n.form-actions {\n    display: flex;\n    gap: 0.7rem;\n    margin-top: 1.5rem;\n}\n\n.form-footnote {\n    text-align: center;\n    margin-top: 1.2rem;\n    font-size: 0.9rem;\n    color: var(--muted);\n}\n\n/* Buttons */\n.btn {\n    display: inline-block;\n    padding: 0.65rem 1.3rem;\n    border-radius: 8px;\n    border: none;\n    font-size: 0.95rem;\n    font-weight: 600;\n    cursor: pointer;\n    text-decoration: none;\n}\n\n.btn-primary {\n    background: var(--primary-light);\n    color: white;\n}\n\n.btn-primary:hover {\n    background: #3a59c4;\n}\n\n.btn-secondary {\n    background: #eceefb;\n    color: var(--primary);\n}\n\n.btn-secondary:hover {\n    background: #dde1f7;\n}\n\n.btn-danger {\n    background: var(--danger);\n    color: white;\n}\n\n.btn-danger:hover {\n    background: #c8463d;\n}\n\n.btn-block {\n    width: 100%;\n}\n\n/* Error page */\n.error-page {\n    text-align: center;\n    padding: 4rem 0;\n}\n\n.error-page h1 {\n    font-size: 4rem;\n    color: var(--primary);\n    margin-bottom: 0;\n}\n\n/* Footer */\n.footer {\n    text-align: center;\n    padding: 1.5rem;\n    color: var(--muted);\n    font-size: 0.85rem;\n}\n\n/* Responsive */\n@media (max-width: 640px) {\n    .nav-links {\n        display: none;\n        flex-direction: column;\n        align-items: flex-start;\n        gap: 0.8rem;\n        position: absolute;\n        top: 100%;\n        left: 0;\n        right: 0;\n        background: var(--primary);\n        padding: 1rem 1.5rem;\n    }\n\n    .nav-links.open {\n        display: flex;\n    }\n\n    .nav-toggle {\n        display: block;\n    }\n\n    .form-card {\n        padding: 1.3rem;\n    }\n\n    .post-detail {\n        padding: 1.3rem;\n    }\n}\n'
JS_CONTENT = 'document.addEventListener("DOMContentLoaded", function () {\n    // Mobile nav toggle\n    const navToggle = document.getElementById("navToggle");\n    const navLinks = document.querySelector(".nav-links");\n    if (navToggle && navLinks) {\n        navToggle.addEventListener("click", function () {\n            navLinks.classList.toggle("open");\n        });\n    }\n\n    // Live character counter for post forms\n    const contentField = document.getElementById("content");\n    const charCount = document.getElementById("charCount");\n    if (contentField && charCount) {\n        const updateCount = () => { charCount.textContent = contentField.value.length; };\n        updateCount();\n        contentField.addEventListener("input", updateCount);\n    }\n\n    // Auto-dismiss flash messages after 5 seconds\n    document.querySelectorAll(".flash").forEach(function (el) {\n        setTimeout(() => {\n            el.style.transition = "opacity 0.5s";\n            el.style.opacity = "0";\n            setTimeout(() => el.remove(), 500);\n        }, 5000);\n    });\n});\n'


BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

DB_PATH = os.path.join(BASE_DIR, "blog.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"
# ----------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    posts = db.relationship("Post", backref="author", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    def excerpt(self, length=180):
        text = self.content.strip()
        return text[:length] + ("..." if len(text) > length else "")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ----------------------------------------------------------------------
# Public routes
# ----------------------------------------------------------------------

@app.route("/")
def index():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template("index.html", posts=posts)


@app.route("/post/<int:post_id>")
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template("post.html", post=post)


# ----------------------------------------------------------------------
# Auth routes
# ----------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("Username already taken.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Account created successfully. Please log in.", "success")
            return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Logged in successfully.", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))
        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------
# Blog CRUD routes (require login)
# ----------------------------------------------------------------------

@app.route("/post/new", methods=["GET", "POST"])
@login_required
def create_post():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()

        if not title or not content:
            flash("Title and content are required.", "danger")
        else:
            post = Post(title=title, content=content, author=current_user)
            db.session.add(post)
            db.session.commit()
            flash("Post created successfully.", "success")
            return redirect(url_for("view_post", post_id=post.id))

    return render_template("create_post.html")


@app.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        abort(403)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()

        if not title or not content:
            flash("Title and content are required.", "danger")
        else:
            post.title = title
            post.content = content
            db.session.commit()
            flash("Post updated successfully.", "success")
            return redirect(url_for("view_post", post_id=post.id))

    return render_template("edit_post.html", post=post)


@app.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        abort(403)

    db.session.delete(post)
    db.session.commit()
    flash("Post deleted.", "info")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------
# Error handlers
# ----------------------------------------------------------------------

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="You don't have permission to do that."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404



app.jinja_loader = DictLoader(TEMPLATES)

@app.route('/static/css/style.css')
def embedded_css():
    return Response(CSS_CONTENT, mimetype='text/css')

@app.route('/static/js/script.js')
def embedded_js():
    return Response(JS_CONTENT, mimetype='application/javascript')


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def create_tables():
    with app.app_context():
        db.create_all()


if __name__ == "__main__":
    create_tables()
    app.run(host="0.0.0.0", port=5000, debug=False)