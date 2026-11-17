"""The invoice lab's checkpoints, with fake servers (no key, no network, no cost).

Against the finished answer:   uv run pytest labs/invoices -q
Against your copy:             LAB=start uv run pytest labs/invoices -q
Part 1 only:                   LAB=start uv run pytest labs/invoices -q -k part1
"""

import importlib
import json
import os
import sys
from pathlib import Path

import httpx2
import pytest

from shopkart import budget, data
from shopkart.llm import LLM
from tests.fakes import FakeServer, anthropic_message, openai_response

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")
NAMES = ["pages", "extract", "checks", "review", "pipeline", "score"]


def _load_all():
    """Import the lab's modules from FOLDER, without clashing with other labs' modules of the same name."""
    saved = {n: sys.modules.pop(n) for n in NAMES if n in sys.modules}
    sys.path.insert(0, str(FOLDER))
    try:
        return {n: importlib.import_module(n) for n in NAMES}
    finally:
        sys.path.remove(str(FOLDER))
        for n in NAMES:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


M = _load_all()
pages, extract, checks, review, pipeline, score = (M[n] for n in NAMES)

EXPECTED = data.load_invoice_expected()
FILES = {f.name: f for f in data.invoice_files()}
META = {"file", "expected_validation_errors", "note"}


def invoice_json(e: dict) -> str:
    return json.dumps({k: v for k, v in e.items() if k not in META})


def answer(provider: str, text: str):
    return anthropic_message(text, input_tokens=3200, output_tokens=330) if provider == "anthropic" \
        else openai_response(text, input_tokens=1700, output_tokens=170)


def make(server: FakeServer) -> LLM:
    http = httpx2.Client(transport=httpx2.MockTransport(server))
    return LLM(server.provider, http_client=http, sleep=lambda s: None)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


# ============================ Part 1: document -> validated JSON ============================


def test_part1_a_pdf_becomes_one_image_per_page():
    imgs = pages.load_pages(FILES["inv-01-sunrise-textiles.pdf"])
    assert len(imgs) == 1
    assert imgs[0].size == (1241, 1754)  # A4 at 150 dpi
    assert imgs[0].mode == "RGB"


def test_part1_a_photo_is_one_page():
    imgs = pages.load_pages(FILES["inv-06-nimbus-devices.png"])
    assert len(imgs) == 1 and imgs[0].mode == "RGB"


def test_part1_blank_margins_are_trimmed_and_the_size_is_capped():
    sent = pages.prepare(FILES["inv-01-sunrise-textiles.pdf"])[0]
    assert sent.height < 1754 * 0.6  # the empty bottom half of the A4 page is gone
    assert max(sent.size) <= pages.MAX_SIDE
    from PIL import Image
    assert max(pages.fit(Image.new("RGB", (4000, 3000))).size) == pages.MAX_SIDE


def test_part1_image_tokens_are_28_pixel_patches():
    from PIL import Image
    assert pages.image_tokens(Image.new("RGB", (1000, 1000))) == 36 * 36  # about thirteen hundred
    assert pages.image_tokens(Image.new("RGB", (28, 29))) == 2


def test_part1_the_blurred_photo_scores_low_on_sharpness():
    scores = {name: pages.sharpness(pages.load_pages(f)[0]) for name, f in FILES.items()}
    assert scores["inv-06-nimbus-devices.png"] < checks.BLUR_LIMIT
    assert all(s > checks.BLUR_LIMIT for n, s in scores.items() if n != "inv-06-nimbus-devices.png")


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_part1_extract_sends_the_page_image_and_the_schema(provider):
    e = EXPECTED[0]
    server = FakeServer(provider, [answer(provider, invoice_json(e))])
    ex = extract.extract(make(server), FILES[e["file"]])
    assert ex.error is None
    assert isinstance(ex.invoice, extract.Invoice)
    assert ex.invoice.supplier_gstin == "27ABCFS7710K1ZY" and ex.invoice.total_inr == 44940
    assert len(ex.invoice.line_items) == 2
    sent = server.requests[0]
    if provider == "anthropic":
        content = sent["messages"][0]["content"]
        assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
        assert sent["output_config"]["format"]["type"] == "json_schema"
    else:
        content = sent["input"][0]["content"]
        assert content[0]["type"] == "input_image"
        assert content[0]["image_url"].startswith("data:image/png;base64,")
        assert sent["text"]["format"]["type"] == "json_schema"
    assert ex.cost_usd > 0 and budget.spent_today() == pytest.approx(ex.cost_usd)


def test_part1_a_second_run_comes_from_the_cache_at_no_cost():
    e = EXPECTED[0]
    server = FakeServer("anthropic", [answer("anthropic", invoice_json(e))])
    llm = make(server)
    extract.extract(llm, FILES[e["file"]])
    again = extract.extract(llm, FILES[e["file"]])
    assert server.calls == 1
    assert again.cached and again.cost_usd == 0 and again.invoice.total_inr == 44940


def test_part1_dates_and_gstins_are_normalised_in_code():
    e = dict(EXPECTED[3], invoice_date="08/11/2026", supplier_gstin="33aaqfs 5532d1z8")
    inv = extract.Invoice.model_validate_json(invoice_json(e))
    assert inv.invoice_date == "2026-11-08"  # DD/MM/YYYY, the Indian way
    assert inv.supplier_gstin == "33AAQFS5532D1Z8"


def test_part1_an_answer_that_stays_invalid_is_an_error_not_a_crash():
    bad = invoice_json(dict(EXPECTED[0], invoice_date="31/02/2026"))
    server = FakeServer("anthropic", [answer("anthropic", bad), answer("anthropic", bad)])
    ex = extract.extract(make(server), FILES[EXPECTED[0]["file"]])
    assert ex.invoice is None and "schema" in ex.error
    assert server.calls == 2  # one retry, with the error, then a person


def test_part1_the_estimate_needs_no_call():
    tokens, usd = extract.estimate(FILES["inv-01-sunrise-textiles.pdf"], "claude-haiku-5-5")
    assert 2500 < tokens < 4500 and 0 < usd < 0.001


# ============================ Part 2: rules, review queue, accuracy ============================


def test_part2_every_real_gstin_passes_its_check_character():
    for e in EXPECTED:
        for g in (e["supplier_gstin"], e["buyer_gstin"]):
            if g:
                assert checks.gstin_check_char(g[:14]) == g[14], g
                assert checks.gstin_problem(g) is None


def test_part2_a_misread_gstin_fails():
    assert "check character" in checks.gstin_problem("29AAECN5604H1ZD")  # a 6 read as a 5
    assert "format" in checks.gstin_problem("33AAQF55532D1Z8")          # an S read as a 5
    assert "state code" in checks.gstin_problem("99AAECN6604H1ZD")


@pytest.mark.parametrize("e", EXPECTED, ids=lambda e: e["file"])
def test_part2_the_rules_flag_exactly_the_expected_errors(e):
    inv = extract.Invoice.model_validate_json(invoice_json(e))
    sharp = pages.sharpness(pages.load_pages(FILES[e["file"]])[0])
    codes = {i.code for i in checks.validate(inv, sharp)}
    assert codes == set(e["expected_validation_errors"])


def _inv(**changes):
    return extract.Invoice.model_validate_json(invoice_json({**EXPECTED[0], **changes}))


def test_part2_lines_must_add_up_to_the_subtotal():
    codes = {i.code for i in checks.validate(_inv(taxable_value_inr=52800.0, total_inr=54940.0, cgst_inr=1070.0))}
    assert "subtotal_mismatch" in codes


def test_part2_cgst_sgst_in_state_igst_across_states():
    # Sunrise (27) to Maharashtra (27) charged IGST: wrong tax type.
    issues = checks.validate(_inv(cgst_inr=0.0, sgst_inr=0.0, igst_inr=2140.0))
    assert [i.code for i in issues] == ["wrong_tax_type"]
    # A Karnataka seller (29) charging CGST + SGST to Maharashtra: also wrong.
    issues = checks.validate(_inv(supplier_gstin="29AAECN6604H1ZD"))
    assert [i.code for i in issues] == ["wrong_tax_type"]


def test_part2_missing_values_are_flagged_not_guessed():
    codes = {i.code for i in checks.validate(_inv(total_inr=None, invoice_number=None))}
    assert codes == {"missing_total_inr", "missing_invoice_number"}


def _store(q, e, reasons=(), sha=None):
    return q.store(file=e["file"], sha256=sha or e["file"], data=json.loads(invoice_json(e)),
                   reasons=list(reasons), model="claude-haiku-5-5", prompt_version="inv-v1", cost_usd=0.0005)


def test_part2_clean_invoices_go_straight_through_the_rest_wait_for_a_person(tmp_path):
    q = review.ReviewQueue(tmp_path / "q.db")
    assert _store(q, EXPECTED[0])[1] == "approved"
    assert _store(q, EXPECTED[3], ["total_mismatch: ..."])[1] == "review"
    row = q.get(1)
    assert row["decided_by"] == "pipeline" and row["sha256"] and row["model"] == "claude-haiku-5-5"
    assert [r["file"] for r in q.rows("review")] == ["inv-04-stride-footwear.pdf"]


def test_part2_storing_twice_is_safe(tmp_path):
    q = review.ReviewQueue(tmp_path / "q.db")
    first = _store(q, EXPECTED[0])
    again = _store(q, EXPECTED[0])
    assert again == (first[0], "approved", False)
    assert len(q.rows()) == 1


def test_part2_the_same_invoice_as_a_pdf_and_a_photo_is_held_as_a_duplicate(tmp_path):
    q = review.ReviewQueue(tmp_path / "q.db")
    _store(q, EXPECTED[0])
    photo = dict(EXPECTED[0], file="inv-01-photo.jpg")
    row_id, status, new = _store(q, photo, sha="different-bytes")
    assert (status, new) == ("duplicate", True)
    assert "duplicate" in q.get(row_id)["reasons"]
    with pytest.raises(ValueError, match="duplicate"):
        q.decide(row_id, approve=True)
    assert q.decide(row_id, approve=False, note="paid once already")["status"] == "rejected"


def test_part2_a_person_approves_with_a_correction_or_rejects(tmp_path):
    q = review.ReviewQueue(tmp_path / "q.db")
    rid = _store(q, EXPECTED[3], ["total_mismatch: ..."])[0]
    row = q.decide(rid, approve=True, note="supplier confirmed", fixes={"total_inr": 279104.0})
    assert (row["status"], row["decided_by"], row["total_inr"]) == ("approved", "person", 279104.0)
    assert json.loads(row["corrections"]) == {"total_inr": {"was": 283604.0, "now": 279104.0}}
    assert json.loads(row["data"])["total_inr"] == 283604.0  # the model's reading is kept
    assert q.final(row)["total_inr"] == 279104.0
    with pytest.raises(ValueError):
        q.decide(rid, approve=False)  # already decided


def test_part2_the_review_cli(tmp_path, capsys):
    db = str(tmp_path / "q.db")
    q = review.ReviewQueue(db)
    _store(q, EXPECTED[0])
    _store(q, EXPECTED[7], ["tax_mismatch: tax charged is ₹9,840.00, but the line rates give ₹4,100.00"])
    assert review.main(["--db", db, "list"]) == 0
    out = capsys.readouterr().out
    assert "inv-08-desi-dryfruits.pdf" in out and "tax_mismatch" in out and "inv-01" not in out
    assert review.main(["--db", db, "reject", "2", "--note", "wrong rate"]) == 0
    assert review.main(["--db", db, "approve", "2"]) == 1  # already rejected
    assert review.main(["--db", db, "approve", "1", "--set", "total_inr=1"]) == 1  # approved by the pipeline


def test_part2_the_whole_pipeline_and_its_score(tmp_path, capsys):
    """8 invoices through fake Claude: 4 straight through, 4 to review, every field right."""
    files = data.invoice_files()
    by_file = {e["file"]: e for e in EXPECTED}
    server = FakeServer("anthropic", [answer("anthropic", invoice_json(by_file[f.name])) for f in files])
    db = tmp_path / "q.db"
    counts = pipeline.run(make(server), files, review.ReviewQueue(db))
    assert counts == {"approved": 4, "review": 4, "duplicate": 0, "rejected": 0}
    assert server.calls == 8
    pipeline.run(make(server), files, review.ReviewQueue(db))  # again: cached, stored once
    assert server.calls == 8 and len(review.ReviewQueue(db).rows()) == 8
    capsys.readouterr()

    assert score.main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "all fields            100%" in out
    assert "Straight through: 4 of 8" in out
    assert "Flags as expected: 8 of 8" in out
    assert "slipped past every check: 0" in out


def test_part2_score_catches_a_wrong_value_that_slipped_through(tmp_path, capsys):
    db = tmp_path / "q.db"
    q = review.ReviewQueue(db)
    wrong = dict(EXPECTED[0], invoice_number="ST/2026-27/0417")  # misread, and no rule can see it
    _store(q, wrong)
    assert score.main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "slipped past every check: 1" in out and "invoice_number" in out
