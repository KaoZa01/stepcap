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


def find_spans(text: str, rules: Iterable[str],
               custom: Iterable[str]) -> list[tuple[int, int]]:
    """(start, end) of every match, sorted, overlaps merged."""
    spans = []
    for r in rules:
        pat, ok = _PATTERNS.get(r), _CHECKS.get(r)
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
    for a, b in find_spans(text, list(rules), list(custom)):
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
