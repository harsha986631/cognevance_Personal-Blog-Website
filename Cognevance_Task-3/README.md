# Enterprise ERP & Analytics Platform

A REST API backend for an ERP system: authentication, Employee / Inventory / Sales / Finance
modules, and an analytics dashboard — built with **FastAPI** + **SQLAlchemy** + **SQLite**.

---

## 1. Required VS Code Extensions

Install these from the Extensions panel (`Ctrl+Shift+X` / `Cmd+Shift+X`):

| Extension | Publisher | Why you need it |
|---|---|---|
| **Python** | Microsoft | Core Python language support, debugging, run button |
| **Pylance** | Microsoft | Fast type-checking & autocomplete (installs automatically with Python extension) |
| **SQLite Viewer** *(optional)* | Florian Klampfer / qwtel | Lets you browse `erp_platform.db` visually inside VS Code |
| **Thunder Client** *(optional)* | Ranga Vadhineni | Test API endpoints from inside VS Code instead of a browser |

You do **not** strictly need Thunder Client or SQLite Viewer — the built-in `/docs` page
(Swagger UI) covers all API testing. They're listed only as conveniences.

---

## 2. Project Files

```
erp_platform/
├── app.py              # The entire application (models, auth, routes, analytics)
├── requirements.txt    # Exact dependency versions
├── README.md           # This file
└── ARCHITECTURE.md     # Architecture, API reference, and workflow documentation
```

Running the app will also auto-create `erp_platform.db` (the SQLite database file) the first
time you start it — you don't need to create this yourself.

---

## 3. Step-by-Step: Run Locally in VS Code

### Step 1 — Open the folder
Open the `erp_platform` folder in VS Code (`File → Open Folder...`).

### Step 2 — Create a virtual environment
Open a terminal in VS Code (`` Ctrl+` ``) and run:

```bash
python -m venv venv
```

Activate it:
- **Windows (PowerShell):** `venv\Scripts\activate`
- **Windows (cmd.exe):** `venv\Scripts\activate.bat`
- **macOS / Linux:** `source venv/bin/activate`

You should see `(venv)` appear at the start of your terminal line.

> In VS Code, you may also be prompted "Select Interpreter" — choose the one inside `venv`.

### Step 3 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 4 — Run the server
```bash
uvicorn app:app --reload
```

You should see output ending in something like:
```
Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### Step 5 — Open the interactive API docs
Go to **http://127.0.0.1:8000/docs** in your browser. This is a full interactive interface —
you can call every endpoint directly from here.

---

## 4. First-Time Usage Walkthrough

1. A default admin account is created automatically the first time the app starts:
   - **username:** `admin`
   - **password:** `Admin@123`
2. In `/docs`, click the green **"Authorize"** button (top right) and log in with the
   credentials above.
3. You can now call any endpoint directly from the docs page using "Try it out".
4. To create more users with specific roles (`hr`, `sales`, `finance`, `inventory`), use
   `POST /auth/register`.

### Role-based access summary
| Module | Who can write | Who can read |
|---|---|---|
| Employees | `hr`, `admin` | any logged-in user |
| Inventory | `inventory`, `admin` | any logged-in user |
| Sales | `sales`, `admin` | any logged-in user |
| Finance | `finance`, `admin` | `finance`, `admin` only |
| Analytics | — | any logged-in user |

`admin` can do everything regardless of the table above.

---

## 5. Troubleshooting Common Errors

| Error message | Cause | Fix |
|---|---|---|
| `'uvicorn' is not recognized` | Virtual env not activated, or install didn't run | Re-activate `venv`, re-run `pip install -r requirements.txt` |
| `ModuleNotFoundError: No module named 'fastapi'` | Wrong Python interpreter selected in VS Code | `Ctrl+Shift+P` → "Python: Select Interpreter" → pick the `venv` one |
| `Address already in use` | Port 8000 already running another app | Run `uvicorn app:app --reload --port 8001` instead |
| `401 Unauthorized` on an endpoint | Didn't click "Authorize" in `/docs`, or token expired (1 hour) | Log in again via Authorize button |
| `403 Forbidden` | Logged in user's role doesn't have permission for that action | Log in as `admin`, or a user with the correct role |
| Database looks "stuck" / weird data | Just delete `erp_platform.db` and restart — it regenerates automatically | `rm erp_platform.db` then re-run |

---

## 6. Switching to a Cloud / Production Database

Open `app.py` and find this line near the top:

```python
DATABASE_URL = "sqlite:///./erp_platform.db"
```

Replace it with your real connection string, e.g.:

```python
# PostgreSQL (AWS RDS, Supabase, Azure, local Postgres, etc.)
DATABASE_URL = "postgresql://username:password@host:5432/dbname"
```

Then install the matching driver:
```bash
pip install psycopg2-binary
```

No other code changes are required — SQLAlchemy handles the rest.

---

## 7. Deployment (Production)

For a simple cloud deployment (Render, Railway, Fly.io, AWS EC2, etc.):

1. **Never** keep `SECRET_KEY` hardcoded in `app.py` for production. Instead:
   ```python
   import os
   SECRET_KEY = os.environ["SECRET_KEY"]
   ```
   Then set `SECRET_KEY` as an environment variable on your hosting platform.

2. Run with a production-grade process manager instead of `--reload`:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
   ```

3. Restrict CORS in `app.py` — replace:
   ```python
   allow_origins=["*"]
   ```
   with your actual frontend domain:
   ```python
   allow_origins=["https://your-frontend-domain.com"]
   ```

4. Point `DATABASE_URL` at your managed cloud database (see Section 6).

5. Put a reverse proxy (Nginx) or your platform's built-in HTTPS termination in front of
   uvicorn — never expose port 8000 directly to the public internet without TLS.

See `ARCHITECTURE.md` for the full system design and API reference.
