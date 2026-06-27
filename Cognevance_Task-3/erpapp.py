import os
import sqlite3
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, request, render_template_string, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# --------------------------------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.environ.get("ERP_DB_PATH", os.path.join(BASE_DIR, "erp.db"))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
SECRET_KEY = os.environ.get("ERP_SECRET_KEY", secrets.token_hex(32))
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 8          # 8 hour session token
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "csv", "xlsx", "docx"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024   # 10 MB upload limit

serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])

# --------------------------------------------------------------------------
# 2. LOGGING
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "app.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("erp")

# --------------------------------------------------------------------------
# 3. DATABASE LAYER (sqlite3, parameterized queries everywhere)
# --------------------------------------------------------------------------

def get_db():
    """Return a request-scoped SQLite connection."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','manager','employee')) DEFAULT 'employee',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    department TEXT NOT NULL,
    designation TEXT,
    salary REAL NOT NULL DEFAULT 0,
    phone TEXT,
    hire_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL DEFAULT 0,
    reorder_level INTEGER NOT NULL DEFAULT 10,
    supplier TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT UNIQUE NOT NULL,
    item_id INTEGER NOT NULL REFERENCES inventory(id),
    employee_id INTEGER REFERENCES employees(id),
    customer_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    total_amount REAL NOT NULL,
    sale_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS finance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('revenue','expense')),
    category TEXT NOT NULL,
    amount REAL NOT NULL,
    description TEXT,
    ref_sale_id INTEGER REFERENCES sales(id),
    record_date TEXT NOT NULL,
    created_by TEXT
);
"""


def init_db():
    """Create schema (if missing) and seed an admin user + demo data."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()

    cur = conn.execute("SELECT COUNT(*) AS c FROM users")
    if cur.fetchone()["c"] == 0:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (?,?,?,?,?)",
            ("admin", "admin@erp.local", generate_password_hash("Admin@123"), "admin", now),
        )
        conn.execute(
            "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (?,?,?,?,?)",
            ("manager1", "manager1@erp.local", generate_password_hash("Manager@123"), "manager", now),
        )
        logger.info("Seeded default users: admin/Admin@123, manager1/Manager@123")

    cur = conn.execute("SELECT COUNT(*) AS c FROM employees")
    if cur.fetchone()["c"] == 0:
        now = datetime.now(timezone.utc).isoformat()
        demo_employees = [
            ("Asha Rao", "asha.rao@erp.local", "Sales", "Sales Executive", 45000, "9000000001", "2023-01-10"),
            ("Vikram Singh", "vikram.singh@erp.local", "Inventory", "Warehouse Lead", 38000, "9000000002", "2022-06-21"),
            ("Priya Nair", "priya.nair@erp.local", "Finance", "Accountant", 52000, "9000000003", "2021-11-05"),
        ]
        for e in demo_employees:
            conn.execute(
                "INSERT INTO employees (name,email,department,designation,salary,phone,hire_date,status,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (*e, "active", now),
            )

    cur = conn.execute("SELECT COUNT(*) AS c FROM inventory")
    if cur.fetchone()["c"] == 0:
        now = datetime.now(timezone.utc).isoformat()
        demo_items = [
            ("SKU-1001", "Wireless Mouse", "Electronics", 150, 499.0, 20, "TechSupply Co"),
            ("SKU-1002", "Office Chair", "Furniture", 40, 3499.0, 10, "ComfortWorks"),
            ("SKU-1003", "A4 Paper Ream", "Stationery", 8, 250.0, 15, "PaperHub"),
        ]
        for it in demo_items:
            conn.execute(
                "INSERT INTO inventory (sku,name,category,quantity,unit_price,reorder_level,supplier,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (*it, now),
            )

    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# 4. AUTH HELPERS  (token-based, signed with itsdangerous - no extra deps)
# --------------------------------------------------------------------------

def create_token(user_row):
    payload = {"uid": user_row["id"], "username": user_row["username"], "role": user_row["role"]}
    return serializer.dumps(payload)


def decode_token(token):
    try:
        return serializer.loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    data = decode_token(token)
    if not data:
        return None
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (data["uid"],)).fetchone()
    return user


def token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required. Provide a valid Bearer token."}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if not user or user["role"] not in roles:
                return jsonify({"error": "You do not have permission to perform this action."}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ---- very small in-memory login rate limiter (per IP) -------------------
_login_attempts = {}
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 8


def is_rate_limited(ip):
    now = time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[ip] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def record_login_attempt(ip):
    _login_attempts.setdefault(ip, []).append(time.time())


# --------------------------------------------------------------------------
# 5. SECURITY HEADERS (basic hardening on every response)
# --------------------------------------------------------------------------
@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-XSS-Protection"] = "1; mode=block"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return resp


# --------------------------------------------------------------------------
# 6. VALIDATION HELPERS
# --------------------------------------------------------------------------

def require_fields(payload, fields):
    missing = [f for f in fields if payload.get(f) in (None, "")]
    return missing


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ==========================================================================
# 7. AUTH ROUTES
# ==========================================================================
@app.route("/api/auth/register", methods=["POST"])
def register():
    """Public self-registration always creates an 'employee' role account.
    Admin accounts are created via /api/auth/create-user (admin only)."""
    data = request.get_json(silent=True) or {}
    missing = require_fields(data, ["username", "email", "password"])
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    if len(data["password"]) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    db = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users (username,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
            (data["username"], data["email"], generate_password_hash(data["password"]), "employee", now),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username or email already exists."}), 409

    logger.info("New user registered: %s", data["username"])
    return jsonify({"message": "Registration successful. Please login."}), 201


@app.route("/api/auth/create-user", methods=["POST"])
@token_required
@roles_required("admin")
def create_user():
    """Admin-only: create users with any role (admin/manager/employee)."""
    data = request.get_json(silent=True) or {}
    missing = require_fields(data, ["username", "email", "password", "role"])
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    if data["role"] not in ("admin", "manager", "employee"):
        return jsonify({"error": "Invalid role."}), 400

    db = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users (username,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
            (data["username"], data["email"], generate_password_hash(data["password"]), data["role"], now),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username or email already exists."}), 409

    return jsonify({"message": f"User '{data['username']}' created with role '{data['role']}'."}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    ip = request.remote_addr or "unknown"
    if is_rate_limited(ip):
        return jsonify({"error": "Too many login attempts. Try again in a few minutes."}), 429

    data = request.get_json(silent=True) or {}
    missing = require_fields(data, ["username", "password"])
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (data["username"],)).fetchone()

    if not user or not check_password_hash(user["password_hash"], data["password"]):
        record_login_attempt(ip)
        logger.warning("Failed login attempt for username=%s from ip=%s", data["username"], ip)
        return jsonify({"error": "Invalid username or password."}), 401

    if not user["is_active"]:
        return jsonify({"error": "This account has been disabled."}), 403

    token = create_token(user)
    logger.info("User logged in: %s", user["username"])
    return jsonify({
        "token": token,
        "expires_in_seconds": TOKEN_MAX_AGE_SECONDS,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
    })


@app.route("/api/auth/me", methods=["GET"])
@token_required
def me():
    u = g.current_user
    return jsonify({"id": u["id"], "username": u["username"], "email": u["email"], "role": u["role"]})


@app.route("/api/users", methods=["GET"])
@token_required
@roles_required("admin")
def list_users():
    db = get_db()
    rows = db.execute(
        "SELECT id, username, email, role, is_active, created_at FROM users ORDER BY id DESC"
    ).fetchall()
    return jsonify({"data": [dict(r) for r in rows], "total": len(rows)})


@app.route("/api/users/<int:user_id>/status", methods=["PUT"])
@token_required
@roles_required("admin")
def toggle_user_status(user_id):
    if user_id == g.current_user["id"]:
        return jsonify({"error": "You cannot deactivate your own account."}), 400
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return jsonify({"error": "User not found."}), 404
    new_status = 0 if row["is_active"] else 1
    db.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, user_id))
    db.commit()
    return jsonify({"message": "User status updated.", "is_active": bool(new_status)})


# ==========================================================================
# 8. EMPLOYEE MODULE
# ==========================================================================
@app.route("/api/employees", methods=["GET"])
@token_required
def list_employees():
    db = get_db()
    search = request.args.get("search", "")
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(int(request.args.get("per_page", 20)), 100)
    offset = (page - 1) * per_page

    rows = db.execute(
        "SELECT * FROM employees WHERE name LIKE ? OR department LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
        (f"%{search}%", f"%{search}%", per_page, offset),
    ).fetchall()
    total = db.execute(
        "SELECT COUNT(*) AS c FROM employees WHERE name LIKE ? OR department LIKE ?",
        (f"%{search}%", f"%{search}%"),
    ).fetchone()["c"]

    return jsonify({"data": [dict(r) for r in rows], "page": page, "per_page": per_page, "total": total})


@app.route("/api/employees/<int:emp_id>", methods=["GET"])
@token_required
def get_employee(emp_id):
    db = get_db()
    row = db.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    if not row:
        return jsonify({"error": "Employee not found."}), 404
    return jsonify(dict(row))


@app.route("/api/employees", methods=["POST"])
@token_required
@roles_required("admin", "manager")
def create_employee():
    data = request.get_json(silent=True) or {}
    missing = require_fields(data, ["name", "email", "department", "hire_date"])
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    db = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        cur = db.execute(
            "INSERT INTO employees (name,email,department,designation,salary,phone,hire_date,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                data["name"], data["email"], data["department"], data.get("designation", ""),
                float(data.get("salary", 0)), data.get("phone", ""), data["hire_date"],
                data.get("status", "active"), now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "An employee with this email already exists."}), 409

    return jsonify({"message": "Employee created.", "id": cur.lastrowid}), 201


@app.route("/api/employees/<int:emp_id>", methods=["PUT"])
@token_required
@roles_required("admin", "manager")
def update_employee(emp_id):
    db = get_db()
    row = db.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    if not row:
        return jsonify({"error": "Employee not found."}), 404

    data = request.get_json(silent=True) or {}
    fields = ["name", "email", "department", "designation", "salary", "phone", "hire_date", "status"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return jsonify({"error": "No valid fields supplied to update."}), 400

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE employees SET {set_clause} WHERE id = ?", (*updates.values(), emp_id))
    db.commit()
    return jsonify({"message": "Employee updated."})


@app.route("/api/employees/<int:emp_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def delete_employee(emp_id):
    db = get_db()
    row = db.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    if not row:
        return jsonify({"error": "Employee not found."}), 404
    db.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    db.commit()
    return jsonify({"message": "Employee deleted."})


# ==========================================================================
# 9. INVENTORY MODULE
# ==========================================================================
@app.route("/api/inventory", methods=["GET"])
@token_required
def list_inventory():
    db = get_db()
    search = request.args.get("search", "")
    low_stock = request.args.get("low_stock")

    query = "SELECT * FROM inventory WHERE (name LIKE ? OR sku LIKE ? OR category LIKE ?)"
    params = [f"%{search}%", f"%{search}%", f"%{search}%"]
    if low_stock == "true":
        query += " AND quantity <= reorder_level"
    query += " ORDER BY id DESC"

    rows = db.execute(query, params).fetchall()
    return jsonify({"data": [dict(r) for r in rows], "total": len(rows)})


@app.route("/api/inventory/<int:item_id>", methods=["GET"])
@token_required
def get_inventory_item(item_id):
    db = get_db()
    row = db.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
    if not row:
        return jsonify({"error": "Inventory item not found."}), 404
    return jsonify(dict(row))


@app.route("/api/inventory", methods=["POST"])
@token_required
@roles_required("admin", "manager")
def create_inventory_item():
    data = request.get_json(silent=True) or {}
    missing = require_fields(data, ["sku", "name", "category", "unit_price"])
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    db = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        cur = db.execute(
            "INSERT INTO inventory (sku,name,category,quantity,unit_price,reorder_level,supplier,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                data["sku"], data["name"], data["category"], int(data.get("quantity", 0)),
                float(data["unit_price"]), int(data.get("reorder_level", 10)),
                data.get("supplier", ""), now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "An item with this SKU already exists."}), 409

    return jsonify({"message": "Inventory item created.", "id": cur.lastrowid}), 201


@app.route("/api/inventory/<int:item_id>", methods=["PUT"])
@token_required
@roles_required("admin", "manager")
def update_inventory_item(item_id):
    db = get_db()
    row = db.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
    if not row:
        return jsonify({"error": "Inventory item not found."}), 404

    data = request.get_json(silent=True) or {}
    fields = ["sku", "name", "category", "quantity", "unit_price", "reorder_level", "supplier"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return jsonify({"error": "No valid fields supplied to update."}), 400
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE inventory SET {set_clause} WHERE id = ?", (*updates.values(), item_id))
    db.commit()
    return jsonify({"message": "Inventory item updated."})


@app.route("/api/inventory/<int:item_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def delete_inventory_item(item_id):
    db = get_db()
    row = db.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
    if not row:
        return jsonify({"error": "Inventory item not found."}), 404
    db.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    db.commit()
    return jsonify({"message": "Inventory item deleted."})


# ==========================================================================
# 10. SALES MODULE  (creating a sale auto-decrements stock + posts revenue)
# ==========================================================================
@app.route("/api/sales", methods=["GET"])
@token_required
def list_sales():
    db = get_db()
    rows = db.execute(
        """SELECT s.*, i.name AS item_name, e.name AS employee_name
           FROM sales s
           LEFT JOIN inventory i ON s.item_id = i.id
           LEFT JOIN employees e ON s.employee_id = e.id
           ORDER BY s.id DESC"""
    ).fetchall()
    return jsonify({"data": [dict(r) for r in rows], "total": len(rows)})


@app.route("/api/sales", methods=["POST"])
@token_required
@roles_required("admin", "manager", "employee")
def create_sale():
    data = request.get_json(silent=True) or {}
    missing = require_fields(data, ["item_id", "customer_name", "quantity"])
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    db = get_db()
    item = db.execute("SELECT * FROM inventory WHERE id = ?", (data["item_id"],)).fetchone()
    if not item:
        return jsonify({"error": "Inventory item not found."}), 404

    quantity = int(data["quantity"])
    if quantity <= 0:
        return jsonify({"error": "Quantity must be a positive number."}), 400
    if item["quantity"] < quantity:
        return jsonify({"error": f"Insufficient stock. Available: {item['quantity']}"}), 400

    unit_price = float(data.get("unit_price", item["unit_price"]))
    total_amount = round(unit_price * quantity, 2)
    order_no = f"ORD-{int(time.time() * 1000)}"
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    db.execute(
        "INSERT INTO sales (order_no,item_id,employee_id,customer_name,quantity,unit_price,total_amount,sale_date,status) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (order_no, item["id"], data.get("employee_id"), data["customer_name"], quantity,
         unit_price, total_amount, data.get("sale_date", now_date), "completed"),
    )
    sale_id = db.execute("SELECT id FROM sales WHERE order_no = ?", (order_no,)).fetchone()["id"]

    db.execute(
        "UPDATE inventory SET quantity = quantity - ?, updated_at = ? WHERE id = ?",
        (quantity, datetime.now(timezone.utc).isoformat(), item["id"]),
    )

    db.execute(
        "INSERT INTO finance (type,category,amount,description,ref_sale_id,record_date,created_by) "
        "VALUES (?,?,?,?,?,?,?)",
        ("revenue", "Sales Revenue", total_amount, f"Auto-posted from order {order_no}",
         sale_id, now_date, g.current_user["username"]),
    )

    db.commit()
    logger.info("Sale created: %s amount=%.2f", order_no, total_amount)
    return jsonify({"message": "Sale recorded.", "order_no": order_no, "total_amount": total_amount}), 201


@app.route("/api/sales/<int:sale_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def cancel_sale(sale_id):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if not sale:
        return jsonify({"error": "Sale not found."}), 404
    if sale["status"] == "cancelled":
        return jsonify({"error": "Sale already cancelled."}), 400

    db.execute("UPDATE sales SET status = 'cancelled' WHERE id = ?", (sale_id,))
    db.execute("UPDATE inventory SET quantity = quantity + ? WHERE id = ?", (sale["quantity"], sale["item_id"]))
    db.execute(
        "INSERT INTO finance (type,category,amount,description,ref_sale_id,record_date,created_by) VALUES (?,?,?,?,?,?,?)",
        ("expense", "Sales Reversal", sale["total_amount"], f"Cancellation of {sale['order_no']}",
         sale_id, datetime.now(timezone.utc).strftime("%Y-%m-%d"), g.current_user["username"]),
    )
    db.commit()
    return jsonify({"message": "Sale cancelled and stock restored."})


# ==========================================================================
# 11. FINANCE MODULE
# ==========================================================================
@app.route("/api/finance", methods=["GET"])
@token_required
@roles_required("admin", "manager")
def list_finance():
    db = get_db()
    ftype = request.args.get("type")
    query = "SELECT * FROM finance"
    params = []
    if ftype in ("revenue", "expense"):
        query += " WHERE type = ?"
        params.append(ftype)
    query += " ORDER BY id DESC"
    rows = db.execute(query, params).fetchall()
    return jsonify({"data": [dict(r) for r in rows], "total": len(rows)})


@app.route("/api/finance", methods=["POST"])
@token_required
@roles_required("admin", "manager")
def create_finance_record():
    data = request.get_json(silent=True) or {}
    missing = require_fields(data, ["type", "category", "amount"])
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    if data["type"] not in ("revenue", "expense"):
        return jsonify({"error": "type must be 'revenue' or 'expense'."}), 400

    db = get_db()
    db.execute(
        "INSERT INTO finance (type,category,amount,description,record_date,created_by) VALUES (?,?,?,?,?,?)",
        (data["type"], data["category"], float(data["amount"]), data.get("description", ""),
         data.get("record_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")), g.current_user["username"]),
    )
    db.commit()
    return jsonify({"message": "Finance record created."}), 201


# ==========================================================================
# 12. ANALYTICS & REPORTING
# ==========================================================================
@app.route("/api/analytics/summary", methods=["GET"])
@token_required
def analytics_summary():
    db = get_db()

    total_employees = db.execute("SELECT COUNT(*) AS c FROM employees WHERE status='active'").fetchone()["c"]
    inventory_value = db.execute("SELECT COALESCE(SUM(quantity * unit_price),0) AS v FROM inventory").fetchone()["v"]
    total_sales_amount = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) AS v FROM sales WHERE status='completed'"
    ).fetchone()["v"]
    total_revenue = db.execute("SELECT COALESCE(SUM(amount),0) AS v FROM finance WHERE type='revenue'").fetchone()["v"]
    total_expense = db.execute("SELECT COALESCE(SUM(amount),0) AS v FROM finance WHERE type='expense'").fetchone()["v"]

    monthly_sales_rows = db.execute(
        """SELECT strftime('%Y-%m', sale_date) AS month, SUM(total_amount) AS total
           FROM sales WHERE status='completed' GROUP BY month ORDER BY month"""
    ).fetchall()

    low_stock_rows = db.execute(
        "SELECT sku, name, quantity, reorder_level FROM inventory WHERE quantity <= reorder_level"
    ).fetchall()

    category_rows = db.execute(
        """SELECT i.category AS category, COALESCE(SUM(s.total_amount),0) AS total
           FROM sales s JOIN inventory i ON s.item_id = i.id
           WHERE s.status='completed' GROUP BY i.category"""
    ).fetchall()

    return jsonify({
        "total_employees": total_employees,
        "inventory_value": round(inventory_value, 2),
        "total_sales_amount": round(total_sales_amount, 2),
        "total_revenue": round(total_revenue, 2),
        "total_expense": round(total_expense, 2),
        "net_profit": round(total_revenue - total_expense, 2),
        "monthly_sales": [{"month": r["month"], "total": round(r["total"], 2)} for r in monthly_sales_rows],
        "low_stock_items": [dict(r) for r in low_stock_rows],
        "sales_by_category": [{"category": r["category"], "total": round(r["total"], 2)} for r in category_rows],
    })


# ==========================================================================
# 13. FILE STORAGE  (local disk demo - see "Cloud Deployment Notes" at end)
# ==========================================================================
@app.route("/api/files/upload", methods=["POST"])
@token_required
@roles_required("admin", "manager")
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request."}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed."}), 400

    filename = secure_filename(f"{int(time.time())}_{file.filename}")
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return jsonify({"message": "File uploaded.", "filename": filename, "url": f"/api/files/{filename}"}), 201


@app.route("/api/files/<path:filename>", methods=["GET"])
@token_required
def download_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ==========================================================================
# 14. ERROR HANDLERS
# ==========================================================================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Resource not found."}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed."}), 405


@app.errorhandler(500)
def server_error(e):
    logger.exception("Internal server error")
    return jsonify({"error": "Internal server error."}), 500


# ==========================================================================
# 15. FRONTEND  -  Login page + Analytics Dashboard (Chart.js via CDN)
# ==========================================================================
BASE_STYLE = """
<style>
  :root{--bg:#0f172a;--card:#1e293b;--accent:#38bdf8;--accent2:#a78bfa;--text:#e2e8f0;--muted:#94a3b8;--good:#34d399;--bad:#f87171;--border:rgba(255,255,255,0.08);}
  *{box-sizing:border-box;font-family:'Segoe UI',Roboto,Arial,sans-serif;}
  body{margin:0;background:linear-gradient(160deg,#0f172a,#111827 60%);color:var(--text);min-height:100vh;}
  a{color:var(--accent);text-decoration:none;}
  .btn{background:var(--accent);color:#0f172a;border:none;padding:9px 16px;border-radius:8px;font-weight:600;cursor:pointer;transition:.2s;font-size:13.5px;}
  .btn:hover{opacity:0.85;}
  .btn.secondary{background:transparent;border:1px solid var(--muted);color:var(--text);}
  .btn.danger{background:var(--bad);color:#1a0a0a;}
  .btn.small{padding:5px 10px;font-size:12px;border-radius:6px;}
  .badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;background:rgba(56,189,248,0.15);color:var(--accent);}
  .pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11.5px;font-weight:600;}
  .pill.active, .pill.completed, .pill.revenue{background:rgba(52,211,153,0.15);color:var(--good);}
  .pill.inactive, .pill.cancelled, .pill.expense{background:rgba(248,113,113,0.15);color:var(--bad);}

  /* ---- App shell layout ---- */
  .app-shell{display:flex;min-height:100vh;}
  .sidebar{width:230px;flex-shrink:0;background:rgba(255,255,255,0.03);border-right:1px solid var(--border);padding:20px 14px;display:flex;flex-direction:column;}
  .sidebar .brand{font-size:17px;font-weight:700;padding:6px 10px 22px;}
  .sidebar .brand span{color:var(--accent);}
  .navlink{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:9px;color:var(--muted);cursor:pointer;font-size:14px;margin-bottom:3px;transition:.15s;}
  .navlink:hover{background:rgba(255,255,255,0.05);color:var(--text);}
  .navlink.active{background:rgba(56,189,248,0.14);color:var(--accent);font-weight:600;}
  .sidebar-footer{margin-top:auto;padding:12px 10px 4px;border-top:1px solid var(--border);}
  .sidebar-footer .who{font-size:13px;margin-bottom:8px;}
  .main{flex:1;min-width:0;}
  .topbar{display:flex;justify-content:space-between;align-items:center;padding:16px 28px;border-bottom:1px solid var(--border);background:rgba(255,255,255,0.02);}
  .topbar h1{font-size:18px;margin:0;}
  .wrap{max-width:1180px;margin:0 auto;padding:26px 28px;}

  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px;margin-bottom:24px;}
  .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px;box-shadow:0 6px 18px rgba(0,0,0,0.25);}
  .card h3{margin:0 0 6px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;}
  .card .val{font-size:26px;font-weight:700;}
  .chart-row{display:grid;grid-template-columns:2fr 1fr;gap:18px;}
  .panel{background:var(--card);border-radius:14px;padding:20px;border:1px solid var(--border);}
  .panel h2{margin-top:0;font-size:16px;color:var(--accent2);}
  .panel-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;}
  .panel-head h2{margin:0;}
  .toolbar{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;}
  .toolbar input[type=text]{max-width:260px;margin-bottom:0;}
  .toolbar label{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);}

  table{width:100%;border-collapse:collapse;font-size:13.5px;}
  th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--border);white-space:nowrap;}
  th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:0.4px;}
  tbody tr:hover{background:rgba(255,255,255,0.03);}
  .table-wrap{overflow-x:auto;}
  .actions-cell{display:flex;gap:6px;}
  .empty-row td{text-align:center;color:var(--muted);padding:26px;}

  .login-box{max-width:380px;margin:9vh auto;background:var(--card);padding:32px;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,0.4);}
  .login-box h1{text-align:center;margin-bottom:4px;}
  .login-box p{text-align:center;color:var(--muted);margin-top:0;font-size:13px;}
  input,select,textarea{width:100%;padding:10px 12px;margin-bottom:14px;border-radius:8px;border:1px solid rgba(255,255,255,0.14);background:#0b1220;color:var(--text);font-size:13.5px;}
  label.field-label{font-size:12.5px;color:var(--muted);display:block;margin-bottom:6px;}
  .err{color:var(--bad);font-size:13px;margin-bottom:10px;min-height:14px;}
  .ok-msg{color:var(--good);font-size:13px;margin-bottom:10px;min-height:14px;}
  .hint{font-size:12px;color:var(--muted);margin-top:14px;text-align:center;}

  /* ---- Modal ---- */
  .modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,0.55);display:none;align-items:center;justify-content:center;z-index:50;}
  .modal-backdrop.open{display:flex;}
  .modal-box{background:var(--card);border-radius:14px;padding:24px;width:420px;max-width:92vw;max-height:88vh;overflow-y:auto;border:1px solid var(--border);box-shadow:0 16px 50px rgba(0,0,0,0.5);}
  .modal-box h3{margin-top:0;}
  .modal-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:6px;}
  .field-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
</style>
"""

LOGIN_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>ERP Platform - Login</title>""" + BASE_STYLE + """
</head><body>
<div class="login-box">
  <h1>ERP<span style="color:var(--accent)">+</span>Analytics</h1>
  <p>Enterprise Resource Planning Platform</p>
  <div class="err" id="err"></div>
  <input id="username" placeholder="Username" autocomplete="username">
  <input id="password" type="password" placeholder="Password" autocomplete="current-password">
  <button class="btn" style="width:100%" onclick="doLogin()">Sign In</button>
  <div class="hint">Demo admin &rarr; <b>admin</b> / <b>Admin@123</b></div>
</div>
<script>
async function doLogin(){
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  const errBox = document.getElementById('err');
  errBox.textContent = '';
  try{
    const res = await fetch('/api/auth/login', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username, password})
    });
    const data = await res.json();
    if(!res.ok){ errBox.textContent = data.error || 'Login failed'; return; }
    localStorage.setItem('erp_token', data.token);
    localStorage.setItem('erp_user', JSON.stringify(data.user));
    window.location.href = '/dashboard';
  }catch(e){ errBox.textContent = 'Network error. Is the server running?'; }
}
document.getElementById('password').addEventListener('keyup', e=>{ if(e.key==='Enter') doLogin(); });
</script>
</body></html>
"""

APP_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>ERP Platform</title>""" + BASE_STYLE + """
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.4/chart.umd.min.js"></script>
</head><body>

<div class="app-shell">
  <div class="sidebar">
    <div class="brand">ERP<span>+</span>Platform</div>
    <div id="navlinks"></div>
    <div class="sidebar-footer">
      <div class="who"><span class="badge" id="whoami">...</span></div>
      <button class="btn secondary" style="width:100%" onclick="logout()">Logout</button>
    </div>
  </div>

  <div class="main">
    <div class="topbar">
      <h1 id="pageTitle">Dashboard</h1>
      <a href="/docs" class="btn secondary" target="_blank">API Docs</a>
    </div>
    <div class="wrap" id="content"></div>
  </div>
</div>

<div class="modal-backdrop" id="modalBackdrop">
  <div class="modal-box">
    <h3 id="modalTitle">Form</h3>
    <div class="err" id="modalErr"></div>
    <form id="modalForm"></form>
    <div class="modal-actions">
      <button class="btn secondary" onclick="closeModal()">Cancel</button>
      <button class="btn" onclick="submitModal()">Save</button>
    </div>
  </div>
</div>

<script>
/* ===================== Core state & helpers ===================== */
const token = localStorage.getItem('erp_token');
const user = JSON.parse(localStorage.getItem('erp_user') || 'null');
if(!token || !user){ window.location.href = '/'; }

function logout(){ localStorage.removeItem('erp_token'); localStorage.removeItem('erp_user'); window.location.href='/'; }

async function api(path, options){
  options = options || {};
  options.headers = Object.assign({'Authorization':'Bearer '+token}, options.headers||{});
  const res = await fetch(path, options);
  if(res.status === 401){ logout(); throw new Error('Session expired'); }
  let data = {};
  try{ data = await res.json(); }catch(e){ data = {}; }
  if(!res.ok){ throw new Error(data.error || ('Request failed ('+res.status+')')); }
  return data;
}
async function apiJSON(path, method, body){
  return api(path, { method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
}
function money(n){ return '\u20b9' + Number(n||0).toLocaleString(undefined,{maximumFractionDigits:2}); }
function esc(s){ return (s===undefined||s===null) ? '' : String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

/* ===================== Navigation ===================== */
const NAV = [
  {id:'dashboard', label:'Dashboard', roles:['admin','manager','employee']},
  {id:'employees',  label:'Employees',  roles:['admin','manager','employee']},
  {id:'inventory',  label:'Inventory',  roles:['admin','manager','employee']},
  {id:'sales',      label:'Sales',      roles:['admin','manager','employee']},
  {id:'finance',    label:'Finance',    roles:['admin','manager']},
  {id:'users',      label:'Users',      roles:['admin']},
];
let currentPage = 'dashboard';

function renderNav(){
  document.getElementById('navlinks').innerHTML = NAV
    .filter(n => n.roles.includes(user.role))
    .map(n => `<div class="navlink ${n.id===currentPage?'active':''}" onclick="goTo('${n.id}')">${n.label}</div>`)
    .join('');
}
function goTo(page){
  currentPage = page;
  document.getElementById('pageTitle').textContent = NAV.find(n=>n.id===page).label;
  renderNav();
  const fn = {dashboard: renderDashboard, employees: renderEmployees, inventory: renderInventory,
              sales: renderSales, finance: renderFinance, users: renderUsers}[page];
  fn();
}
document.getElementById('whoami').textContent = user.username + ' (' + user.role + ')';

/* ===================== Generic modal ===================== */
let modalSubmitHandler = null;
function openModal(title, fieldsHtml, onSubmit){
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalForm').innerHTML = fieldsHtml;
  document.getElementById('modalErr').textContent = '';
  modalSubmitHandler = onSubmit;
  document.getElementById('modalBackdrop').classList.add('open');
}
function closeModal(){ document.getElementById('modalBackdrop').classList.remove('open'); }
async function submitModal(){
  const errBox = document.getElementById('modalErr');
  errBox.textContent = '';
  try{ await modalSubmitHandler(); closeModal(); }
  catch(e){ errBox.textContent = e.message; }
}
function fv(name){ const el = document.getElementById('f_'+name); return el ? el.value : ''; }

/* ===================== DASHBOARD ===================== */
async function renderDashboard(){
  const c = document.getElementById('content');
  c.innerHTML = `
    <div class="grid" id="kpis"></div>
    <div class="chart-row">
      <div class="panel"><h2>Monthly Sales Trend</h2><canvas id="salesChart" height="160"></canvas></div>
      <div class="panel"><h2>Sales by Category</h2><canvas id="categoryChart" height="160"></canvas></div>
    </div>
    <br>
    <div class="panel"><h2>Low Stock Alerts</h2>
      <div class="table-wrap"><table id="lowStockTable"><thead><tr><th>SKU</th><th>Item</th><th>Qty</th><th>Reorder Level</th></tr></thead><tbody></tbody></table></div>
    </div>`;
  const d = await api('/api/analytics/summary');
  document.getElementById('kpis').innerHTML = `
    <div class="card"><h3>Active Employees</h3><div class="val">${d.total_employees}</div></div>
    <div class="card"><h3>Inventory Value</h3><div class="val">${money(d.inventory_value)}</div></div>
    <div class="card"><h3>Total Sales</h3><div class="val">${money(d.total_sales_amount)}</div></div>
    <div class="card"><h3>Net Profit</h3><div class="val" style="color:${d.net_profit>=0?'var(--good)':'var(--bad)'}">${money(d.net_profit)}</div></div>`;

  new Chart(document.getElementById('salesChart'), {
    type:'line',
    data:{ labels: d.monthly_sales.map(m=>m.month), datasets:[{
      label:'Sales (\u20b9)', data: d.monthly_sales.map(m=>m.total),
      borderColor:'#38bdf8', backgroundColor:'rgba(56,189,248,0.15)', tension:0.35, fill:true }]},
    options:{ plugins:{legend:{labels:{color:'#e2e8f0'}}}, scales:{
      x:{ticks:{color:'#94a3b8'}, grid:{color:'rgba(255,255,255,0.05)'}},
      y:{ticks:{color:'#94a3b8'}, grid:{color:'rgba(255,255,255,0.05)'}} }}
  });
  new Chart(document.getElementById('categoryChart'), {
    type:'doughnut',
    data:{ labels: d.sales_by_category.map(c=>c.category),
      datasets:[{ data: d.sales_by_category.map(c=>c.total),
        backgroundColor:['#38bdf8','#a78bfa','#34d399','#f87171','#fbbf24'] }]},
    options:{ plugins:{legend:{labels:{color:'#e2e8f0'}}} }
  });
  document.querySelector('#lowStockTable tbody').innerHTML =
    d.low_stock_items.map(i=>`<tr><td>${esc(i.sku)}</td><td>${esc(i.name)}</td><td>${i.quantity}</td><td>${i.reorder_level}</td></tr>`).join('')
    || '<tr class="empty-row"><td colspan="4">No low-stock items</td></tr>';
}

/* ===================== EMPLOYEES ===================== */
const canWrite = ['admin','manager'].includes(user.role);
const canDelete = user.role === 'admin';

async function renderEmployees(){
  const c = document.getElementById('content');
  c.innerHTML = `
    <div class="panel">
      <div class="panel-head"><h2>Employees</h2>${canWrite?'<button class="btn" onclick="openEmployeeModal()">+ Add Employee</button>':''}</div>
      <div class="toolbar"><input type="text" id="empSearch" placeholder="Search name or department..." oninput="loadEmployees()"></div>
      <div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Department</th><th>Designation</th><th>Salary</th><th>Status</th><th></th></tr></thead><tbody id="empBody"></tbody></table></div>
    </div>`;
  await loadEmployees();
}
async function loadEmployees(){
  const q = document.getElementById('empSearch').value;
  const d = await api('/api/employees?search=' + encodeURIComponent(q) + '&per_page=100');
  const rows = d.data.map(e => `<tr>
      <td>${esc(e.name)}</td><td>${esc(e.email)}</td><td>${esc(e.department)}</td><td>${esc(e.designation||'-')}</td>
      <td>${money(e.salary)}</td><td><span class="pill ${e.status}">${esc(e.status)}</span></td>
      <td class="actions-cell">
        ${canWrite?`<button class="btn small secondary" onclick='openEmployeeModal(${JSON.stringify(e)})'>Edit</button>`:''}
        ${canDelete?`<button class="btn small danger" onclick="deleteEmployee(${e.id})">Delete</button>`:''}
      </td></tr>`).join('');
  document.getElementById('empBody').innerHTML = rows || '<tr class="empty-row"><td colspan="7">No employees found</td></tr>';
}
function openEmployeeModal(e){
  e = e || {};
  const fields = `
    <label class="field-label">Full Name</label><input id="f_name" value="${esc(e.name)}">
    <label class="field-label">Email</label><input id="f_email" value="${esc(e.email)}">
    <div class="field-row">
      <div><label class="field-label">Department</label><input id="f_department" value="${esc(e.department)}"></div>
      <div><label class="field-label">Designation</label><input id="f_designation" value="${esc(e.designation)}"></div>
    </div>
    <div class="field-row">
      <div><label class="field-label">Salary</label><input id="f_salary" type="number" value="${e.salary||0}"></div>
      <div><label class="field-label">Phone</label><input id="f_phone" value="${esc(e.phone)}"></div>
    </div>
    <div class="field-row">
      <div><label class="field-label">Hire Date</label><input id="f_hire_date" type="date" value="${e.hire_date||''}"></div>
      <div><label class="field-label">Status</label>
        <select id="f_status"><option value="active" ${e.status==='active'?'selected':''}>Active</option><option value="inactive" ${e.status==='inactive'?'selected':''}>Inactive</option></select>
      </div>
    </div>`;
  openModal(e.id ? 'Edit Employee' : 'Add Employee', fields, async () => {
    const payload = {name:fv('name'), email:fv('email'), department:fv('department'), designation:fv('designation'),
                      salary: parseFloat(fv('salary')||0), phone: fv('phone'), hire_date: fv('hire_date'), status: fv('status')};
    if(e.id) await apiJSON('/api/employees/'+e.id, 'PUT', payload);
    else await apiJSON('/api/employees', 'POST', payload);
    await loadEmployees();
  });
}
async function deleteEmployee(id){
  if(!confirm('Delete this employee?')) return;
  try{ await api('/api/employees/'+id, {method:'DELETE'}); await loadEmployees(); }
  catch(e){ alert(e.message); }
}

/* ===================== INVENTORY ===================== */
async function renderInventory(){
  const c = document.getElementById('content');
  c.innerHTML = `
    <div class="panel">
      <div class="panel-head"><h2>Inventory</h2>${canWrite?'<button class="btn" onclick="openInventoryModal()">+ Add Item</button>':''}</div>
      <div class="toolbar">
        <input type="text" id="invSearch" placeholder="Search SKU, name or category..." oninput="loadInventory()">
        <label><input type="checkbox" id="lowStockOnly" style="width:auto;margin:0;" onchange="loadInventory()"> Low stock only</label>
      </div>
      <div class="table-wrap"><table><thead><tr><th>SKU</th><th>Name</th><th>Category</th><th>Qty</th><th>Unit Price</th><th>Reorder Lvl</th><th>Supplier</th><th></th></tr></thead><tbody id="invBody"></tbody></table></div>
    </div>`;
  await loadInventory();
}
async function loadInventory(){
  const q = document.getElementById('invSearch').value;
  const low = document.getElementById('lowStockOnly').checked;
  const d = await api('/api/inventory?search=' + encodeURIComponent(q) + (low?'&low_stock=true':''));
  const rows = d.data.map(i => `<tr>
      <td>${esc(i.sku)}</td><td>${esc(i.name)}</td><td>${esc(i.category)}</td>
      <td style="color:${i.quantity<=i.reorder_level?'var(--bad)':'inherit'}">${i.quantity}</td>
      <td>${money(i.unit_price)}</td><td>${i.reorder_level}</td><td>${esc(i.supplier||'-')}</td>
      <td class="actions-cell">
        ${canWrite?`<button class="btn small secondary" onclick='openInventoryModal(${JSON.stringify(i)})'>Edit</button>`:''}
        ${canDelete?`<button class="btn small danger" onclick="deleteInventoryItem(${i.id})">Delete</button>`:''}
      </td></tr>`).join('');
  document.getElementById('invBody').innerHTML = rows || '<tr class="empty-row"><td colspan="8">No inventory items found</td></tr>';
}
function openInventoryModal(i){
  i = i || {};
  const fields = `
    <div class="field-row">
      <div><label class="field-label">SKU</label><input id="f_sku" value="${esc(i.sku)}" ${i.id?'disabled':''}></div>
      <div><label class="field-label">Name</label><input id="f_name" value="${esc(i.name)}"></div>
    </div>
    <label class="field-label">Category</label><input id="f_category" value="${esc(i.category)}">
    <div class="field-row">
      <div><label class="field-label">Quantity</label><input id="f_quantity" type="number" value="${i.quantity||0}"></div>
      <div><label class="field-label">Unit Price</label><input id="f_unit_price" type="number" value="${i.unit_price||0}"></div>
    </div>
    <div class="field-row">
      <div><label class="field-label">Reorder Level</label><input id="f_reorder_level" type="number" value="${i.reorder_level||10}"></div>
      <div><label class="field-label">Supplier</label><input id="f_supplier" value="${esc(i.supplier)}"></div>
    </div>`;
  openModal(i.id ? 'Edit Inventory Item' : 'Add Inventory Item', fields, async () => {
    const payload = {name:fv('name'), category:fv('category'), quantity: parseInt(fv('quantity')||0),
                      unit_price: parseFloat(fv('unit_price')||0), reorder_level: parseInt(fv('reorder_level')||10),
                      supplier: fv('supplier')};
    if(i.id) await apiJSON('/api/inventory/'+i.id, 'PUT', payload);
    else await apiJSON('/api/inventory', 'POST', Object.assign({sku: fv('sku')}, payload));
    await loadInventory();
  });
}
async function deleteInventoryItem(id){
  if(!confirm('Delete this inventory item?')) return;
  try{ await api('/api/inventory/'+id, {method:'DELETE'}); await loadInventory(); }
  catch(e){ alert(e.message); }
}

/* ===================== SALES ===================== */
let _invCache = [];
async function renderSales(){
  const c = document.getElementById('content');
  c.innerHTML = `
    <div class="panel">
      <div class="panel-head"><h2>Sales Orders</h2><button class="btn" onclick="openSaleModal()">+ New Sale</button></div>
      <div class="table-wrap"><table><thead><tr><th>Order No</th><th>Item</th><th>Customer</th><th>Qty</th><th>Unit Price</th><th>Total</th><th>Date</th><th>Status</th><th></th></tr></thead><tbody id="salesBody"></tbody></table></div>
    </div>`;
  await loadSales();
}
async function loadSales(){
  const d = await api('/api/sales');
  const rows = d.data.map(s => `<tr>
      <td>${esc(s.order_no)}</td><td>${esc(s.item_name||'-')}</td><td>${esc(s.customer_name)}</td>
      <td>${s.quantity}</td><td>${money(s.unit_price)}</td><td>${money(s.total_amount)}</td>
      <td>${esc(s.sale_date)}</td><td><span class="pill ${s.status}">${esc(s.status)}</span></td>
      <td class="actions-cell">${(canDelete && s.status==='completed')?`<button class="btn small danger" onclick="cancelSale(${s.id})">Cancel</button>`:''}</td>
      </tr>`).join('');
  document.getElementById('salesBody').innerHTML = rows || '<tr class="empty-row"><td colspan="9">No sales yet</td></tr>';
}
async function openSaleModal(){
  const invData = await api('/api/inventory');
  _invCache = invData.data;
  const options = _invCache.map(i => `<option value="${i.id}" data-price="${i.unit_price}" data-stock="${i.quantity}">${esc(i.sku)} - ${esc(i.name)} (stock: ${i.quantity})</option>`).join('');
  const fields = `
    <label class="field-label">Item</label><select id="f_item_id">${options}</select>
    <label class="field-label">Customer Name</label><input id="f_customer_name">
    <div class="field-row">
      <div><label class="field-label">Quantity</label><input id="f_quantity" type="number" value="1"></div>
      <div><label class="field-label">Unit Price (auto)</label><input id="f_unit_price" type="number"></div>
    </div>`;
  openModal('New Sale', fields, async () => {
    const payload = {item_id: parseInt(fv('item_id')), customer_name: fv('customer_name'), quantity: parseInt(fv('quantity')||0)};
    if(fv('unit_price')) payload.unit_price = parseFloat(fv('unit_price'));
    await apiJSON('/api/sales', 'POST', payload);
    await loadSales();
  });
  const sel = document.getElementById('f_item_id');
  const priceBox = document.getElementById('f_unit_price');
  const syncPrice = () => { const opt = sel.options[sel.selectedIndex]; if(opt) priceBox.value = opt.dataset.price; };
  sel.addEventListener('change', syncPrice); syncPrice();
}
async function cancelSale(id){
  if(!confirm('Cancel this sale and restore stock?')) return;
  try{ await api('/api/sales/'+id, {method:'DELETE'}); await loadSales(); }
  catch(e){ alert(e.message); }
}

/* ===================== FINANCE ===================== */
async function renderFinance(){
  const c = document.getElementById('content');
  c.innerHTML = `
    <div class="panel">
      <div class="panel-head"><h2>Finance Ledger</h2><button class="btn" onclick="openFinanceModal()">+ Add Record</button></div>
      <div class="toolbar">
        <select id="finFilter" style="width:200px;margin:0;" onchange="loadFinance()">
          <option value="">All types</option><option value="revenue">Revenue</option><option value="expense">Expense</option>
        </select>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Category</th><th>Amount</th><th>Description</th><th>By</th></tr></thead><tbody id="finBody"></tbody></table></div>
    </div>`;
  await loadFinance();
}
async function loadFinance(){
  const t = document.getElementById('finFilter').value;
  const d = await api('/api/finance' + (t ? ('?type='+t) : ''));
  const rows = d.data.map(f => `<tr>
      <td>${esc(f.record_date)}</td><td><span class="pill ${f.type}">${esc(f.type)}</span></td>
      <td>${esc(f.category)}</td><td>${money(f.amount)}</td><td>${esc(f.description||'-')}</td><td>${esc(f.created_by||'-')}</td>
      </tr>`).join('');
  document.getElementById('finBody').innerHTML = rows || '<tr class="empty-row"><td colspan="6">No finance records found</td></tr>';
}
function openFinanceModal(){
  const fields = `
    <label class="field-label">Type</label>
    <select id="f_type"><option value="revenue">Revenue</option><option value="expense">Expense</option></select>
    <label class="field-label">Category</label><input id="f_category" placeholder="e.g. Rent, Utilities, Other Income">
    <label class="field-label">Amount</label><input id="f_amount" type="number">
    <label class="field-label">Description</label><input id="f_description">`;
  openModal('Add Finance Record', fields, async () => {
    await apiJSON('/api/finance', 'POST', {type: fv('type'), category: fv('category'), amount: parseFloat(fv('amount')||0), description: fv('description')});
    await loadFinance();
  });
}

/* ===================== USERS (admin only) ===================== */
async function renderUsers(){
  const c = document.getElementById('content');
  c.innerHTML = `
    <div class="panel">
      <div class="panel-head"><h2>System Users</h2><button class="btn" onclick="openUserModal()">+ Create User</button></div>
      <div class="table-wrap"><table><thead><tr><th>Username</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody id="usersBody"></tbody></table></div>
    </div>`;
  await loadUsers();
}
async function loadUsers(){
  const d = await api('/api/users');
  const rows = d.data.map(u => `<tr>
      <td>${esc(u.username)}</td><td>${esc(u.email)}</td><td>${esc(u.role)}</td>
      <td><span class="pill ${u.is_active?'active':'inactive'}">${u.is_active?'active':'inactive'}</span></td>
      <td class="actions-cell">${u.id!==user.id?`<button class="btn small secondary" onclick="toggleUser(${u.id})">${u.is_active?'Deactivate':'Activate'}</button>`:'<span style="color:var(--muted);font-size:12px;">(you)</span>'}</td>
      </tr>`).join('');
  document.getElementById('usersBody').innerHTML = rows || '<tr class="empty-row"><td colspan="5">No users found</td></tr>';
}
function openUserModal(){
  const fields = `
    <label class="field-label">Username</label><input id="f_username">
    <label class="field-label">Email</label><input id="f_email" type="email">
    <label class="field-label">Password</label><input id="f_password" type="password">
    <label class="field-label">Role</label>
    <select id="f_role"><option value="employee">Employee</option><option value="manager">Manager</option><option value="admin">Admin</option></select>`;
  openModal('Create User', fields, async () => {
    await apiJSON('/api/auth/create-user', 'POST', {username:fv('username'), email:fv('email'), password:fv('password'), role:fv('role')});
    await loadUsers();
  });
}
async function toggleUser(id){
  try{ await api('/api/users/'+id+'/status', {method:'PUT'}); await loadUsers(); }
  catch(e){ alert(e.message); }
}

/* ===================== Boot ===================== */
renderNav();
goTo('dashboard');
</script>
</body></html>
"""

DOCS_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>API Docs</title>""" + BASE_STYLE + """
</head><body>
<div class="nav"><h1>ERP<span>+</span>Analytics &mdash; API Reference</h1><a class="btn secondary" href="/">Home</a></div>
<div class="wrap">
<div class="panel">
<pre style="white-space:pre-wrap;font-size:13.5px;line-height:1.6;color:#cbd5e1">{{docs}}</pre>
</div>
</div>
</body></html>
"""

API_DOCS_TEXT = """
AUTHENTICATION
  POST   /api/auth/register        Public registration (role=employee)
  POST   /api/auth/create-user     [admin] create user with any role
  POST   /api/auth/login           Returns Bearer token
  GET    /api/auth/me              Current user info               [auth]
  GET    /api/users                List all users                 [admin]
  PUT    /api/users/<id>/status    Activate / deactivate a user    [admin]

EMPLOYEES
  GET    /api/employees            List (search, page, per_page)    [auth]
  GET    /api/employees/<id>       Get one                          [auth]
  POST   /api/employees            Create                    [admin/manager]
  PUT    /api/employees/<id>       Update                    [admin/manager]
  DELETE /api/employees/<id>       Delete                          [admin]

INVENTORY
  GET    /api/inventory            List (search, low_stock=true)    [auth]
  GET    /api/inventory/<id>       Get one                          [auth]
  POST   /api/inventory            Create                    [admin/manager]
  PUT    /api/inventory/<id>       Update                    [admin/manager]
  DELETE /api/inventory/<id>       Delete                          [admin]

SALES
  GET    /api/sales                List all sales                  [auth]
  POST   /api/sales                Create sale (auto stock+finance) [auth]
  DELETE /api/sales/<id>           Cancel sale & restore stock     [admin]

FINANCE
  GET    /api/finance              List records (type=revenue|expense) [admin/manager]
  POST   /api/finance              Create manual record           [admin/manager]

ANALYTICS
  GET    /api/analytics/summary    KPIs, trends, low stock, category split [auth]

FILES
  POST   /api/files/upload         Multipart upload                [admin/manager]
  GET    /api/files/<filename>     Download                         [auth]

All protected endpoints require header:  Authorization: Bearer <token>
"""


@app.route("/")
def home():
    return render_template_string(LOGIN_PAGE)


@app.route("/dashboard")
def dashboard():
    return render_template_string(APP_PAGE)


@app.route("/docs")
def docs():
    return render_template_string(DOCS_PAGE, docs=API_DOCS_TEXT)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


# ==========================================================================
# 16. ENTRY POINT
# ==========================================================================
if __name__ == "__main__":
    init_db()
    logger.info("Database ready at %s", DATABASE)
    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug_mode)
