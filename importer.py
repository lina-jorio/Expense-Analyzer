"""CSV import: tolerant parsing of bank statements (French or English style)."""
import csv
import io
import re
from datetime import datetime

from categorizer import normalize

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%Y/%m/%d", "%m/%d/%Y"]

DATE_COLS = {"date", "dateop", "dateoperation", "datevaleur", "transactiondate", "bookingdate",
             "postingdate", "jour"}
DESC_COLS = {"description", "libelle", "label", "details", "memo", "payee", "name", "intitule",
             "motif", "libelleoperation"}
AMOUNT_COLS = {"amount", "montant", "value", "somme"}
DEBIT_COLS = {"debit", "debits", "retrait", "withdrawal"}
CREDIT_COLS = {"credit", "credits", "depot", "deposit"}


def _header_key(name):
    return re.sub(r"[^a-z]", "", normalize(name))


def parse_date(text):
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {text!r}")


def parse_amount(text):
    s = str(text).strip().replace("\u00a0", "").replace(" ", "").replace("\u2212", "-")
    s = s.replace("€", "").replace("$", "").replace("£", "")
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):      # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                  # 1,234.56
            s = s.replace(",", "")
    elif "," in s:                             # 12,50
        s = s.replace(",", ".")
    value = float(s)
    return round(-value if negative else value, 2)


def _decode(raw):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Cannot decode the file.")


def parse_csv(raw_bytes):
    """Return (rows, skipped). rows = [{'date','description','amount'}, ...]."""
    text = _decode(raw_bytes)
    if not text.strip():
        raise ValueError("The file is empty.")
    first_line = text.splitlines()[0]
    delimiter = max([";", ",", "\t", "|"], key=first_line.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader)
    keys = [_header_key(h) for h in header]

    def find(options):
        for i, k in enumerate(keys):
            if k in options:
                return i
        return None

    i_date, i_desc = find(DATE_COLS), find(DESC_COLS)
    i_amount, i_debit, i_credit = find(AMOUNT_COLS), find(DEBIT_COLS), find(CREDIT_COLS)
    if i_date is None or i_desc is None or (i_amount is None and i_debit is None and i_credit is None):
        raise ValueError(
            "Columns not recognised. The first row must contain a date column, a description "
            "column and an amount column (e.g. Date, Description, Amount)."
        )

    rows, skipped = [], 0
    for line in reader:
        if not any(cell.strip() for cell in line):
            continue
        try:
            date = parse_date(line[i_date])
            description = line[i_desc].strip()
            if not description:
                raise ValueError("empty description")
            if i_amount is not None:
                amount = parse_amount(line[i_amount])
            else:
                debit = parse_amount(line[i_debit]) if i_debit is not None and i_debit < len(line) else None
                credit = parse_amount(line[i_credit]) if i_credit is not None and i_credit < len(line) else None
                amount = round(abs(credit or 0) - abs(debit or 0), 2)
            if amount is None:
                raise ValueError("empty amount")
        except (ValueError, IndexError):
            skipped += 1
            continue
        rows.append({"date": date, "description": description, "amount": amount})
    return rows, skipped
