"""Automatic categorisation of bank transactions.

Pipeline, from most to least trusted:
  1. memory  - the user already corrected an identical description
  2. rule    - a keyword rule matches
  3. model   - a scikit-learn classifier (TF-IDF on character n-grams +
               logistic regression) trained on a seed list plus the user's
               own corrections
  4. default - "Other"
Positive amounts are treated as "Income" unless memory says otherwise.
"""
import re
import unicodedata

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

CATEGORIES = [
    "Groceries", "Restaurants", "Transport", "Housing", "Utilities", "Health",
    "Entertainment", "Shopping", "Subscriptions", "Travel", "Education",
    "Income", "Other",
]

RULES = {
    "Groceries": ["carrefour", "leclerc", "lidl", "auchan", "monoprix", "intermarche", "franprix",
                  "aldi", "casino", "picard", "supermarche", "grocery", "walmart", "tesco"],
    "Restaurants": ["restaurant", "mcdonald", "burger king", "kfc", "uber eats", "deliveroo",
                    "just eat", "starbucks", "boulangerie", "sushi", "pizza", "brasserie",
                    "cafe", "bistro", "subway", "paul"],
    "Transport": ["sncf", "ratp", "navigo", "uber", "bolt", "taxi", "total", "shell", "esso",
                  "essence", "carburant", "peage", "parking", "blablacar", "metro", "bus"],
    "Housing": ["loyer", "rent", "immobilier", "syndic", "assurance habitation", "ikea", "leroy merlin"],
    "Utilities": ["edf", "engie", "veolia", "eau", "electricite", "gaz", "free mobile", "orange",
                  "sfr", "bouygues", "internet", "electricity", "water bill"],
    "Health": ["pharmacie", "pharmacy", "doctolib", "medecin", "docteur", "hopital", "dentiste",
               "mutuelle", "optique", "clinique", "laboratoire"],
    "Entertainment": ["cinema", "ugc", "pathe", "gaumont", "steam", "playstation", "xbox",
                      "concert", "ticketmaster", "fnac spectacles", "theatre", "bowling"],
    "Shopping": ["amazon", "zara", "h&m", "decathlon", "fnac", "darty", "cdiscount", "zalando",
                 "vinted", "apple store", "boulanger", "uniqlo", "kiabi"],
    "Subscriptions": ["netflix", "spotify", "disney", "deezer", "youtube premium", "amazon prime",
                      "canal", "icloud", "openai", "chatgpt", "adobe", "dropbox", "subscription"],
    "Travel": ["airbnb", "booking", "ryanair", "easyjet", "air france", "hotel", "expedia",
               "airline", "lufthansa", "trainline"],
    "Education": ["universite", "ecole", "udemy", "coursera", "edx", "librairie", "cours",
                  "tuition", "campus", "scolarite"],
    "Income": ["salaire", "salary", "payroll", "virement recu", "remboursement secu"],
}

# Extra labelled examples so the model has something to learn from on day one.
SEED_EXAMPLES = {
    "Groceries": ["carrefour market", "leclerc drive", "lidl", "auchan supermarche", "monoprix",
                  "intermarche express", "franprix", "marche bio", "primeur du coin", "epicerie fine"],
    "Restaurants": ["mcdonalds", "burger king", "uber eats", "deliveroo", "starbucks coffee",
                    "boulangerie paul", "sushi shop", "pizzeria napoli", "brasserie du coin",
                    "cafe de la gare", "restaurant le bistrot", "kebab", "creperie", "dominos pizza"],
    "Transport": ["sncf voyageurs", "ratp navigo", "uber trip", "taxi g7", "totalenergies station",
                  "shell essence", "autoroute peage", "parking indigo", "blablacar", "velib abonnement"],
    "Housing": ["loyer appartement", "virement loyer", "rent payment", "assurance habitation",
                "ikea meubles", "leroy merlin bricolage", "syndic copropriete", "castorama"],
    "Utilities": ["edf electricite", "engie gaz", "veolia eau", "free mobile forfait", "orange internet",
                  "sfr box", "bouygues telecom", "electricity bill", "internet provider"],
    "Health": ["pharmacie centrale", "pharmacie du centre", "doctolib rdv", "dr martin medecin",
               "hopital clinique", "dentiste cabinet", "mutuelle sante", "optique lunettes"],
    "Entertainment": ["cinema ugc", "pathe gaumont", "steam games", "playstation store",
                      "ticketmaster concert", "theatre billet", "bowling", "parc attractions"],
    "Shopping": ["amazon marketplace", "zara", "decathlon sport", "fnac", "darty", "zalando",
                 "vinted", "h&m", "uniqlo", "cdiscount", "boulanger electro"],
    "Subscriptions": ["netflix", "spotify premium", "disney plus", "deezer", "icloud storage",
                      "youtube premium", "amazon prime", "chatgpt subscription", "adobe creative"],
    "Travel": ["airbnb", "booking com hotel", "ryanair", "easyjet", "air france", "hotel ibis",
               "trainline", "expedia voyage"],
    "Education": ["universite inscription", "udemy cours", "coursera", "librairie gibert",
                  "ecole scolarite", "edx certificate", "campus fees"],
    "Income": ["salaire entreprise", "virement salaire", "salary payment", "payroll", "caf allocation",
               "remboursement secu"],
}
SEED_EXAMPLES = [(text, cat) for cat, texts in SEED_EXAMPLES.items() for text in texts]

NOISE = {"carte", "cb", "paiement", "prlv", "vir", "card", "payment", "purchase", "pos", "du",
         "de", "la", "le", "les", "sa", "sas", "sarl", "fr", "com", "www"}

MODEL_THRESHOLD = 0.25


def normalize(text):
    """Lowercase, strip accents, digits and punctuation, drop noisy bank words."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z&\s]", " ", text)
    words = [w for w in text.split() if w not in NOISE]
    return " ".join(words)


def rule_category(norm_desc):
    for category, keywords in RULES.items():
        for kw in keywords:
            # short keywords must match a whole word ("bus" != "business")
            pattern = r"\b" + re.escape(kw) + (r"\b" if len(kw) <= 4 else "")
            if re.search(pattern, norm_desc):
                return category
    return None


class Categorizer:
    def __init__(self, manual_examples=()):
        self.memory = {normalize(d): c for d, c in manual_examples if c in CATEGORIES}
        texts = [normalize(t) for t, _ in SEED_EXAMPLES]
        labels = [c for _, c in SEED_EXAMPLES]
        for desc, cat in manual_examples:  # user corrections count double
            if cat in CATEGORIES:
                texts += [normalize(desc)] * 2
                labels += [cat] * 2
        self.model = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)),
            LogisticRegression(max_iter=2000, C=20),
        )
        self.model.fit(texts, labels)

    def predict(self, description, amount):
        """Return (category, source)."""
        norm = normalize(description)
        if norm in self.memory:
            return self.memory[norm], "memory"
        if amount > 0:
            return "Income", "rule"
        cat = rule_category(norm)
        if cat:
            return cat, "rule"
        if norm:
            probs = self.model.predict_proba([norm])[0]
            best = probs.argmax()
            if probs[best] >= MODEL_THRESHOLD:
                return self.model.classes_[best], "model"
        return "Other", "default"
