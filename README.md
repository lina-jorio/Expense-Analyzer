# EXPENSE ANALYZER

#### Description: **Expense Analyzer** is a web application that turns a raw bank-statement CSV into something you can actually learn from. You import your transactions, the app automatically sorts every line into a spending category (groceries, transport, subscriptions...), shows where your money goes on an interactive dashboard, predicts next month's spending, and highlights unusual expenses. When the automatic category is wrong, you correct it once and the app learns from that correction. I built it because I wanted to understand my own spending without handing my bank data to a third-party service: everything runs locally with Python, Flask, SQLite, pandas and scikit-learn.

## How to run

```
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000, create an account, then click **Load sample data** (six months of fake transactions) or import your own CSV. Run the automated tests with `python -m unittest -v`. The dashboard charts use Chart.js loaded from a CDN, so the browser needs an internet connection for the graphs only.

## Features

- **Accounts**: registration and login with hashed passwords (Werkzeug), session-based authentication, and a CSRF token on every POST form. Each user only ever sees their own data.
- **Tolerant CSV import**: semicolon, comma, tab or pipe separators; UTF-8 or Windows encodings; French or English column names (`Date`, `Libelle`/`Description`, `Montant`/`Amount`, or separate `Debit`/`Credit`); amounts such as `-12,50`, `1.234,56`, `1,234.56` or `(20.00)`; several date formats. Invalid rows are skipped and counted instead of crashing the import, and re-importing the same file does not create duplicates.
- **Automatic categorisation** in four steps (see below).
- **Dashboard**: totals, a doughnut chart of spending per category, a month-by-month bar chart of spending versus income, and a filter by month.
- **Forecast**: expected spending for the next month, in total and per category.
- **Anomaly detection**: a list of unusually large expenses compared with what is normal in the same category.
- **Transactions page**: search, filter by category, pagination, and a drop-down to change any category instantly.

## What each file does

- `app.py` - the Flask application. It contains all routes (register, login, dashboard, upload, transactions, category update, re-analysis, delete), the CSRF protection, the login-required decorator and the shared import logic. It uses an application factory (`create_app`) so the tests can create an app with a temporary database.
- `database.py` - every SQL query lives here: the schema (`users` and `transactions` tables), and functions to insert, search, update and delete. Keeping SQL out of `app.py` keeps the routes readable.
- `importer.py` - turns raw CSV bytes into clean rows (ISO date, description, signed amount). It detects the delimiter and the columns, parses European and US number formats, and reports what it had to skip.
- `categorizer.py` - the machine-learning part, described below.
- `analytics.py` - the data-analysis part, written with pandas: summary figures, spending per category, monthly totals, the forecast and the anomaly detector.
- `generate_sample.py` - the script that produced `data/sample_transactions.csv` (160 fake transactions, April to September 2026, in the style of a French bank export). It deliberately plants a few outliers so the anomaly detector has something to find.
- `templates/` - Jinja pages: `base.html` (layout and navigation), `login.html`, `register.html`, `dashboard.html`, `upload.html`, `transactions.html`.
- `static/` - `style.css` (the design), `app.js` (auto-submitting drop-downs and a confirmation before deleting data) and `dashboard.js` (draws the two charts from JSON embedded by Flask).
- `test_project.py` - 25 unit and integration tests covering parsing, categorisation, authentication, data isolation between users, CSRF, the learning behaviour and the analytics.
- `requirements.txt` and `.gitignore` - dependencies, and files that must not be committed (virtual environment, database, secret key).

## How the categorisation works, and why

For every transaction the app tries, in order: (1) **memory** - if you already corrected a transaction with the same cleaned-up description, reuse your choice; (2) **rules** - keyword lists such as "carrefour" or "netflix"; (3) **model** - a scikit-learn pipeline (TF-IDF on character n-grams followed by logistic regression) trained on a seed list of merchants plus all of your own corrections; (4) otherwise **Other**. Positive amounts are classed as Income.

I debated using a pure machine-learning approach, but with no labelled data at the start it would be unreliable, and a pure rule-based approach cannot handle merchants it has never seen. Combining them gives predictable results on day one and improves with use. Character n-grams were chosen over whole words because bank labels are messy (`CB BOULANGERIE DUPONT 0412`), and partial word overlap is a strong signal. The model only answers when its confidence is above a threshold; otherwise the transaction stays in "Other" rather than being confidently wrong. Each transaction stores which step decided its category, shown as a small tag on the transactions page, so the system stays transparent.

## Design choices

- **Anomalies use the modified z-score (median and MAD)** instead of the mean and standard deviation. A very large expense inflates the standard deviation and hides itself; the median is robust to that. When all amounts in a category are identical (for example rent), the median absolute deviation is zero, so I flag only amounts above twice the usual value.
- **The forecast is a weighted moving average** of the last three months, with recent months weighing more. A regression would overfit six data points; this is simple, explainable and good enough for a budgeting hint.
- **SQLite and plain SQL** keep setup to zero configuration. Duplicate detection compares the date, description and amount of incoming rows with what is already stored.
- **Security**: passwords are hashed, categories are validated against a fixed list, every query is parameterised, uploads are limited to 5 MB, and a transaction can only be edited by its owner.

## Possible future improvements

Support for multiple bank accounts, budgets with alerts, export to CSV, recurring-payment detection, and a confusion matrix to measure the classifier on real labelled data.


