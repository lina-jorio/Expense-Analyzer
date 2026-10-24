"""Data analysis with pandas: summaries, monthly trends, forecast, anomalies."""
import pandas as pd


def to_df(transactions):
    df = pd.DataFrame(transactions, columns=["id", "date", "description", "amount", "category", "source"])
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.strftime("%Y-%m")
    return df


def _expenses(df):
    exp = df[(df["amount"] < 0) & (df["category"] != "Income")].copy()
    exp["spent"] = -exp["amount"]
    return exp


def available_months(df):
    return sorted(df["month"].unique().tolist(), reverse=True)


def summary(df):
    exp = _expenses(df)
    income = float(df.loc[df["amount"] > 0, "amount"].sum())
    spent = float(exp["spent"].sum())
    n_months = max(df["month"].nunique(), 1)
    return {
        "spent": round(spent, 2),
        "income": round(income, 2),
        "net": round(income - spent, 2),
        "avg_month": round(spent / n_months, 2),
        "count": int(len(df)),
    }


def by_category(df):
    exp = _expenses(df)
    if exp.empty:
        return []
    totals = exp.groupby("category")["spent"].sum().sort_values(ascending=False)
    grand = totals.sum()
    return [{"category": c, "total": round(float(v), 2), "share": round(float(v / grand * 100), 1)}
            for c, v in totals.items()]


def monthly(df):
    exp = _expenses(df)
    spent = exp.groupby("month")["spent"].sum()
    income = df[df["amount"] > 0].groupby("month")["amount"].sum()
    months = sorted(df["month"].unique())
    return [{"month": m, "spent": round(float(spent.get(m, 0)), 2),
             "income": round(float(income.get(m, 0)), 2)} for m in months]


def forecast(df, window=3):
    """Weighted moving average per category over the last `window` months
    (most recent month weighs most). Returns None if there is no data."""
    exp = _expenses(df)
    months = sorted(df["month"].unique())
    if exp.empty or not months:
        return None
    last = months[-window:]
    weights = list(range(1, len(last) + 1))
    pivot = (exp[exp["month"].isin(last)].pivot_table(
        index="category", columns="month", values="spent", aggfunc="sum", fill_value=0)
        .reindex(columns=last, fill_value=0))
    items = []
    for category, row in pivot.iterrows():
        value = sum(w * row[m] for w, m in zip(weights, last)) / sum(weights)
        items.append({"category": category, "forecast": round(float(value), 2)})
    items.sort(key=lambda x: x["forecast"], reverse=True)
    next_month = (pd.Period(months[-1], "M") + 1).strftime("%Y-%m")
    return {"month": next_month, "total": round(sum(i["forecast"] for i in items), 2),
            "items": items, "based_on": last}


def anomalies(df, min_samples=5, threshold=3.5, top=10):
    """Flag unusually large expenses within their category using the modified
    z-score (median / MAD), which is robust to the outliers we are hunting."""
    exp = _expenses(df)
    found = []
    for category, group in exp.groupby("category"):
        if len(group) < min_samples:
            continue
        median = group["spent"].median()
        mad = (group["spent"] - median).abs().median()
        for _, row in group.iterrows():
            if mad > 0:
                score = 0.6745 * (row["spent"] - median) / mad
                flagged = score >= threshold
            else:  # (almost) identical amounts: flag anything above double the usual
                flagged = row["spent"] > 2 * median and median > 0
                score = row["spent"] / median if median else 0
            if flagged:
                found.append({
                    "id": int(row["id"]), "date": row["date"].strftime("%Y-%m-%d"),
                    "description": row["description"], "category": category,
                    "amount": round(float(row["spent"]), 2), "usual": round(float(median), 2),
                    "score": round(float(score), 1),
                })
    found.sort(key=lambda x: x["score"], reverse=True)
    return found[:top]
