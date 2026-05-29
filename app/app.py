"""
Dragon Technologies Inventory Manager - Module 2
Main Flask application: auth, roles, inventory CRUD, badge-scan checkout,
roster import, dashboard, and the printable history report.
"""
import csv
import io
import json
import functools
from datetime import datetime, timedelta

import bcrypt
import qrcode
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, jsonify, Response,
)

from db import get_db, init_db
from labels import build_label_pdf

app = Flask(__name__)
# In production set INVENTORY_SECRET_KEY via the environment / compose file.
import os
app.secret_key = os.environ.get("INVENTORY_SECRET_KEY", "dev-only-change-me")

# Ensure the database exists and is seeded before the first request.
init_db()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    """Restrict a view to the given roles (e.g. 'admin', 'manager')."""
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("You don't have permission to do that.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def inject_globals():
    """Make role/username available to every template."""
    return {
        "current_role": session.get("role"),
        "current_user": session.get("username"),
        "now_year": datetime.now().year,
    }


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
def _now():
    return datetime.now().isoformat(timespec="seconds")


def _is_overdue(due_at, return_at):
    """A checkout is overdue if it's still out and past its due date."""
    if return_at:
        return False
    try:
        return datetime.fromisoformat(due_at) < datetime.now()
    except (ValueError, TypeError):
        return False


def generate_item_code(conn, category_id):
    """Build the next item code for a category, e.g. DT-LAP-014, and
    advance that category's counter atomically."""
    cat = conn.execute(
        "SELECT prefix, next_number FROM categories WHERE id = ?",
        (category_id,),
    ).fetchone()
    if cat is None:
        raise ValueError("Unknown category")
    code = f"DT-{cat['prefix']}-{cat['next_number']:03d}"
    conn.execute(
        "UPDATE categories SET next_number = next_number + 1 WHERE id = ?",
        (category_id,),
    )
    return code


# ---------------------------------------------------------------------------
# First-run setup guard
# ---------------------------------------------------------------------------
def admin_exists():
    """True if at least one admin account exists. When none does, the app is
    in first-run mode and must route everything to /setup."""
    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin'"
    ).fetchone()[0]
    conn.close()
    return n > 0


# Endpoints reachable before any admin exists (the setup page itself and its
# static assets). Everything else redirects to /setup until setup is done.
_SETUP_ALLOWED = {"setup", "static"}


@app.before_request
def require_setup_first():
    """If no admin account exists yet, force the first-run setup screen."""
    if request.endpoint in _SETUP_ALLOWED:
        return None
    if not admin_exists():
        return redirect(url_for("setup"))
    return None


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/setup", methods=["GET", "POST"])
def setup():
    """First-run screen: create the initial admin account. Only available
    while no admin exists; once one does, this redirects to login."""
    # If an admin already exists, setup is closed - send them to login.
    if admin_exists():
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        # Validation, with clear messages.
        if not username or not password:
            flash("Username and password are required.", "error")
        elif len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm:
            flash("The two passwords don't match.", "error")
        else:
            conn = get_db()
            # Re-check inside the transaction in case of a race.
            if conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin'"
            ).fetchone()[0] == 0:
                pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                conn.execute(
                    "INSERT INTO users (username, password_hash, role,"
                    " created_at) VALUES (?, ?, 'admin', ?)",
                    (username, pw, _now()),
                )
                conn.commit()
                conn.close()
                flash("Admin account created. Please log in.", "success")
                return redirect(url_for("login"))
            conn.close()
            return redirect(url_for("login"))

    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").encode()
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()
        if user and bcrypt.checkpw(password, user["password_hash"].encode()):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    total_assets = conn.execute(
        "SELECT COUNT(*) FROM items WHERE kind = 'asset'"
    ).fetchone()[0]
    available = conn.execute(
        "SELECT COUNT(*) FROM items WHERE kind='asset' AND status='Available'"
    ).fetchone()[0]
    checked_out = conn.execute(
        "SELECT COUNT(*) FROM items WHERE kind='asset' AND status='Checked Out'"
    ).fetchone()[0]
    in_repair = conn.execute(
        "SELECT COUNT(*) FROM items WHERE kind='asset' AND status='In Repair'"
    ).fetchone()[0]

    # Open checkouts, joined for display, newest first.
    open_rows = conn.execute(
        """SELECT c.*, i.item_code, i.name AS item_name,
                  s.name AS student_name, s.employee_id
           FROM checkouts c
           JOIN items i ON i.id = c.item_id
           JOIN students s ON s.id = c.student_id
           WHERE c.return_at IS NULL
           ORDER BY c.due_at ASC"""
    ).fetchall()

    overdue = [r for r in open_rows if _is_overdue(r["due_at"], r["return_at"])]

    # Low-stock consumables (Phase 2 data; query is harmless when empty).
    low_stock = conn.execute(
        """SELECT * FROM items
           WHERE kind='consumable' AND quantity_on_hand IS NOT NULL
             AND low_stock_threshold IS NOT NULL
             AND quantity_on_hand <= low_stock_threshold"""
    ).fetchall()
    conn.close()

    return render_template(
        "dashboard.html",
        total_assets=total_assets, available=available,
        checked_out=checked_out, in_repair=in_repair,
        open_rows=open_rows, overdue=overdue, low_stock=low_stock,
    )


# ---------------------------------------------------------------------------
# Inventory list + item detail
# ---------------------------------------------------------------------------
@app.route("/inventory")
@login_required
def inventory():
    q = request.args.get("q", "").strip()
    cat_filter = request.args.get("category", "").strip()
    status_filter = request.args.get("status", "").strip()

    conn = get_db()
    sql = """SELECT i.*, c.name AS category_name, c.prefix
             FROM items i JOIN categories c ON c.id = i.category_id
             WHERE i.kind = 'asset'"""
    params = []
    if q:
        sql += " AND (i.name LIKE ? OR i.item_code LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if cat_filter:
        sql += " AND c.id = ?"
        params.append(cat_filter)
    if status_filter:
        sql += " AND i.status = ?"
        params.append(status_filter)
    sql += " ORDER BY i.item_code"
    items = conn.execute(sql, params).fetchall()
    categories = conn.execute(
        "SELECT * FROM categories ORDER BY name"
    ).fetchall()
    conn.close()
    return render_template(
        "inventory.html", items=items, categories=categories,
        q=q, cat_filter=cat_filter, status_filter=status_filter,
        statuses=["Available", "Checked Out", "In Repair", "Retired-Lost"],
    )


@app.route("/item/<int:item_id>")
@login_required
def item_detail(item_id):
    conn = get_db()
    item = conn.execute(
        """SELECT i.*, c.name AS category_name, c.prefix, c.checkout_limit
           FROM items i JOIN categories c ON c.id = i.category_id
           WHERE i.id = ?""",
        (item_id,),
    ).fetchone()
    if item is None:
        conn.close()
        flash("Item not found.", "error")
        return redirect(url_for("inventory"))
    history = conn.execute(
        """SELECT c.*, s.name AS student_name, s.employee_id
           FROM checkouts c JOIN students s ON s.id = c.student_id
           WHERE c.item_id = ? ORDER BY c.checkout_at DESC""",
        (item_id,),
    ).fetchall()
    conn.close()
    return render_template(
        "item_detail.html", item=item, history=history, is_overdue=_is_overdue,
    )


# ---------------------------------------------------------------------------
# Add / edit / delete items  (manager + admin)
# ---------------------------------------------------------------------------
@app.route("/item/new", methods=["GET", "POST"])
@role_required("admin", "manager")
def item_new():
    conn = get_db()
    categories = conn.execute(
        "SELECT * FROM categories ORDER BY name"
    ).fetchall()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category_id = request.form.get("category_id", "")
        location = request.form.get("location", "").strip()
        notes = request.form.get("notes", "").strip()
        if not name or not category_id:
            flash("Name and category are required.", "error")
            conn.close()
            return render_template("item_form.html", categories=categories,
                                   item=None)
        code = generate_item_code(conn, category_id)
        conn.execute(
            """INSERT INTO items (item_code, name, kind, category_id, status,
                                  location, notes, created_at)
               VALUES (?, ?, 'asset', ?, 'Available', ?, ?, ?)""",
            (code, name, category_id, location, notes, _now()),
        )
        conn.commit()
        conn.close()
        flash(f"Asset {code} created.", "success")
        return redirect(url_for("inventory"))
    conn.close()
    return render_template("item_form.html", categories=categories, item=None)


@app.route("/item/<int:item_id>/edit", methods=["GET", "POST"])
@role_required("admin", "manager")
def item_edit(item_id):
    conn = get_db()
    item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        conn.close()
        flash("Item not found.", "error")
        return redirect(url_for("inventory"))
    categories = conn.execute(
        "SELECT * FROM categories ORDER BY name"
    ).fetchall()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category_id = request.form.get("category_id", "")
        status = request.form.get("status", "")
        location = request.form.get("location", "").strip()
        notes = request.form.get("notes", "").strip()
        if not name or not category_id:
            flash("Name and category are required.", "error")
            conn.close()
            return render_template("item_form.html", categories=categories,
                                   item=item)
        # Guard: don't let a checked-out item be flipped away from
        # 'Checked Out' through the edit form - that must go via Return.
        if item["status"] == "Checked Out" and status != "Checked Out":
            flash("This item is checked out. Use Return to change its status.",
                  "error")
            conn.close()
            return redirect(url_for("item_detail", item_id=item_id))
        conn.execute(
            """UPDATE items SET name=?, category_id=?, status=?, location=?,
                                notes=? WHERE id=?""",
            (name, category_id, status, location, notes, item_id),
        )
        conn.commit()
        conn.close()
        flash("Item updated.", "success")
        return redirect(url_for("item_detail", item_id=item_id))
    conn.close()
    return render_template("item_form.html", categories=categories, item=item)


@app.route("/item/<int:item_id>/delete", methods=["POST"])
@role_required("admin", "manager")
def item_delete(item_id):
    conn = get_db()
    open_co = conn.execute(
        "SELECT COUNT(*) FROM checkouts WHERE item_id=? AND return_at IS NULL",
        (item_id,),
    ).fetchone()[0]
    if open_co:
        conn.close()
        flash("Can't delete an item that is currently checked out.", "error")
        return redirect(url_for("item_detail", item_id=item_id))
    conn.execute("DELETE FROM checkouts WHERE item_id = ?", (item_id,))
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    flash("Item deleted.", "success")
    return redirect(url_for("inventory"))


# ---------------------------------------------------------------------------
# Scan station  +  badge / checkout API
# ---------------------------------------------------------------------------
@app.route("/scan")
@login_required
def scan_station():
    """The shared-station screen. Camera scanning happens client-side; the
    page posts decoded QR text to the API endpoints below."""
    return render_template("scan.html")


@app.route("/api/badge", methods=["POST"])
@login_required
def api_badge():
    """Resolve a scanned CLOCKIN badge. The badge encodes JSON:
       {"school","name","employee_id","student_id"}.
    Three distinct failure cases are reported separately."""
    raw = (request.json or {}).get("payload", "")
    # Case 1: not valid JSON at all.
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return jsonify(ok=False, reason="bad_payload",
                       message="That code isn't a valid CLOCKIN badge."), 200
    # Case 2: valid JSON but missing the key we need.
    employee_id = (data.get("employee_id") or "").strip() if isinstance(data, dict) else ""
    if not employee_id:
        return jsonify(ok=False, reason="no_employee_id",
                       message="Badge scanned, but it has no employee ID."), 200
    # Case 3: valid employee_id, but not in our roster.
    conn = get_db()
    student = conn.execute(
        "SELECT * FROM students WHERE employee_id = ?", (employee_id,)
    ).fetchone()
    conn.close()
    if student is None:
        badge_name = data.get("name", "") if isinstance(data, dict) else ""
        return jsonify(ok=False, reason="not_in_roster",
                       message=(f"{badge_name or 'This student'} ({employee_id}) "
                                "isn't in the inventory roster yet. "
                                "See your teacher."),
                       employee_id=employee_id), 200
    if not student["active"]:
        return jsonify(ok=False, reason="inactive",
                       message="That student account is inactive."), 200
    return jsonify(ok=True, student_id=student["id"],
                   employee_id=student["employee_id"],
                   name=student["name"])


@app.route("/api/item-lookup", methods=["POST"])
@login_required
def api_item_lookup():
    """Resolve a scanned asset label (the QR encodes the bare item_code)."""
    code = (request.json or {}).get("payload", "").strip()
    conn = get_db()
    item = conn.execute(
        """SELECT i.*, c.name AS category_name, c.checkout_limit
           FROM items i JOIN categories c ON c.id = i.category_id
           WHERE i.item_code = ?""",
        (code,),
    ).fetchone()
    conn.close()
    if item is None:
        return jsonify(ok=False,
                       message=f"No asset found with code '{code}'."), 200
    return jsonify(ok=True, item_id=item["id"], item_code=item["item_code"],
                   name=item["name"], status=item["status"],
                   category_name=item["category_name"])


@app.route("/api/checkout", methods=["POST"])
@login_required
def api_checkout():
    """Check an asset out to a student. Enforces status + category limits."""
    body = request.json or {}
    item_id = body.get("item_id")
    student_db_id = body.get("student_id")
    days = int(body.get("days", 7))

    conn = get_db()
    item = conn.execute(
        """SELECT i.*, c.checkout_limit, c.name AS category_name
           FROM items i JOIN categories c ON c.id = i.category_id
           WHERE i.id = ?""",
        (item_id,),
    ).fetchone()
    student = conn.execute(
        "SELECT * FROM students WHERE id = ?", (student_db_id,)
    ).fetchone()

    if item is None or student is None:
        conn.close()
        return jsonify(ok=False, message="Item or student not found."), 200
    if item["status"] != "Available":
        conn.close()
        return jsonify(ok=False,
                       message=f"{item['item_code']} is not available "
                               f"(status: {item['status']})."), 200

    # Category checkout limit: count this student's open checkouts in the
    # same category and block if at the cap.
    if item["checkout_limit"] is not None:
        held = conn.execute(
            """SELECT COUNT(*) FROM checkouts c
               JOIN items i ON i.id = c.item_id
               WHERE c.student_id = ? AND c.return_at IS NULL
                 AND i.category_id = ?""",
            (student_db_id, item["category_id"]),
        ).fetchone()[0]
        if held >= item["checkout_limit"]:
            conn.close()
            return jsonify(ok=False,
                           message=(f"{student['name']} already has "
                                    f"{held} {item['category_name']} item(s) "
                                    f"out (limit {item['checkout_limit']}).")), 200

    now = datetime.now()
    due = now + timedelta(days=days)
    conn.execute(
        """INSERT INTO checkouts (item_id, student_id, checkout_at, due_at)
           VALUES (?, ?, ?, ?)""",
        (item_id, student_db_id, now.isoformat(timespec="seconds"),
         due.isoformat(timespec="seconds")),
    )
    conn.execute("UPDATE items SET status='Checked Out' WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify(ok=True,
                   message=(f"{item['item_code']} checked out to "
                            f"{student['name']}. Due "
                            f"{due.strftime('%b %d, %Y')}."))


@app.route("/api/return", methods=["POST"])
@login_required
def api_return():
    """Return an asset. Works from a scanned item code or an item_id."""
    body = request.json or {}
    item_id = body.get("item_id")

    conn = get_db()
    co = conn.execute(
        """SELECT c.*, i.item_code FROM checkouts c
           JOIN items i ON i.id = c.item_id
           WHERE c.item_id = ? AND c.return_at IS NULL""",
        (item_id,),
    ).fetchone()
    if co is None:
        conn.close()
        return jsonify(ok=False,
                       message="That item has no open checkout."), 200
    conn.execute("UPDATE checkouts SET return_at=? WHERE id=?",
                 (_now(), co["id"]))
    conn.execute("UPDATE items SET status='Available' WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify(ok=True, message=f"{co['item_code']} returned. Thanks!")


# ---------------------------------------------------------------------------
# Categories admin  (admin only)
# ---------------------------------------------------------------------------
@app.route("/categories", methods=["GET", "POST"])
@role_required("admin")
def categories():
    conn = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        prefix = request.form.get("prefix", "").strip().upper()
        limit_raw = request.form.get("checkout_limit", "").strip()
        limit = int(limit_raw) if limit_raw.isdigit() else None
        if not name or not prefix:
            flash("Name and prefix are required.", "error")
        elif not (2 <= len(prefix) <= 4) or not prefix.isalpha():
            flash("Prefix must be 2-4 letters.", "error")
        else:
            try:
                conn.execute(
                    """INSERT INTO categories (name, prefix, checkout_limit,
                                               next_number)
                       VALUES (?, ?, ?, 1)""",
                    (name, prefix, limit),
                )
                conn.commit()
                flash(f"Category '{name}' added.", "success")
            except Exception:
                flash("That name or prefix is already in use.", "error")
    cats = conn.execute(
        """SELECT c.*, (SELECT COUNT(*) FROM items WHERE category_id=c.id)
                  AS item_count
           FROM categories c ORDER BY c.name"""
    ).fetchall()
    conn.close()
    return render_template("categories.html", categories=cats)


@app.route("/categories/<int:cat_id>/update", methods=["POST"])
@role_required("admin")
def category_update(cat_id):
    limit_raw = request.form.get("checkout_limit", "").strip()
    limit = int(limit_raw) if limit_raw.isdigit() else None
    conn = get_db()
    conn.execute("UPDATE categories SET checkout_limit=? WHERE id=?",
                 (limit, cat_id))
    conn.commit()
    conn.close()
    flash("Category limit updated.", "success")
    return redirect(url_for("categories"))


# ---------------------------------------------------------------------------
# Users admin  (admin only)
# ---------------------------------------------------------------------------
@app.route("/users", methods=["GET", "POST"])
@role_required("admin")
def users():
    conn = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "student")
        if not username or not password:
            flash("Username and password are required.", "error")
        elif role not in ("admin", "manager", "student"):
            flash("Invalid role.", "error")
        else:
            try:
                pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                conn.execute(
                    """INSERT INTO users (username, password_hash, role,
                                          created_at)
                       VALUES (?, ?, ?, ?)""",
                    (username, pw, role, _now()),
                )
                conn.commit()
                flash(f"User '{username}' created.", "success")
            except Exception:
                flash("That username is already taken.", "error")
    all_users = conn.execute(
        "SELECT id, username, role, created_at FROM users ORDER BY username"
    ).fetchall()
    conn.close()
    return render_template("users.html", users=all_users)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def user_delete(user_id):
    if user_id == session.get("user_id"):
        flash("You can't delete your own account.", "error")
        return redirect(url_for("users"))
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash("User deleted.", "success")
    return redirect(url_for("users"))


# ---------------------------------------------------------------------------
# Student roster  (admin only) - manual add + CSV import
# ---------------------------------------------------------------------------
@app.route("/roster", methods=["GET", "POST"])
@role_required("admin")
def roster():
    conn = get_db()
    if request.method == "POST":
        employee_id = request.form.get("employee_id", "").strip()
        name = request.form.get("name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        section = request.form.get("section", "").strip()
        if not employee_id or not name:
            flash("Employee ID and name are required.", "error")
        else:
            try:
                conn.execute(
                    """INSERT INTO students (employee_id, name, student_id,
                                             section, active, created_at)
                       VALUES (?, ?, ?, ?, 1, ?)""",
                    (employee_id, name, student_id, section, _now()),
                )
                conn.commit()
                flash(f"Student '{name}' added.", "success")
            except Exception:
                flash(f"Employee ID '{employee_id}' already exists.", "error")
    students = conn.execute(
        "SELECT * FROM students ORDER BY name"
    ).fetchall()
    conn.close()
    return render_template("roster.html", students=students)


@app.route("/roster/import", methods=["POST"])
@role_required("admin")
def roster_import():
    """Import a CLOCKIN roster CSV. Expected column: employee_id (required),
    plus optional name, student_id, section. Existing employee_ids are
    updated, not duplicated."""
    file = request.files.get("csv_file")
    if not file or file.filename == "":
        flash("No CSV file selected.", "error")
        return redirect(url_for("roster"))
    try:
        text = file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if "employee_id" not in (reader.fieldnames or []):
            flash("CSV must have an 'employee_id' column.", "error")
            return redirect(url_for("roster"))
        conn = get_db()
        added = updated = 0
        for row in reader:
            emp = (row.get("employee_id") or "").strip()
            if not emp:
                continue
            name = (row.get("name") or "").strip() or emp
            sid = (row.get("student_id") or "").strip()
            section = (row.get("section") or "").strip()
            existing = conn.execute(
                "SELECT id FROM students WHERE employee_id = ?", (emp,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE students SET name=?, student_id=?, section=?
                       WHERE employee_id=?""",
                    (name, sid, section, emp),
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO students (employee_id, name, student_id,
                                             section, active, created_at)
                       VALUES (?, ?, ?, ?, 1, ?)""",
                    (emp, name, sid, section, _now()),
                )
                added += 1
        conn.commit()
        conn.close()
        flash(f"Roster import complete: {added} added, {updated} updated.",
              "success")
    except Exception as exc:
        flash(f"Import failed: {exc}", "error")
    return redirect(url_for("roster"))


# ---------------------------------------------------------------------------
# Asset QR labels  (admin + manager)
# ---------------------------------------------------------------------------
@app.route("/item/<int:item_id>/qr.png")
@role_required("admin", "manager")
def item_qr(item_id):
    """Serve a single asset's QR code as a PNG (handy for one-off printing
    or embedding elsewhere). The QR encodes the bare item_code, which is
    exactly what the scan station expects to read."""
    conn = get_db()
    item = conn.execute(
        "SELECT item_code FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    conn.close()
    if item is None:
        return "Not found", 404
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=2)
    qr.add_data(item["item_code"])
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


# ---------------------------------------------------------------------------
# Check-out history report  (printable)
# ---------------------------------------------------------------------------
@app.route("/report/history")
@login_required
def report_history():
    scope = request.args.get("scope", "all")  # all | open | overdue
    conn = get_db()
    rows = conn.execute(
        """SELECT c.*, i.item_code, i.name AS item_name,
                  s.name AS student_name, s.employee_id
           FROM checkouts c
           JOIN items i ON i.id = c.item_id
           JOIN students s ON s.id = c.student_id
           ORDER BY c.checkout_at DESC"""
    ).fetchall()
    conn.close()
    if scope == "open":
        rows = [r for r in rows if r["return_at"] is None]
    elif scope == "overdue":
        rows = [r for r in rows if _is_overdue(r["due_at"], r["return_at"])]
    return render_template(
        "report_history.html", rows=rows, scope=scope,
        is_overdue=_is_overdue,
        generated=datetime.now().strftime("%B %d, %Y at %I:%M %p"),
    )


@app.route("/report/history.csv")
@login_required
def report_history_csv():
    conn = get_db()
    rows = conn.execute(
        """SELECT c.checkout_at, c.due_at, c.return_at,
                  i.item_code, i.name AS item_name,
                  s.name AS student_name, s.employee_id
           FROM checkouts c
           JOIN items i ON i.id = c.item_id
           JOIN students s ON s.id = c.student_id
           ORDER BY c.checkout_at DESC"""
    ).fetchall()
    conn.close()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["item_code", "item_name", "student_name", "employee_id",
                     "checkout_at", "due_at", "return_at"])
    for r in rows:
        writer.writerow([r["item_code"], r["item_name"], r["student_name"],
                         r["employee_id"], r["checkout_at"], r["due_at"],
                         r["return_at"] or ""])
    return Response(
        out.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition":
                 "attachment; filename=checkout_history.csv"},
    )


# ---------------------------------------------------------------------------
# Asset label printing  (admin + manager)
# ---------------------------------------------------------------------------
@app.route("/labels")
@role_required("admin", "manager")
def labels_page():
    """Pick which assets to print QR labels for."""
    q = request.args.get("q", "").strip()
    cat_filter = request.args.get("category", "").strip()
    conn = get_db()
    sql = """SELECT i.id, i.item_code, i.name, c.name AS category_name
             FROM items i JOIN categories c ON c.id = i.category_id
             WHERE i.kind = 'asset'"""
    params = []
    if q:
        sql += " AND (i.name LIKE ? OR i.item_code LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if cat_filter:
        sql += " AND c.id = ?"
        params.append(cat_filter)
    sql += " ORDER BY i.item_code"
    items = conn.execute(sql, params).fetchall()
    categories = conn.execute(
        "SELECT * FROM categories ORDER BY name"
    ).fetchall()
    conn.close()
    return render_template("labels.html", items=items, categories=categories,
                           q=q, cat_filter=cat_filter)


@app.route("/labels/pdf", methods=["POST"])
@role_required("admin", "manager")
def labels_pdf():
    """Generate a printable PDF of QR labels for the selected assets."""
    ids = request.form.getlist("item_ids")
    if not ids:
        flash("Select at least one asset to print labels for.", "error")
        return redirect(url_for("labels_page"))

    conn = get_db()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT item_code, name FROM items
            WHERE id IN ({placeholders}) AND kind='asset'
            ORDER BY item_code""",
        ids,
    ).fetchall()
    conn.close()

    if not rows:
        flash("No matching assets found.", "error")
        return redirect(url_for("labels_page"))

    pdf_bytes = build_label_pdf([(r["item_code"], r["name"]) for r in rows])
    return Response(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition":
                 "inline; filename=asset-labels.pdf"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
