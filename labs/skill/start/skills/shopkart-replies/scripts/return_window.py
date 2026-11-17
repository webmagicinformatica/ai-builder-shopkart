"""Is a ShopKart return still inside its window? Counts the days, so the model doesn't.

    python scripts/return_window.py footwear 2026-11-05 --today 2026-11-17
    -> footwear: delivered 2026-11-05, 12 days ago. Window 10 days. OUTSIDE the window by 2 days.

Standard library only (it also runs in the Claude API's code execution sandbox).
"""

import argparse
import os
from datetime import date

WINDOWS = {  # days from delivery; 0 = not returnable
    "electronics": 7, "footwear": 10, "clothing": 14, "home": 14, "books": 14,
    "beauty": 7, "grocery": 0, "gift_card": 0, "other": 14,
}
ALIASES = {"home_kitchen": "home", "fashion": "clothing", "shoes": "footwear", "phones": "electronics"}


def check(category: str, delivered_on: date, today: date) -> str:
    cat = ALIASES.get(category.lower(), category.lower())
    window = WINDOWS.get(cat, 14)
    days = (today - delivered_on).days
    head = f"{cat}: delivered {delivered_on}, {days} days ago."
    if window == 0:
        return f"{head} Not returnable (damaged on arrival: report within 48 hours)."
    if days <= window:
        return f"{head} Window {window} days. INSIDE the window, {window - days} days left."
    return f"{head} Window {window} days. OUTSIDE the window by {days - window} days."


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("category", help="electronics, footwear, clothing, home, beauty, books, grocery")
    p.add_argument("delivered_on", help="YYYY-MM-DD")
    p.add_argument("--today", default=os.environ.get("SHOPKART_TODAY"), help="YYYY-MM-DD (default: today)")
    a = p.parse_args()
    today = date.fromisoformat(a.today) if a.today else date.today()
    print(check(a.category, date.fromisoformat(a.delivered_on), today))


if __name__ == "__main__":
    main()
