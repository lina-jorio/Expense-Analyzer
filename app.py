"""Expense Analyzer - Flask web application.


"""
import os
import secrets
from functools import wraps

from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import analytics
import database as db
from categorizer import CATEGORIES, Categorizer, normalize
from importer import parse_csv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_CSV = os.path.join(BASE_DIR, "data", "sample_transactions.csv")
PER_PAGE = 50


def _load_secret_key():
    """Use SECRET_KEY from the environment, otherwise create one once and keep it."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    instance = os.path.join(BASE_DIR, "instance")
    os.makedirs(instance, exist_ok=True)
    path = os.path.join(instance, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config["DATABASE"] = os.path.join(BASE_DIR, "expenses.db")
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB upload limit
    if test_config:
        app.config.update(test_config)
    app.config.setdefault("SECRET_KEY", None)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = _load_secret_key()

    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)

    # ---------- security helpers ----------
    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if request.method == "POST" and not app.config.get("TESTING"):
            sent = request.form.get("csrf_token", "")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Invalid or missing CSRF token. Reload the page and try again.")

    @app.after_request
    def no_cache(resp):
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("user_id") is None or db.get_user(session["user_id"]) is None:
                session.clear()
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    # ---------- shared logic ----------
    def import_rows(user_id, rows):
        """Categorise and store rows, skipping ones already in the database."""
        known = db.existing_keys(user_id)
        categorizer = Categorizer(db.manual_examples(user_id))
        fresh, duplicates = [], 0
        for r in rows:
            if (r["date"], r["description"], r["amount"]) in known:
                duplicates += 1
                continue
            r["category"], r["source"] = categorizer.predict(r["description"], r["amount"])
            fresh.append(r)
        db.insert_transactions(user_id, fresh)
        return len(fresh), duplicates

    # ---------- auth ----------
    @app.route("/")
    def index():
        return redirect(url_for("dashboard" if session.get("user_id") else "login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirmation", "")
            if not username or len(username) > 40:
                flash("Please choose a username (max 40 characters).", "error")
            elif len(password) < 6:
                flash("Password must be at least 6 characters.", "error")
            elif password != confirm:
                flash("Passwords do not match.", "error")
            elif db.get_user_by_name(username):
                flash("That username is already taken.", "error")
            else:
                user_id = db.create_user(username, generate_password_hash(password))
                session.clear()
                session["user_id"] = user_id
                flash("Welcome! Upload a CSV or load the sample data to begin.", "success")
                return redirect(url_for("dashboard"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = db.get_user_by_name(request.form.get("username", "").strip())
            if user and check_password_hash(user["hash"], request.form.get("password", "")):
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------- dashboard ----------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        transactions = db.all_transactions(session["user_id"])
        if not transactions:
            return render_template("dashboard.html", empty=True)
        df = analytics.to_df(transactions)
        months = analytics.available_months(df)
        month = request.args.get("month", "all")
        view = df if month == "all" or month not in months else df[df["month"] == month]
        if view is not df:
            selected = month
        else:
            selected = "all"
        data = {
            "categories": analytics.by_category(view),
            "monthly": analytics.monthly(df),
        }
        return render_template(
            "dashboard.html", empty=False, summary=analytics.summary(view), months=months,
            selected=selected, chart_data=data, forecast=analytics.forecast(df),
            anomalies=analytics.anomalies(df),
        )

    # ---------- upload ----------
    @app.route("/upload", methods=["GET", "POST"])
    @login_required
    def upload():
        if request.method == "POST":
            file = request.files.get("file")
            if not file or not file.filename:
                flash("Please choose a CSV file.", "error")
                return redirect(url_for("upload"))
            try:
                rows, skipped = parse_csv(file.read())
            except ValueError as e:
                flash(str(e), "error")
                return redirect(url_for("upload"))
            if not rows:
                flash("No valid transaction found in that file.", "error")
                return redirect(url_for("upload"))
            added, dup = import_rows(session["user_id"], rows)
            flash(f"Imported {added} transactions ({dup} duplicates ignored, {skipped} invalid rows skipped).",
                  "success")
            return redirect(url_for("dashboard"))
        return render_template("upload.html")

    @app.route("/load-sample", methods=["POST"])
    @login_required
    def load_sample():
        with open(SAMPLE_CSV, "rb") as f:
            rows, skipped = parse_csv(f.read())
        added, dup = import_rows(session["user_id"], rows)
        flash(f"Sample data loaded: {added} transactions added ({dup} duplicates ignored).", "success")
        return redirect(url_for("dashboard"))

    # ---------- transactions ----------
    @app.route("/transactions")
    @login_required
    def transactions():
        category = request.args.get("category", "")
        if category not in CATEGORIES:
            category = ""
        query = request.args.get("q", "").strip()
        page = max(request.args.get("page", 1, type=int), 1)
        rows, total = db.search_transactions(
            session["user_id"], category or None, query or None, PER_PAGE, (page - 1) * PER_PAGE)
        pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
        return render_template(
            "transactions.html", rows=rows, total=total, page=page, pages=pages,
            categories=CATEGORIES, category=category, q=query)

    @app.route("/transactions/<int:tx_id>/category", methods=["POST"])
    @login_required
    def set_category(tx_id):
        category = request.form.get("category", "")
        tx = db.get_transaction(session["user_id"], tx_id)
        if tx is None or category not in CATEGORIES:
            abort(400)
        db.update_category(tx_id, category, "manual")
        # learning: apply the correction to every identical, non-manual transaction
        norm = normalize(tx["description"])
        updates = [(category, "memory", t["id"]) for t in db.all_transactions(session["user_id"])
                   if t["id"] != tx_id and t["source"] != "manual"
                   and normalize(t["description"]) == norm and t["category"] != category]
        if updates:
            db.bulk_update(updates)
            flash(f"Category updated. Also applied to {len(updates)} similar transaction(s).", "success")
        else:
            flash("Category updated.", "success")
        nxt = request.form.get("next", "")
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = url_for("transactions")
        return redirect(nxt)

    @app.route("/recategorize", methods=["POST"])
    @login_required
    def recategorize():
        user_id = session["user_id"]
        categorizer = Categorizer(db.manual_examples(user_id))
        updates = []
        for t in db.all_transactions(user_id):
            if t["source"] == "manual":
                continue
            cat, src = categorizer.predict(t["description"], t["amount"])
            if cat != t["category"] or src != t["source"]:
                updates.append((cat, src, t["id"]))
        db.bulk_update(updates)
        flash(f"Re-analysed all transactions: {len(updates)} changed.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/clear", methods=["POST"])
    @login_required
    def clear():
        db.delete_all(session["user_id"])
        flash("All your transactions were deleted.", "success")
        return redirect(url_for("dashboard"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=False, port=5000)
