import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, g, request, session, redirect, url_for,
    render_template_string, flash, jsonify, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

# --------------------------------------------------------------------------
# APP CONFIG
# --------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "jobportal.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
app.config["DATABASE"] = DATABASE

# --------------------------------------------------------------------------
# DATABASE HELPERS (sqlite3 — swap-out instructions for MySQL/PostgreSQL
# are at the bottom of this file in the comments)
# --------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('jobseeker','employer')),
            phone TEXT DEFAULT '',
            location TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            skills TEXT DEFAULT '',
            company_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employer_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            job_type TEXT NOT NULL,
            salary TEXT DEFAULT '',
            posted_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (employer_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            applicant_id INTEGER NOT NULL,
            cover_letter TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            applied_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY (applicant_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(job_id, applicant_id)
        );
        """
    )
    db.commit()
    db.close()


# --------------------------------------------------------------------------
# AUTH HELPERS
# --------------------------------------------------------------------------

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user or user["role"] != role:
                flash("You don't have permission to view that page.", "danger")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# --------------------------------------------------------------------------
# TEMPLATES (Bootstrap 5, responsive, embedded as strings)
# --------------------------------------------------------------------------

BASE_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}Job Portal{% endblock %}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
<style>
  body { background:#f4f6f9; }
  .navbar-brand { font-weight:700; }
  .job-card { transition: transform .15s ease; border:none; border-radius:14px; }
  .job-card:hover { transform: translateY(-3px); box-shadow:0 8px 20px rgba(0,0,0,.08); }
  .badge-type { font-size:.75rem; }
  footer { color:#888; font-size:.85rem; }
  .hero { background:linear-gradient(135deg,#0d6efd,#6610f2); color:#fff; border-radius:18px; }
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark sticky-top">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}"><i class="bi bi-briefcase-fill"></i> JobPortal</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="nav">
      <ul class="navbar-nav ms-auto align-items-lg-center gap-1">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">Browse Jobs</a></li>
        {% if current_user %}
          {% if current_user['role'] == 'employer' %}
            <li class="nav-item"><a class="nav-link" href="{{ url_for('post_job') }}">Post a Job</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">My Jobs</a></li>
          {% else %}
            <li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">My Applications</a></li>
          {% endif %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('profile') }}">Profile</a></li>
          <li class="nav-item"><span class="nav-link text-warning">Hi, {{ current_user['name'] }}</span></li>
          <li class="nav-item"><a class="btn btn-outline-light btn-sm" href="{{ url_for('logout') }}">Logout</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
          <li class="nav-item"><a class="btn btn-warning btn-sm" href="{{ url_for('register') }}">Sign Up</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>

<div class="container mt-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
          {{ message }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>

<footer class="text-center my-5">
  &copy; {{ 2026 }} JobPortal — Built with Flask &amp; Bootstrap
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

INDEX_HTML = """
{% extends base %}
{% block title %}Browse Jobs{% endblock %}
{% block content %}
<div class="hero p-5 mb-4">
  <h1 class="fw-bold">Find your next opportunity</h1>
  <p class="mb-0">Search thousands of jobs posted by real employers.</p>
</div>

<form class="row g-2 mb-4" method="get" action="{{ url_for('index') }}">
  <div class="col-md-5">
    <input type="text" class="form-control" name="q" placeholder="Job title or keyword" value="{{ q }}">
  </div>
  <div class="col-md-3">
    <input type="text" class="form-control" name="location" placeholder="Location" value="{{ location }}">
  </div>
  <div class="col-md-3">
    <select class="form-select" name="job_type">
      <option value="">All Job Types</option>
      {% for jt in job_types %}
        <option value="{{ jt }}" {% if jt == job_type %}selected{% endif %}>{{ jt }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="col-md-1">
    <button class="btn btn-primary w-100" type="submit"><i class="bi bi-search"></i></button>
  </div>
</form>

<p class="text-muted">{{ jobs|length }} job(s) found</p>

<div class="row g-3">
  {% for job in jobs %}
  <div class="col-md-6 col-lg-4">
    <div class="card job-card h-100 shadow-sm p-3">
      <div class="card-body">
        <span class="badge bg-primary-subtle text-primary badge-type">{{ job['job_type'] }}</span>
        <h5 class="card-title mt-2">{{ job['title'] }}</h5>
        <p class="card-subtitle text-muted mb-2"><i class="bi bi-building"></i> {{ job['company'] }}</p>
        <p class="mb-1"><i class="bi bi-geo-alt"></i> {{ job['location'] }}</p>
        {% if job['salary'] %}<p class="mb-1"><i class="bi bi-cash"></i> {{ job['salary'] }}</p>{% endif %}
        <a href="{{ url_for('job_detail', job_id=job['id']) }}" class="btn btn-outline-primary btn-sm mt-2">View &amp; Apply</a>
      </div>
    </div>
  </div>
  {% else %}
  <p>No jobs match your search.</p>
  {% endfor %}
</div>
{% endblock %}
"""

JOB_DETAIL_HTML = """
{% extends base %}
{% block title %}{{ job['title'] }}{% endblock %}
{% block content %}
<div class="card shadow-sm p-4">
  <span class="badge bg-primary-subtle text-primary badge-type mb-2">{{ job['job_type'] }}</span>
  <h2>{{ job['title'] }}</h2>
  <p class="text-muted"><i class="bi bi-building"></i> {{ job['company'] }} &nbsp; | &nbsp; <i class="bi bi-geo-alt"></i> {{ job['location'] }}</p>
  {% if job['salary'] %}<p><strong>Salary:</strong> {{ job['salary'] }}</p>{% endif %}
  <hr>
  <p style="white-space:pre-wrap;">{{ job['description'] }}</p>
  <p class="text-muted small">Posted on {{ job['posted_at'] }}</p>

  {% if current_user and current_user['role'] == 'jobseeker' %}
    {% if already_applied %}
      <div class="alert alert-info">You already applied to this job. Status: <strong>{{ already_applied['status'] }}</strong></div>
    {% else %}
      <form method="post" action="{{ url_for('apply_job', job_id=job['id']) }}">
        <div class="mb-3">
          <label class="form-label">Cover Letter (optional)</label>
          <textarea class="form-control" name="cover_letter" rows="4" placeholder="Why are you a great fit?"></textarea>
        </div>
        <button class="btn btn-success" type="submit"><i class="bi bi-send"></i> Apply Now</button>
      </form>
    {% endif %}
  {% elif not current_user %}
    <a href="{{ url_for('login') }}" class="btn btn-success">Login to Apply</a>
  {% elif current_user['role'] == 'employer' and current_user['id'] == job['employer_id'] %}
    <a href="{{ url_for('job_applicants', job_id=job['id']) }}" class="btn btn-primary">View Applicants</a>
    <a href="{{ url_for('delete_job', job_id=job['id']) }}" class="btn btn-outline-danger"
       onclick="return confirm('Delete this job posting?');">Delete Job</a>
  {% endif %}
</div>
{% endblock %}
"""

LOGIN_HTML = """
{% extends base %}
{% block title %}Login{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-5">
    <div class="card shadow-sm p-4">
      <h3 class="mb-3 text-center">Welcome Back</h3>
      <form method="post">
        <div class="mb-3">
          <label class="form-label">Email</label>
          <input type="email" class="form-control" name="email" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Password</label>
          <input type="password" class="form-control" name="password" required>
        </div>
        <button class="btn btn-primary w-100" type="submit">Login</button>
      </form>
      <p class="text-center mt-3 mb-0">No account? <a href="{{ url_for('register') }}">Sign up</a></p>
    </div>
  </div>
</div>
{% endblock %}
"""

REGISTER_HTML = """
{% extends base %}
{% block title %}Sign Up{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card shadow-sm p-4">
      <h3 class="mb-3 text-center">Create your account</h3>
      <form method="post">
        <div class="mb-3">
          <label class="form-label">Full Name</label>
          <input type="text" class="form-control" name="name" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Email</label>
          <input type="email" class="form-control" name="email" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Password</label>
          <input type="password" class="form-control" name="password" minlength="6" required>
        </div>
        <div class="mb-3">
          <label class="form-label">I am a:</label>
          <select class="form-select" name="role" required>
            <option value="jobseeker">Job Seeker</option>
            <option value="employer">Employer</option>
          </select>
        </div>
        <button class="btn btn-primary w-100" type="submit">Sign Up</button>
      </form>
      <p class="text-center mt-3 mb-0">Already have an account? <a href="{{ url_for('login') }}">Login</a></p>
    </div>
  </div>
</div>
{% endblock %}
"""

DASHBOARD_EMPLOYER_HTML = """
{% extends base %}
{% block title %}My Jobs{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h3>My Job Postings</h3>
  <a href="{{ url_for('post_job') }}" class="btn btn-primary"><i class="bi bi-plus-circle"></i> Post New Job</a>
</div>
<div class="table-responsive">
<table class="table table-bordered bg-white align-middle">
  <thead class="table-dark"><tr><th>Title</th><th>Location</th><th>Type</th><th>Applicants</th><th>Posted</th><th>Actions</th></tr></thead>
  <tbody>
  {% for job in jobs %}
    <tr>
      <td>{{ job['title'] }}</td>
      <td>{{ job['location'] }}</td>
      <td>{{ job['job_type'] }}</td>
      <td><a href="{{ url_for('job_applicants', job_id=job['id']) }}">{{ job['app_count'] }} view</a></td>
      <td>{{ job['posted_at'] }}</td>
      <td>
        <a href="{{ url_for('job_detail', job_id=job['id']) }}" class="btn btn-sm btn-outline-secondary">View</a>
        <a href="{{ url_for('delete_job', job_id=job['id']) }}" class="btn btn-sm btn-outline-danger"
           onclick="return confirm('Delete this job?');">Delete</a>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="6">You haven't posted any jobs yet.</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endblock %}
"""

DASHBOARD_SEEKER_HTML = """
{% extends base %}
{% block title %}My Applications{% endblock %}
{% block content %}
<h3 class="mb-3">My Applications</h3>
<div class="table-responsive">
<table class="table table-bordered bg-white align-middle">
  <thead class="table-dark"><tr><th>Job Title</th><th>Company</th><th>Status</th><th>Applied On</th><th></th></tr></thead>
  <tbody>
  {% for app in applications %}
    <tr>
      <td>{{ app['title'] }}</td>
      <td>{{ app['company'] }}</td>
      <td>
        <span class="badge bg-{{ 'success' if app['status']=='Accepted' else ('danger' if app['status']=='Rejected' else 'secondary') }}">
          {{ app['status'] }}
        </span>
      </td>
      <td>{{ app['applied_at'] }}</td>
      <td><a href="{{ url_for('job_detail', job_id=app['job_id']) }}" class="btn btn-sm btn-outline-secondary">View Job</a></td>
    </tr>
  {% else %}
    <tr><td colspan="5">You haven't applied to any jobs yet. <a href="{{ url_for('index') }}">Browse jobs</a>.</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endblock %}
"""

POST_JOB_HTML = """
{% extends base %}
{% block title %}Post a Job{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-8">
    <div class="card shadow-sm p-4">
      <h3 class="mb-3">Post a New Job</h3>
      <form method="post">
        <div class="mb-3">
          <label class="form-label">Job Title</label>
          <input type="text" class="form-control" name="title" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Company Name</label>
          <input type="text" class="form-control" name="company" value="{{ current_user['company_name'] or '' }}" required>
        </div>
        <div class="row">
          <div class="col-md-6 mb-3">
            <label class="form-label">Location</label>
            <input type="text" class="form-control" name="location" required>
          </div>
          <div class="col-md-6 mb-3">
            <label class="form-label">Job Type</label>
            <select class="form-select" name="job_type" required>
              {% for jt in job_types %}<option value="{{ jt }}">{{ jt }}</option>{% endfor %}
            </select>
          </div>
        </div>
        <div class="mb-3">
          <label class="form-label">Salary (optional)</label>
          <input type="text" class="form-control" name="salary" placeholder="e.g. $60,000 - $80,000">
        </div>
        <div class="mb-3">
          <label class="form-label">Job Description</label>
          <textarea class="form-control" name="description" rows="6" required></textarea>
        </div>
        <button class="btn btn-primary" type="submit">Publish Job</button>
      </form>
    </div>
  </div>
</div>
{% endblock %}
"""

APPLICANTS_HTML = """
{% extends base %}
{% block title %}Applicants{% endblock %}
{% block content %}
<h3 class="mb-3">Applicants for "{{ job['title'] }}"</h3>
<div class="table-responsive">
<table class="table table-bordered bg-white align-middle">
  <thead class="table-dark"><tr><th>Name</th><th>Email</th><th>Skills</th><th>Cover Letter</th><th>Status</th><th>Update</th></tr></thead>
  <tbody>
  {% for a in applicants %}
    <tr>
      <td>{{ a['name'] }}</td>
      <td>{{ a['email'] }}</td>
      <td>{{ a['skills'] }}</td>
      <td style="max-width:250px;">{{ a['cover_letter'] }}</td>
      <td><span class="badge bg-{{ 'success' if a['status']=='Accepted' else ('danger' if a['status']=='Rejected' else 'secondary') }}">{{ a['status'] }}</span></td>
      <td>
        <form method="post" action="{{ url_for('update_application', app_id=a['id']) }}" class="d-flex gap-1">
          <select name="status" class="form-select form-select-sm">
            <option {% if a['status']=='Pending' %}selected{% endif %}>Pending</option>
            <option {% if a['status']=='Accepted' %}selected{% endif %}>Accepted</option>
            <option {% if a['status']=='Rejected' %}selected{% endif %}>Rejected</option>
          </select>
          <button class="btn btn-sm btn-primary">Save</button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="6">No applicants yet.</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endblock %}
"""

PROFILE_HTML = """
{% extends base %}
{% block title %}My Profile{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-7">
    <div class="card shadow-sm p-4">
      <h3 class="mb-3">My Profile</h3>
      <form method="post">
        <div class="mb-3">
          <label class="form-label">Full Name</label>
          <input type="text" class="form-control" name="name" value="{{ user['name'] }}" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Email</label>
          <input type="email" class="form-control" value="{{ user['email'] }}" disabled>
        </div>
        <div class="mb-3">
          <label class="form-label">Phone</label>
          <input type="text" class="form-control" name="phone" value="{{ user['phone'] }}">
        </div>
        <div class="mb-3">
          <label class="form-label">Location</label>
          <input type="text" class="form-control" name="location" value="{{ user['location'] }}">
        </div>
        {% if user['role'] == 'employer' %}
        <div class="mb-3">
          <label class="form-label">Company Name</label>
          <input type="text" class="form-control" name="company_name" value="{{ user['company_name'] }}">
        </div>
        {% else %}
        <div class="mb-3">
          <label class="form-label">Skills (comma separated)</label>
          <input type="text" class="form-control" name="skills" value="{{ user['skills'] }}" placeholder="Python, SQL, Communication">
        </div>
        {% endif %}
        <div class="mb-3">
          <label class="form-label">Bio</label>
          <textarea class="form-control" name="bio" rows="3">{{ user['bio'] }}</textarea>
        </div>
        <button class="btn btn-primary" type="submit">Save Profile</button>
      </form>
    </div>
  </div>
</div>
{% endblock %}
"""

JOB_TYPES = ["Full-time", "Part-time", "Contract", "Internship", "Remote"]


def render(template_str, **context):
    # Compile the base template into a Template object so that
    # `{% extends base %}` works correctly inside render_template_string.
    context["base"] = app.jinja_env.from_string(BASE_HTML)
    return render_template_string(template_str, **context)


# --------------------------------------------------------------------------
# ROUTES — PAGES
# --------------------------------------------------------------------------

@app.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    location = request.args.get("location", "").strip()
    job_type = request.args.get("job_type", "").strip()

    query = "SELECT * FROM jobs WHERE 1=1"
    params = []
    if q:
        query += " AND (title LIKE ? OR description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")
    if job_type:
        query += " AND job_type = ?"
        params.append(job_type)
    query += " ORDER BY posted_at DESC"

    jobs = db.execute(query, params).fetchall()
    return render(INDEX_HTML, jobs=jobs, q=q, location=location, job_type=job_type, job_types=JOB_TYPES)


@app.route("/job/<int:job_id>")
def job_detail(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        abort(404)
    already_applied = None
    user = current_user()
    if user and user["role"] == "jobseeker":
        already_applied = db.execute(
            "SELECT * FROM applications WHERE job_id = ? AND applicant_id = ?",
            (job_id, user["id"]),
        ).fetchone()
    return render(JOB_DETAIL_HTML, job=job, already_applied=already_applied)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        role = request.form["role"]
        if role not in ("jobseeker", "employer"):
            flash("Invalid role selected.", "danger")
            return redirect(url_for("register"))

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            flash("An account with that email already exists.", "danger")
            return redirect(url_for("register"))

        db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, generate_password_hash(password), role),
        )
        db.commit()
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))
    return render(REGISTER_HTML)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
        return redirect(url_for("login"))
    return render(LOGIN_HTML)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user = current_user()
    if user["role"] == "employer":
        jobs = db.execute(
            """
            SELECT j.*, (SELECT COUNT(*) FROM applications a WHERE a.job_id = j.id) AS app_count
            FROM jobs j WHERE j.employer_id = ? ORDER BY j.posted_at DESC
            """,
            (user["id"],),
        ).fetchall()
        return render(DASHBOARD_EMPLOYER_HTML, jobs=jobs)
    else:
        applications = db.execute(
            """
            SELECT a.*, j.title AS title, j.company AS company, j.id as job_id
            FROM applications a JOIN jobs j ON a.job_id = j.id
            WHERE a.applicant_id = ? ORDER BY a.applied_at DESC
            """,
            (user["id"],),
        ).fetchall()
        return render(DASHBOARD_SEEKER_HTML, applications=applications)


@app.route("/post-job", methods=["GET", "POST"])
@login_required
@role_required("employer")
def post_job():
    if request.method == "POST":
        db = get_db()
        db.execute(
            """INSERT INTO jobs (employer_id, title, description, company, location, job_type, salary)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                current_user()["id"],
                request.form["title"].strip(),
                request.form["description"].strip(),
                request.form["company"].strip(),
                request.form["location"].strip(),
                request.form["job_type"],
                request.form.get("salary", "").strip(),
            ),
        )
        db.commit()
        flash("Job posted successfully!", "success")
        return redirect(url_for("dashboard"))
    return render(POST_JOB_HTML, job_types=JOB_TYPES)


@app.route("/job/<int:job_id>/delete")
@login_required
@role_required("employer")
def delete_job(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job or job["employer_id"] != current_user()["id"]:
        abort(403)
    db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    db.commit()
    flash("Job deleted.", "info")
    return redirect(url_for("dashboard"))


@app.route("/job/<int:job_id>/apply", methods=["POST"])
@login_required
@role_required("jobseeker")
def apply_job(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        abort(404)
    try:
        db.execute(
            "INSERT INTO applications (job_id, applicant_id, cover_letter) VALUES (?, ?, ?)",
            (job_id, current_user()["id"], request.form.get("cover_letter", "").strip()),
        )
        db.commit()
        flash("Application submitted!", "success")
    except sqlite3.IntegrityError:
        flash("You already applied to this job.", "warning")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/job/<int:job_id>/applicants")
@login_required
@role_required("employer")
def job_applicants(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job or job["employer_id"] != current_user()["id"]:
        abort(403)
    applicants = db.execute(
        """
        SELECT a.id, a.status, a.cover_letter, u.name, u.email, u.skills
        FROM applications a JOIN users u ON a.applicant_id = u.id
        WHERE a.job_id = ? ORDER BY a.applied_at DESC
        """,
        (job_id,),
    ).fetchall()
    return render(APPLICANTS_HTML, job=job, applicants=applicants)


@app.route("/application/<int:app_id>/update", methods=["POST"])
@login_required
@role_required("employer")
def update_application(app_id):
    db = get_db()
    row = db.execute(
        """SELECT a.*, j.employer_id FROM applications a
           JOIN jobs j ON a.job_id = j.id WHERE a.id = ?""",
        (app_id,),
    ).fetchone()
    if not row or row["employer_id"] != current_user()["id"]:
        abort(403)
    status = request.form["status"]
    db.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app_id))
    db.commit()
    flash("Application status updated.", "success")
    return redirect(url_for("job_applicants", job_id=row["job_id"]))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    user = current_user()
    if request.method == "POST":
        db.execute(
            """UPDATE users SET name=?, phone=?, location=?, bio=?, skills=?, company_name=? WHERE id=?""",
            (
                request.form["name"].strip(),
                request.form.get("phone", "").strip(),
                request.form.get("location", "").strip(),
                request.form.get("bio", "").strip(),
                request.form.get("skills", "").strip(),
                request.form.get("company_name", "").strip(),
                user["id"],
            ),
        )
        db.commit()
        flash("Profile updated!", "success")
        return redirect(url_for("profile"))
    return render(PROFILE_HTML, user=user)


# --------------------------------------------------------------------------
# JSON REST API ENDPOINTS (for external clients / testing with curl/Postman)
# --------------------------------------------------------------------------

@app.route("/api/jobs", methods=["GET"])
def api_list_jobs():
    db = get_db()
    q = request.args.get("q", "")
    location = request.args.get("location", "")
    job_type = request.args.get("job_type", "")
    query = "SELECT * FROM jobs WHERE 1=1"
    params = []
    if q:
        query += " AND (title LIKE ? OR description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")
    if job_type:
        query += " AND job_type = ?"
        params.append(job_type)
    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/jobs/<int:job_id>", methods=["GET"])
def api_job_detail(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(dict(job))


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    required = {"name", "email", "password", "role"}
    if not required.issubset(data):
        return jsonify({"error": f"Missing fields, required: {sorted(required)}"}), 400
    if data["role"] not in ("jobseeker", "employer"):
        return jsonify({"error": "role must be 'jobseeker' or 'employer'"}), 400
    db = get_db()
    if db.execute("SELECT id FROM users WHERE email = ?", (data["email"].lower(),)).fetchone():
        return jsonify({"error": "Email already registered"}), 409
    db.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (data["name"], data["email"].lower(), generate_password_hash(data["password"]), data["role"]),
    )
    db.commit()
    return jsonify({"message": "User registered successfully"}), 201


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (data.get("email", "").lower(),)).fetchone()
    if not user or not check_password_hash(user["password_hash"], data.get("password", "")):
        return jsonify({"error": "Invalid credentials"}), 401
    session["user_id"] = user["id"]
    return jsonify({"message": "Logged in", "user_id": user["id"], "role": user["role"]})


@app.route("/api/jobs", methods=["POST"])
def api_create_job():
    user = current_user()
    if not user or user["role"] != "employer":
        return jsonify({"error": "Employer login required"}), 401
    data = request.get_json(silent=True) or {}
    required = {"title", "description", "company", "location", "job_type"}
    if not required.issubset(data):
        return jsonify({"error": f"Missing fields, required: {sorted(required)}"}), 400
    db = get_db()
    cur = db.execute(
        """INSERT INTO jobs (employer_id, title, description, company, location, job_type, salary)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user["id"], data["title"], data["description"], data["company"],
         data["location"], data["job_type"], data.get("salary", "")),
    )
    db.commit()
    return jsonify({"message": "Job created", "job_id": cur.lastrowid}), 201


@app.route("/api/jobs/<int:job_id>/apply", methods=["POST"])
def api_apply(job_id):
    user = current_user()
    if not user or user["role"] != "jobseeker":
        return jsonify({"error": "Job seeker login required"}), 401
    data = request.get_json(silent=True) or {}
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO applications (job_id, applicant_id, cover_letter) VALUES (?, ?, ?)",
            (job_id, user["id"], data.get("cover_letter", "")),
        )
        db.commit()
        return jsonify({"message": "Application submitted", "application_id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Already applied to this job"}), 409


@app.errorhandler(404)
def not_found(e):
    return render(
        "{% extends base %}{% block content %}<div class='text-center py-5'><h1>404</h1>"
        "<p>Page not found.</p><a href='{{ url_for(\"index\") }}' class='btn btn-primary'>Go Home</a></div>{% endblock %}"
    ), 404


@app.errorhandler(403)
def forbidden(e):
    return render(
        "{% extends base %}{% block content %}<div class='text-center py-5'><h1>403</h1>"
        "<p>You don't have permission to view this page.</p><a href='{{ url_for(\"index\") }}' class='btn btn-primary'>Go Home</a></div>{% endblock %}"
    ), 403


# --------------------------------------------------------------------------
# ENTRY POINT
# --------------------------------------------------------------------------
if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        init_db()
        print(f"Database created at {DATABASE}")
    else:
        init_db()  # safe: uses CREATE TABLE IF NOT EXISTS
    app.run(debug=True, host="127.0.0.1", port=5000)

# --------------------------------------------------------------------------
# SWITCHING FROM SQLite TO MySQL / PostgreSQL
# --------------------------------------------------------------------------
# This file uses SQLite (Python's built-in sqlite3 module) so it runs with
# ZERO extra setup. To use MySQL or PostgreSQL instead for production:
#
# 1. Install a connector:
#       MySQL:      pip install mysql-connector-python
#       PostgreSQL: pip install psycopg2-binary
#
# 2. Replace the get_db()/init_db() functions's sqlite3.connect(...) calls
#    with the equivalent connector, e.g. for MySQL:
#       import mysql.connector
#       conn = mysql.connector.connect(
#           host="localhost", user="root", password="yourpass", database="jobportal"
#       )
#    For PostgreSQL:
#       import psycopg2
#       conn = psycopg2.connect("dbname=jobportal user=postgres password=yourpass host=localhost")
#
# 3. Adjust the SQL slightly: MySQL/PostgreSQL use AUTO_INCREMENT / SERIAL
#    instead of SQLite's AUTOINCREMENT, and `?` placeholders become `%s`.
#
# The application logic, routes, and templates do NOT need to change.
