"""SQLite helpers for the Expense Analyzer.

"""
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    hash     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    date        TEXT NOT NULL,          -- ISO format YYYY-MM-DD
    description TEXT NOT NULL,
    amount      REAL NOT NULL,          -- negative = expense, positive = income
    category    TEXT NOT NULL,
    source      TEXT NOT NULL           -- memory | rule | model | default | manual
);
CREATE INDEX IF NOT EXISTS idx_tx_user_date ON transactions(user_id, date);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


# ---------- users ----------
def create_user(username, pw_hash):
    db = get_db()
    cur = db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", (username, pw_hash))
    db.commit()
    return cur.lastrowid


def get_user_by_name(username):
    return get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user(user_id):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


# ---------- transactions ----------
def existing_keys(user_id):
    rows = get_db().execute(
        "SELECT date, description, amount FROM transactions WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {(r["date"], r["description"], round(r["amount"], 2)) for r in rows}


def insert_transactions(user_id, rows):
    db = get_db()
    db.executemany(
        "INSERT INTO transactions (user_id, date, description, amount, category, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(user_id, r["date"], r["description"], r["amount"], r["category"], r["source"]) for r in rows],
    )
    db.commit()


def all_transactions(user_id):
    rows = get_db().execute(
        "SELECT id, date, description, amount, category, source FROM transactions "
        "WHERE user_id = ? ORDER BY date DESC, id DESC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def search_transactions(user_id, category=None, query=None, limit=50, offset=0):
    sql = "FROM transactions WHERE user_id = ?"
    params = [user_id]
    if category:
        sql += " AND category = ?"
        params.append(category)
    if query:
        sql += " AND description LIKE ?"
        params.append(f"%{query}%")
    db = get_db()
    total = db.execute("SELECT COUNT(*) " + sql, params).fetchone()[0]
    rows = db.execute(
        "SELECT id, date, description, amount, category, source " + sql +
        " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return [dict(r) for r in rows], total


def get_transaction(user_id, tx_id):
    row = get_db().execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id)
    ).fetchone()
    return dict(row) if row else None


def update_category(tx_id, category, source):
    db = get_db()
    db.execute("UPDATE transactions SET category = ?, source = ? WHERE id = ?", (category, source, tx_id))
    db.commit()


def bulk_update(updates):
    """updates: list of (category, source, tx_id)."""
    db = get_db()
    db.executemany("UPDATE transactions SET category = ?, source = ? WHERE id = ?", updates)
    db.commit()


def manual_examples(user_id):
    rows = get_db().execute(
        "SELECT description, category FROM transactions WHERE user_id = ? AND source = 'manual'",
        (user_id,),
    ).fetchall()
    return [(r["description"], r["category"]) for r in rows]


def delete_all(user_id):
    db = get_db()
    db.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    db.commit()
