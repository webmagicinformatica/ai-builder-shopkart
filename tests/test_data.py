"""Checks that the shared fixtures load and agree with the course facts."""
import re
from collections import Counter
from datetime import date

from shopkart import data


def test_today_is_fixed(monkeypatch):
    monkeypatch.delenv("SHOPKART_TODAY", raising=False)
    assert data.today() == date(2026, 11, 17)
    monkeypatch.setenv("SHOPKART_TODAY", "2026-12-01")
    assert data.today() == date(2026, 12, 1)


def test_policies_current_and_archived():
    current = data.load_policies()
    assert 10 <= len(current) <= 14
    assert all(p.is_current for p in current)
    for p in current:
        words = len(p.text.split())
        assert 300 <= words <= 900, (p.doc_id, words)
    every = data.load_policies(include_archived=True)
    assert {"returns-2024", "price-match", "footwear-v1"} <= {p.doc_id for p in every}
    assert data.load_policy("price-match").status == "withdrawn"


def test_policy_facts():
    returns = data.load_policy("returns-and-refunds").text
    assert "**14 days of delivery**" in returns
    assert "Within 10 days" in data.load_policy("footwear").text or "within 10 days" in data.load_policy("footwear").text
    assert "above ₹5,000 needs a human" in data.load_policy("refunds").text
    # Gift *returns* must stay unanswered by the policies (they are must-hand-over cases).
    for p in data.load_policies():
        assert not re.search(r"(return|returning)\w* (a |an )?(gift|present)s?\b", p.text, re.I), p.doc_id


def test_sections_keep_heading_path():
    secs = data.sections(data.load_policy("returns-and-refunds"))
    s21 = next(s for s in secs if s.number == "2.1")
    assert s21.title == "Return window"
    assert s21.heading_path == ("Returns and Refunds Policy", "2. Returns", "2.1 Return window")
    assert "14 days" in s21.text


def test_orders():
    orders = data.load_orders()
    assert len(orders) == 40
    assert all(data.ORDER_ID_RE.match(o["order_id"]) for o in orders)
    assert any(o["total_inr"] > 5000 for o in orders)
    for o in orders:
        assert o["total_inr"] == o["subtotal_inr"] - o["discount_inr"] + o["delivery_fee_inr"] + o["cod_fee_inr"]
    o = data.get_order("sk-48213")
    assert o["items"][0]["category"] == "electronics" and o["total_inr"] == 1299
    assert data.days_since_delivery(o) == 4
    assert data.get_order("48213") is None
    assert data.get_order("SK00000") is None
    assert data.get_order("SK48190")["delivery_fee_inr"] == 49  # ₹799 to Kochi


def test_customers_link_to_orders():
    meera = data.get_customer("C1042")
    assert meera["name"] == "Meera Nair"
    assert {o["order_id"] for o in data.orders_for_customer("C1042")} == set(meera["order_ids"])


def test_tickets():
    tickets = data.load_tickets()
    assert 55 <= len(tickets) <= 65
    assert len(data.load_tickets("injection")) >= 5
    assert len(data.load_tickets("pii")) >= 4
    assert any(t["language"] in ("hinglish", "hi") for t in tickets)
    ids = {o["order_id"] for o in data.load_orders()}
    assert all(t["order_id"] in ids for t in tickets if t["order_id"])


def test_golden_set_shape():
    g = data.load_golden()
    assert len(g) == 150
    assert Counter(x["category"] for x in g) == {"everyday": 90, "hard": 35, "must_handover": 25}
    assert all(x["must_handover"] == (x["category"] == "must_handover") for x in g)
    assert len({x["id"] for x in g}) == 150
    for x in g:
        assert {"id", "category", "question", "expected", "must_handover", "source_docs"} <= x.keys()


def test_rag50_points_at_real_sections():
    rag = data.load_rag50()
    assert len(rag) == 50
    golden = {x["id"]: x for x in data.load_golden()}
    for r in rag:
        secs = data.sections(data.load_policy(r["source_doc"]))
        match = [s for s in secs if s.number == r["section"]]
        assert match and match[0].title == r["section_title"], r["id"]
        assert golden[r["golden_id"]]["question"] == r["question"]


def test_invoices():
    files = {p.name for p in data.invoice_files()}
    exp = data.load_invoice_expected()
    assert len(exp) == 8 and {e["file"] for e in exp} == files
    errors = Counter(err for e in exp for err in e["expected_validation_errors"])
    assert {"total_mismatch", "missing_supplier_gstin", "low_quality_scan"} <= errors.keys()
    for e in exp:
        if "total_mismatch" not in e["expected_validation_errors"]:
            assert round(e["taxable_value_inr"] + e["cgst_inr"] + e["sgst_inr"] + e["igst_inr"], 2) == e["total_inr"]


def test_workload():
    w = data.load_workload()
    assert len(w) == 200
    assert len({x["question"] for x in w}) < 100   # plenty of repeats for caching
    assert {x["difficulty"] for x in w} == {"easy", "hard"}


def test_policy_pdfs_exist():
    names = {p.name for p in data.policy_pdfs()}
    assert {"shipping-and-delivery.pdf", "returns-and-refunds.pdf", "warranty-scanned.pdf"} <= names
