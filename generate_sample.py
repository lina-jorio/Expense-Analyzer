"""Generate data/sample_transactions.csv (fake data, French bank-export style).

Run once:  python generate_sample.py
"""
import csv
import random
from datetime import date

random.seed(50)
MONTHS = [(2026, m) for m in range(4, 10)]  # April .. September 2026
rows = []


def add(y, m, d, label, amount):
    rows.append((date(y, m, min(d, 28)), label, amount))


for y, m in MONTHS:
    add(y, m, 28, "VIR SALAIRE ACME SAS", 2400.00)
    add(y, m, 1, "VIR LOYER APPARTEMENT", -850.00)
    add(y, m, 5, "PRLV EDF ELECTRICITE", -round(random.uniform(55, 75), 2))
    add(y, m, 7, "PRLV FREE MOBILE", -19.99)
    add(y, m, 9, "NETFLIX.COM", -13.49)
    add(y, m, 9, "SPOTIFY PREMIUM", -10.99)
    add(y, m, 2, "NAVIGO RATP ABONNEMENT", -86.40)
    for _ in range(random.randint(6, 8)):
        add(y, m, random.randint(1, 28),
            f"CB {random.choice(['CARREFOUR MARKET', 'LECLERC', 'LIDL', 'MONOPRIX', 'AUCHAN'])} {random.randint(100, 999)}",
            -round(random.uniform(14, 85), 2))
    for _ in range(random.randint(4, 6)):
        add(y, m, random.randint(1, 28),
            f"CB {random.choice(['MCDONALDS', 'UBER EATS', 'SUSHI SHOP', 'BOULANGERIE DUPONT', 'STARBUCKS', 'LE BISTROT DU COIN'])}",
            -round(random.uniform(6, 38), 2))
    for _ in range(random.randint(2, 3)):
        add(y, m, random.randint(1, 28),
            f"CB {random.choice(['UBER TRIP', 'TOTALENERGIES STATION', 'SNCF VOYAGEURS', 'PARKING INDIGO'])}",
            -round(random.uniform(8, 60), 2))
    add(y, m, random.randint(1, 28), "CB PHARMACIE DU CENTRE", -round(random.uniform(7, 28), 2))
    if random.random() < 0.5:
        add(y, m, random.randint(1, 28), "CB DOCTOLIB CONSULTATION", -25.00)
    for _ in range(random.randint(1, 3)):
        add(y, m, random.randint(1, 28),
            f"CB {random.choice(['AMAZON MARKETPLACE', 'ZARA', 'DECATHLON', 'FNAC', 'VINTED'])}",
            -round(random.uniform(15, 90), 2))
    for _ in range(random.randint(1, 2)):
        add(y, m, random.randint(1, 28),
            f"CB {random.choice(['CINEMA PATHE', 'UGC CINE CITE', 'STEAM GAMES'])}",
            -round(random.uniform(9, 30), 2))

# One-off events (these are what the anomaly detector should catch)
add(2026, 7, 14, "CB CARREFOUR MARKET 482", -312.40)
add(2026, 8, 3, "CB LE BISTROT DU COIN", -184.00)
add(2026, 8, 10, "CB RYANAIR PARIS BARCELONE", -128.90)
add(2026, 8, 12, "CB AIRBNB BARCELONA", -420.00)
add(2026, 9, 2, "CB UDEMY PYTHON COURSE", -19.99)
add(2026, 9, 15, "CB MYSTERY SHOP 77", -23.50)

rows.sort()
with open("data/sample_transactions.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["Date", "Libelle", "Montant"])
    for d, label, amount in rows:
        w.writerow([d.strftime("%d/%m/%Y"), label, f"{amount:.2f}".replace(".", ",")])
print(f"Wrote {len(rows)} rows")
