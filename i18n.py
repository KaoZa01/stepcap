"""Thai / English. Code keeps its Thai text and wraps it in tr("..."); the
English for each Thai string lives in ui/en.json, which the page reads too.
LANG is process-wide: the app sets it at start and when Settings change it."""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path

LANGS = ("th", "en")
LANG = "th"
EN: dict = json.loads((Path(__file__).resolve().parent / "ui" / "en.json")
                      .read_text(encoding="utf-8"))
_PH = re.compile(r"\{(\w+)\}")


def set_lang(lang: str) -> None:
    global LANG
    if lang in LANGS:
        LANG = lang


def tr(th: str, **kw) -> str:
    """th in the current language; {name} filled from kw. A key + "#1" entry
    is the English singular, used when n == 1."""
    s = th
    if LANG == "en":
        s = EN.get(th + "#1") if kw.get("n") == 1 and th + "#1" in EN else EN.get(th, th)
    return _PH.sub(lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), s) if kw else s


@contextmanager
def using(lang: str):
    old = LANG
    set_lang(lang)
    try:
        yield
    finally:
        set_lang(old)
