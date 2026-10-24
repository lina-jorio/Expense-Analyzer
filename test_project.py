"""Automated tests. Run with:  python -m unittest -v   (or: pytest)"""
import os
import re
import tempfile
import unittest

import analytics
import database as db
from app import SAMPLE_CSV, create_app
from categorizer import Categorizer, normalize
from importer import parse_amount, parse_csv, parse_date


class ImporterTests(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(parse_amount("-12,50"), -12.5)
        self.assertEqual(parse_amount("1 234,56"), 1234.56)
        self.assertEqual(parse_amount("1.234,56"), 1234.56)
        self.assertEqual(parse_amount("1,234.56"), 1234.56)
        self.assertEqual(parse_amount("(20.00)"), -20.0)
        self.assertEqual(parse_amount("-9.99 €"), -9.99)
        self.assertIsNone(parse_amount("  "))
        with self.assertRaises(ValueError):
            parse_amount("abc")

    def test_dates(self):
        self.assertEqual(parse_date("2026-03-05"), "2026-03-05")
        self.assertEqual(parse_date("05/03/2026"), "2026-03-05")
        with self.assertRaises(ValueError):
            parse_date("not a date")

    def test_csv_semicolon_french(self):
        rows, skipped = parse_csv("Date;Libellé;Montant\n01/02/2026;CB LIDL;-12,30\n;;\nbad;x;y\n".encode("utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(rows[0], {"date": "2026-02-01", "description": "CB LIDL", "amount": -12.3})

    def test_csv_debit_credit(self):
        rows, _ = parse_csv(b"Date,Description,Debit,Credit\n2026-01-02,Coffee,3.50,\n2026-01-03,Salary,,1000\n")
        self.assertEqual([r["amount"] for r in rows], [-3.5, 1000.0])

    def test_csv_bad_header(self):
        with self.assertRaises(ValueError):
            parse_csv(b"foo,bar\n1,2\n")
        with self.assertRaises(ValueError):
            parse_csv(b"")


class CategorizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Categorizer()

    def test_normalize(self):
        self.assertEqual(normalize("CB Café  N°12 PARIS"), "cafe n paris")

    def test_rules(self):
        self.assertEqual(self.cat.predict("CB CARREFOUR MARKET 482", -20), ("Groceries", "rule"))
        self.assertEqual(self.cat.predict("NETFLIX.COM", -13.49), ("Subscriptions", "rule"))
        self.assertNotEqual(self.cat.predict("business lunch", -5)[0], "Transport")  # "bus" must not match "business"

    def test_income(self):
        self.assertEqual(self.cat.predict("VIR SALAIRE ACME", 2400), ("Income", "rule"))

    def test_model_handles_unseen_text(self):
        category, source = self.cat.predict("PHARMACIE DE LA GARE", -9)
        self.assertEqual(category, "Health")

    def test_memory_beats_rules(self):
        learned = Categorizer([("CB CARREFOUR MARKET 482", "Shopping")])
        self.assertEqual(learned.predict("CB CARREFOUR MARKET 111", -5), ("Shopping", "memory"))

    def test_gibberish_is_other_or_model(self):
        category, _ = self.cat.predict("12345 !!!", -5)
        self.assertEqual(category, "Other")


class AppTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = create_app({"DATABASE": self.path, "TESTING": True, "SECRET_KEY": "test"})
        self.client = self.app.test_client()

    def tearDown(self):
        os.remove(self.path)

    def register(self, name="alice"):
        return self.client.post("/register", data={"username": name, "password": "secret1", "confirmation": "secret1"},
                                follow_redirects=True)

    def test_requires_login(self):
        self.assertEqual(self.client.get("/dashboard").status_code, 302)
        self.assertEqual(self.client.get("/transactions").status_code, 302)

    def test_register_login_logout(self):
        self.assertIn(b"No data yet", self.register().data)
        self.client.post("/logout")
        bad = self.client.post("/login", data={"username": "alice", "password": "wrong"})
        self.assertIn(b"Invalid username or password", bad.data)
        ok = self.client.post("/login", data={"username": "alice", "password": "secret1"}, follow_redirects=True)
        self.assertEqual(ok.status_code, 200)

    def test_duplicate_username_and_short_password(self):
        self.register()
        self.client.post("/logout")
        again = self.register()
        self.assertIn(b"already taken", again.data)
        short = self.client.post("/register", data={"username": "bob", "password": "123", "confirmation": "123"})
        self.assertIn(b"at least 6", short.data)

    def test_sample_flow_and_dashboard(self):
        self.register()
        r = self.client.post("/load-sample", follow_redirects=True)
        self.assertIn(b"Sample data loaded", r.data)
        page = self.client.get("/dashboard")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Forecast for 2026-10", page.data)
        self.assertIn(b"Unusual expenses", page.data)
        self.assertEqual(self.client.get("/dashboard?month=2026-05").status_code, 200)
        self.assertEqual(self.client.get("/dashboard?month=garbage").status_code, 200)
        # loading twice must not duplicate anything
        again = self.client.post("/load-sample", follow_redirects=True)
        self.assertIn(b"0 transactions added", again.data)

    def test_upload_and_validation(self):
        self.register()
        import io
        bad = self.client.post("/upload", data={"file": (io.BytesIO(b"x,y\n1,2"), "a.csv")},
                               content_type="multipart/form-data", follow_redirects=True)
        self.assertIn(b"Columns not recognised", bad.data)
        good = self.client.post("/upload", data={"file": (io.BytesIO(b"Date,Description,Amount\n2026-01-01,LIDL,-10\n"), "a.csv")},
                                content_type="multipart/form-data", follow_redirects=True)
        self.assertIn(b"Imported 1 transactions", good.data)

    def test_transactions_page_and_learning(self):
        self.register()
        self.client.post("/load-sample")
        page = self.client.get("/transactions?q=MYSTERY")
        self.assertIn(b"MYSTERY SHOP", page.data)
        with self.app.app_context():
            uid = db.get_user_by_name("alice")["id"]
            tx = [t for t in db.all_transactions(uid) if "MYSTERY" in t["description"]][0]
        r = self.client.post(f"/transactions/{tx['id']}/category", data={"category": "Shopping", "next": "/transactions"},
                             follow_redirects=True)
        self.assertIn(b"Category updated", r.data)
        with self.app.app_context():
            self.assertEqual(db.get_transaction(uid, tx["id"])["category"], "Shopping")
            self.assertIn(("CB MYSTERY SHOP 77", "Shopping"), db.manual_examples(uid))
        # invalid category rejected
        self.assertEqual(self.client.post(f"/transactions/{tx['id']}/category", data={"category": "Hacked"}).status_code, 400)

    def test_users_are_isolated(self):
        self.register("alice")
        self.client.post("/load-sample")
        with self.app.app_context():
            tx_id = db.all_transactions(db.get_user_by_name("alice")["id"])[0]["id"]
        self.client.post("/logout")
        self.register("bob")
        self.assertEqual(self.client.post(f"/transactions/{tx_id}/category", data={"category": "Travel"}).status_code, 400)
        self.assertIn(b"No data yet", self.client.get("/dashboard").data)

    def test_recategorize_and_clear(self):
        self.register()
        self.client.post("/load-sample")
        self.assertIn(b"Re-analysed", self.client.post("/recategorize", follow_redirects=True).data)
        self.assertIn(b"deleted", self.client.post("/clear", follow_redirects=True).data)

    def test_csrf_enforced_when_not_testing(self):
        app = create_app({"DATABASE": self.path, "TESTING": False, "SECRET_KEY": "x"})
        c = app.test_client()
        self.assertEqual(c.post("/login", data={"username": "a", "password": "b"}).status_code, 400)
        html = c.get("/login").data.decode()
        token = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html).group(1)
        self.assertEqual(c.post("/login", data={"username": "a", "password": "b", "csrf_token": token}).status_code, 200)


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        with open(SAMPLE_CSV, "rb") as f:
            rows, _ = parse_csv(f.read())
        cat = Categorizer()
        tx = []
        for i, r in enumerate(rows):
            c, s = cat.predict(r["description"], r["amount"])
            tx.append({"id": i, "date": r["date"], "description": r["description"], "amount": r["amount"],
                       "category": c, "source": s})
        self.df = analytics.to_df(tx)

    def test_sample_file(self):
        self.assertEqual(len(self.df), 160)
        self.assertEqual(self.df["month"].nunique(), 6)

    def test_summary_consistency(self):
        s = analytics.summary(self.df)
        self.assertAlmostEqual(s["net"], s["income"] - s["spent"], places=2)
        self.assertAlmostEqual(sum(c["total"] for c in analytics.by_category(self.df)), s["spent"], delta=0.1)

    def test_forecast(self):
        f = analytics.forecast(self.df)
        self.assertEqual(f["month"], "2026-10")
        self.assertGreater(f["total"], 1000)
        self.assertEqual(len(f["based_on"]), 3)

    def test_anomalies_find_planted_outliers(self):
        found = " ".join(a["description"] for a in analytics.anomalies(self.df))
        self.assertIn("CARREFOUR MARKET 482", found)
        self.assertIn("BISTROT", found)

    def test_sample_categories_mostly_known(self):
        other = (self.df["category"] == "Other").sum()
        self.assertLessEqual(other, 3)  # only the "MYSTERY SHOP" style rows


if __name__ == "__main__":
    unittest.main()
