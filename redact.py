"""Auto-redaction: rule-based matching (no AI) plus Windows OCR to find text.

Pure logic lives at the top (importable without Windows), the OCR glue below
it, the same split as recorder.py. test_redact.py covers both.
"""
from __future__ import annotations

import math
import re
from typing import Iterable

# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
RULES = ("email", "phone", "thai_id", "card", "bank")
PAD = 4  # px added around each found rect so the glyph edges are covered
MASK = "•••"

_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "phone": re.compile(r"(?<![\d+])(?:\+66[ -]?|0)\d(?:[ -]?\d){7,8}(?!\d)"),
    "thai_id": re.compile(r"(?<!\d)\d(?:[ -]?\d){12}(?!\d)"),
    "card": re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)"),
    "bank": re.compile(r"(?<!\d)\d{3}-?\d-?\d{5}-?\d(?!\d)"),
}


def _digits(s: str) -> list[int]:
    return [int(c) for c in s if c.isdigit()]


def _thai_id_ok(s: str) -> bool:
    d = _digits(s)
    return (11 - sum(d[i] * (13 - i) for i in range(12)) % 11) % 10 == d[12]


def _luhn_ok(s: str) -> bool:
    total = 0
    for i, v in enumerate(reversed(_digits(s))):
        if i % 2:
            v = v * 2 - 9 if v > 4 else v * 2
        total += v
    return total % 10 == 0


_CHECKS = {"thai_id": _thai_id_ok, "card": _luhn_ok}
# OCR splits emails at "@" and inside the name ("userl 1 @mail.com"); on
# image text take one extra word and spaces around "@" -- a word too many
# blurred beats a name left readable. Typed text keeps the strict pattern.
_OCR_PATTERNS = {**_PATTERNS, "email": re.compile(
    r"(?:[\w.+-]+ )?[\w.+-]+ ?@ ?[\w-]+(?: ?\. ?[\w-]+)+")}


def find_spans(text: str, rules: Iterable[str], custom: Iterable[str],
               ocr: bool = False) -> list[tuple[int, int]]:
    """(start, end) of every match, sorted, overlaps merged. ocr=True for
    text read from an image (looser email pattern)."""
    spans = []
    for r in rules:
        pat, ok = (_OCR_PATTERNS if ocr else _PATTERNS).get(r), _CHECKS.get(r)
        if pat is None:
            continue
        spans += [m.span() for m in pat.finditer(text) if not ok or ok(m.group())]
    for w in custom:
        w = w.strip()
        if w:
            spans += [m.span() for m in re.finditer(re.escape(w), text, re.I)]
    merged: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def mask_text(text: str, rules: Iterable[str], custom: Iterable[str]) -> str:
    out, last = [], 0
    for a, b in find_spans(text, rules, custom):
        out += [text[last:a], MASK]
        last = b
    return "".join(out) + text[last:]


def line_rects(words: list[tuple[str, tuple[float, float, float, float]]],
               rules: Iterable[str], custom: Iterable[str],
               size: tuple[int, int]) -> list[dict]:
    """Blur rects for one OCR line: words are joined with single spaces, so a
    number split into several words still matches as one."""
    text, pos = "", []
    for w, _ in words:
        if text:
            text += " "
        pos.append((len(text), len(text) + len(w)))
        text += w
    W, H = size
    out = []
    for a, b in find_spans(text, list(rules), list(custom), ocr=True):
        hit = [r for (s, e), (_, r) in zip(pos, words) if s < b and e > a]
        if not hit:
            continue
        x0 = max(0, math.floor(min(r[0] for r in hit) - PAD))
        y0 = max(0, math.floor(min(r[1] for r in hit) - PAD))
        x1 = min(W, math.ceil(max(r[0] + r[2] for r in hit) + PAD))
        y1 = min(H, math.ceil(max(r[1] + r[3] for r in hit) + PAD))
        if x1 > x0 and y1 > y0:
            out.append({"type": "blur", "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    return out


def new_rects(found: list[dict], existing: list[dict]) -> list[dict]:
    """found minus the rects already fully inside an existing redaction."""
    def inside(a, b):
        return (a["x"] >= b["x"] and a["y"] >= b["y"]
                and a["x"] + a["w"] <= b["x"] + b["w"]
                and a["y"] + a["h"] <= b["y"] + b["h"])
    return [f for f in found if not any(inside(f, e) for e in existing)]


# ---------------------------------------------------------------------------
# Windows OCR glue (Windows.Media.Ocr via pywinrt; en-US only, no Thai)
# ---------------------------------------------------------------------------
import threading
from pathlib import Path


class RedactError(Exception):
    """Message is Thai and shown to the user."""


_LOCK = threading.Lock()  # ponytail: one OCR at a time; fine for a personal app
_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.media.ocr import OcrEngine
        except Exception:
            raise RedactError("โหลดตัวอ่านตัวอักษรไม่ได้")
        eng = OcrEngine.try_create_from_language(Language("en-US"))
        if eng is None:
            raise RedactError("ไม่มี OCR ภาษาอังกฤษในเครื่อง")
        _ENGINE = eng
    return _ENGINE


def available() -> str | None:
    """None when OCR works here, else the Thai reason it doesn't."""
    try:
        with _LOCK:
            _engine()
        return None
    except RedactError as e:
        return str(e)
    except Exception:  # COM / OS errors from WinRT
        return "เปิดตัวอ่านตัวอักษรไม่ได้"


def ocr_lines(path: Path) -> list[list[tuple[str, tuple[float, float, float, float]]]]:
    """Words of each OCR line with (x, y, w, h) in the file's own pixels."""
    import asyncio
    from PIL import Image
    try:
        with Image.open(path) as im:
            img = _upright(im).convert("RGBA")
    except Exception:
        raise RedactError("อ่านภาพไม่ได้")
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter
    W, H = img.size
    s = min(1.0, OcrEngine.max_image_dimension / max(W, H))
    if s < 1:  # OCR refuses bigger images; rects are scaled back below
        img = img.resize((max(1, int(W * s)), max(1, int(H * s))))
    r, g, b, a = img.split()
    data = Image.merge("RGBA", (b, g, r, a)).tobytes()  # BGRA8
    w = DataWriter()
    w.write_bytes(data)
    bmp = SoftwareBitmap.create_copy_from_buffer(
        w.detach_buffer(), BitmapPixelFormat.BGRA8, img.width, img.height)
    with _LOCK:
        eng = _engine()
        try:
            res = asyncio.run(_recognize(eng, bmp))
        except Exception:
            raise RedactError("อ่านตัวอักษรในภาพไม่สำเร็จ")
    return [[(wd.text, (wd.bounding_rect.x / s, wd.bounding_rect.y / s,
                        wd.bounding_rect.width / s, wd.bounding_rect.height / s))
             for wd in line.words] for line in res.lines]


def _upright(im):
    """As the page draws it: browsers apply a JPEG's EXIF rotation."""
    from PIL import ImageOps
    return ImageOps.exif_transpose(im)


async def _recognize(engine, bmp):
    return await engine.recognize_async(bmp)


def find_rects(path: Path, rules: Iterable[str], custom: Iterable[str]) -> list[dict]:
    """Blur rects for everything in the image that matches the rules."""
    from PIL import Image
    lines = ocr_lines(path)
    with Image.open(path) as im:
        size = _upright(im).size
    rules, custom = list(rules), list(custom)
    return [r for ln in lines for r in line_rects(ln, rules, custom, size)]


def redact_guide(storage: Path, guide: dict, rules: Iterable[str], custom: Iterable[str],
                 progress=None, find=find_rects) -> list[int]:
    """Blur matches in every image step of a guide on disk, write guide.json
    once, and return the step numbers (as the page numbers them: notes don't
    count) whose image could not be checked: GIF, missing, unreadable."""
    import library
    folder = storage / guide["id"]
    rules, custom = list(rules), list(custom)
    todo, n = [], 0
    for s in guide["steps"]:
        if s.get("kind") != "note":
            n += 1
            if s.get("image"):
                todo.append((n, s))
    failed = []
    for i, (num, s) in enumerate(todo, 1):
        p = folder / s["image"]
        if p.suffix.lower() == ".gif" or not p.is_file():
            failed.append(num)
        else:
            try:
                s["redactions"] = (s.get("redactions") or []) + new_rects(
                    find(p, rules, custom), s.get("redactions") or [])
            except RedactError:
                failed.append(num)
        if progress:
            progress(i, len(todo))
    guide.pop("redact_pending", None)  # checked: opening it no longer re-runs the pass
    library.write_json_atomic(folder / "guide.json", guide)
    return failed
