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
