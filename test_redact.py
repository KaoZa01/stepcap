"""Self-check for auto-redaction. Run: python test_redact.py"""
import sys
import tempfile
from pathlib import Path

from redact import RULES, find_spans, line_rects, mask_text, new_rects

TMP = Path(tempfile.mkdtemp(prefix="stepcap-redact-"))


def _text_png(text, size, at=(20, 20)):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", size, "white")
    ImageDraw.Draw(img).text(at, text, fill="black", font=ImageFont.truetype("arial.ttf", 28))
    p = TMP / f"{abs(hash((text, size, at)))}.png"
    img.save(p)
    return p


def test_email_and_custom():
    assert find_spans("mail me@x.co now", RULES, []) == [(5, 12)]
    assert find_spans("ACME Corp", [], ["acme"]) == [(0, 4)]


def test_phone_formats():
    for s in ("081-234-5678", "081 234 5678", "0812345678", "02-123-4567",
              "+66 81 234 5678"):
        assert find_spans(s, ["phone"], []) == [(0, len(s))], s


def test_checksums_reject():
    assert find_spans("1101700230708", ["thai_id"], []) == [(0, 13)]  # valid checksum
    assert find_spans("1101700230705", ["thai_id"], []) == []         # last digit wrong
    assert find_spans("1234567890123", ["thai_id", "card"], []) == []
    assert find_spans("4111 1111 1111 1111", ["card"], []) == [(0, 19)]


def test_bank_account():
    assert find_spans("acct 123-4-56789-0", ["bank"], []) == [(5, 18)]


def test_mask_text():
    assert mask_text('พิมพ์ "me@x.co" ในช่อง', RULES, []) == 'พิมพ์ "•••" ในช่อง'


def test_rules_off():
    assert find_spans("me@x.co 0812345678", [], []) == []


def test_rects_join_split_words():
    words = [("call", (0, 0, 40, 20)), ("081", (50, 0, 30, 20)),
             ("234", (85, 0, 30, 20)), ("5678", (120, 0, 40, 20))]
    assert line_rects(words, RULES, [], (400, 100)) == \
        [{"type": "blur", "x": 46, "y": 0, "w": 118, "h": 24}]


def test_rects_email_split_by_ocr():
    # OCR often breaks an email at "@" and inside the name: still one blur over all of it
    words = [("sample", (0, 0, 60, 20)), ("userl", (70, 0, 40, 20)),
             ("1", (112, 0, 8, 20)), ("@mail.com", (122, 0, 80, 20))]
    assert line_rects(words, ["email"], [], (400, 100)) == \
        [{"type": "blur", "x": 66, "y": 0, "w": 140, "h": 24}]
    assert mask_text("text me @x.co", ["email"], []) == "text me @x.co"  # typed text stays strict


def test_rects_email_split_after_dot():
    words = [("user@mail.", (0, 0, 80, 20)), ("com", (84, 0, 30, 20))]
    assert line_rects(words, ["email"], [], (400, 100)) == \
        [{"type": "blur", "x": 0, "y": 0, "w": 118, "h": 24}]


def test_ocr_follows_exif_rotation():
    # a phone JPEG stored sideways: rects must be in the upright picture the page draws
    from PIL import Image, ImageDraw, ImageFont
    from redact import find_rects
    up = Image.new("RGB", (640, 120), "white")
    ImageDraw.Draw(up).text((300, 40), "someone@example.com", fill="black",
                            font=ImageFont.truetype("arial.ttf", 28))
    exif = Image.Exif()
    exif[0x0112] = 6  # viewer turns it 90° clockwise
    p = TMP / "rot.jpg"
    up.rotate(90, expand=True).save(p, "JPEG", quality=95, exif=exif)
    r = find_rects(p, ["email"], [])
    assert len(r) == 1 and 280 <= r[0]["x"] <= 310 and r[0]["y"] < 60, r


def test_rects_clamped():
    r = line_rects([("me@x.co", (2, 1, 60, 18))], RULES, [], (60, 18))[0]
    assert (r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]) == (0, 0, 60, 18)


def test_new_rects_skips_covered():
    a = {"type": "blur", "x": 10, "y": 10, "w": 50, "h": 20}
    assert new_rects([a], [{"type": "black", "x": 0, "y": 0, "w": 100, "h": 100}]) == []
    assert new_rects([a], []) == [a]


def test_ocr_finds_email_rect():
    from redact import find_rects
    p = _text_png("contact: someone@example.com", (640, 80))
    rs = find_rects(p, RULES, [])
    assert len(rs) == 1 and rs[0]["x"] < 160 < rs[0]["x"] + rs[0]["w"], rs
    assert rs[0]["x"] > 100, rs  # "contact:" stays readable


def test_ocr_large_image_scales_back():
    from redact import find_rects
    p = _text_png("0812345678", (12000, 300), at=(11000, 200))
    r = find_rects(p, ["phone"], [])[0]
    assert 10985 <= r["x"] <= 11010, r


def test_unreadable_image_raises():
    from redact import RedactError, find_rects
    bad = TMP / "bad.png"
    bad.write_bytes(b"\x89PNG junk")
    try:
        find_rects(bad, RULES, [])
        assert False, "no error"
    except RedactError:
        pass


def test_redact_guide_marks_and_reports():
    import json
    from redact import redact_guide
    st = TMP / "store"
    (st / "g1").mkdir(parents=True)
    (st / "g1" / "a.png").write_bytes(b"png")
    (st / "g1" / "c.gif").write_bytes(b"gif")
    guide = {"id": "g1", "redact_pending": True, "steps": [
        {"id": "s1", "image": "a.png", "redactions": []},
        {"id": "n", "kind": "note", "image": None},          # not an image step
        {"id": "s2", "image": "c.gif", "redactions": []},
        {"id": "s3", "image": "gone.png", "redactions": []}]}
    seen = []
    rect = {"type": "blur", "x": 1, "y": 2, "w": 3, "h": 4}
    failed = redact_guide(st, guide, RULES, [], progress=lambda d, n: seen.append((d, n)),
                          find=lambda p, r, c: [rect])
    assert failed == [2, 3], failed     # numbered like the page: notes don't count
    assert guide["steps"][0]["redactions"] == [rect]
    disk = json.loads((st / "g1" / "guide.json").read_text(encoding="utf-8"))
    assert disk["steps"][0]["redactions"] == [rect]
    assert "redact_pending" not in disk
    assert seen[-1] == (3, 3), seen


def _app():
    """app.py in this process, on its own temp storage (never the real one)."""
    import os
    st = TMP / "appstore"
    st.mkdir(exist_ok=True)
    os.environ["STEPCAP_STORAGE"] = str(st)
    import app
    assert app.STORAGE == st
    return app


def _pending_guide(st, gid):
    import json
    (st / gid).mkdir()
    (st / gid / "p.png").write_bytes(_text_png("mail someone@example.com", (640, 80)).read_bytes())
    g = {"id": gid, "title": "t", "created": "2026-10-16T10:00:00", "redact_pending": True,
         "steps": [{"id": "s1", "kind": "click", "text": "x", "image": "p.png", "redactions": []}]}
    (st / gid / "guide.json").write_text(json.dumps(g), encoding="utf-8")
    return g


def test_stop_gates_guide_until_redacted():
    import threading
    app = _app()
    gate, started = threading.Event(), threading.Event()
    real = app.redact.redact_guide

    def slow(*a, **k):
        started.set()
        gate.wait(10)
        return real(*a, **k)
    g = _pending_guide(app.STORAGE, "gstop")
    app.REC = type("R", (), {"stop_recording": lambda self: dict(g), "monitors": [],
                             "recording": False, "paused": False, "selected": 0,
                             "hooks_ok": True, "hook_error": 0, "live": lambda self: {}})()
    app.OV = type("O", (), {"hide_panel": lambda self: None})()
    app.main_hwnd = lambda: None
    app.recorder.set_capture_excluded = lambda h, on: True
    app.redact.redact_guide = slow
    try:
        seq = app.GUIDE_SEQ
        app.stop_rec_ui()
        assert started.wait(10)
        assert app.guide_for_page("gstop") == 409       # page must wait
        assert app.rec_status()["redacting"] is not None
        assert app.GUIDE_SEQ == seq                      # not opened yet
        gate.set()
        for _ in range(100):
            if app.GUIDE_SEQ != seq:
                break
            threading.Event().wait(0.1)
        assert app.GUIDE_SEQ == seq + 1 and app.LAST_GUIDE == "gstop"
        got = app.guide_for_page("gstop")
        assert len(got["steps"][0]["redactions"]) == 1 and "redact_pending" not in got, got
        assert app.rec_status()["redacting"] is None
    finally:
        app.redact.redact_guide = real


def test_pending_guide_redacted_when_opened():
    # the app quit mid-pass: opening the guide finishes the job first
    app = _app()
    _pending_guide(app.STORAGE, "gquit")
    got = app.guide_for_page("gquit")
    assert len(got["steps"][0]["redactions"]) == 1 and "redact_pending" not in got, got


def test_unchecked_guide_warns_until_checked():
    app = _app()
    _pending_guide(app.STORAGE, "gnote")
    real = app.redact.available
    app.redact.available = lambda: "ไม่มี OCR ภาษาอังกฤษในเครื่อง"
    try:
        for _ in range(2):  # still unchecked: says so on every open
            got = app.guide_for_page("gnote")
            assert "ไม่มี OCR" in got["redact_note"] and got["redact_pending"], got
    finally:
        app.redact.available = real
    got = app.guide_for_page("gnote")  # OCR back: checked, blurred, quiet
    assert "redact_note" not in got and "redact_pending" not in got, got
    assert len(got["steps"][0]["redactions"]) == 1


def test_page_doc_waits_for_redaction():
    import library
    app = _app()
    _pending_guide(app.STORAGE, "gpage")
    pid = library.create_page(app.STORAGE, "p")["id"]
    library.add_guide_to_page(app.STORAGE, pid, "gpage")
    app.REDACT_BUSY["gpage"] = [0, 1]
    try:
        assert app.page_doc(pid) == 409
    finally:
        app.REDACT_BUSY.pop("gpage", None)
    doc = app.page_doc(pid)  # pending guide is checked on the way
    assert doc["steps"][1]["id"] == "gpage.s1" and len(doc["steps"][1]["redactions"]) == 1, doc
    assert app.page_doc("nope") == 404


def test_available():
    from redact import available
    assert available() is None


if __name__ == "__main__":
    import traceback
    sys.stdout.reconfigure(encoding="utf-8")
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("ok  ", fn.__name__)
        except Exception:
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
