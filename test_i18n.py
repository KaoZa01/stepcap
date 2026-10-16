"""Language checks: tr() on the Python side, and a lint over the source that
fails on Thai text outside tr("...") and on table entries that are missing,
unused or malformed. Pure: no Windows, no app.
Run: python test_i18n.py"""
import ast
import re
from pathlib import Path

import i18n

HERE = Path(__file__).resolve().parent
# files whose Thai must all go through tr(); each task adds its own
FILES: list[str] = ["recorder.py", "library.py", "exporters.py", "redact.py", "app.py", "overlay.py",
                     "ui/common.js", "ui/tour.js", "ui/shell.js", "ui/index.html"]

THAI = re.compile("[\u0e00-\u0e7f]")
LIT = r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')'
CALL = re.compile(r"\btr\(\s*" + LIT)
BAD_CALL = re.compile(r"\btr\(\s*(?:f[\"']|`)")
PH = re.compile(r"\{(\w+)\}")


def _sources() -> list[Path]:
    py = [p for p in HERE.glob("*.py") if not p.name.startswith("test_")]
    return py + sorted((HERE / "ui").glob("*.js"))


def _used_keys() -> set:
    keys = set()
    for p in _sources():
        for m in CALL.finditer(p.read_text(encoding="utf-8")):
            k = ast.literal_eval(m.group(1))
            if THAI.search(k):  # keys are Thai text; skips tr("...") in prose
                keys.add(k)
    return keys


def _leaks(path: Path) -> list[str]:
    out = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if "i18n-ok" in line or s.startswith(("#", "//", "*", "/*")):
            continue
        if BAD_CALL.search(line) or THAI.search(CALL.sub("", line)):
            out.append(f"{path.name}:{no}: {s[:90]}")
    return out


class _Table:
    """Swap i18n.EN for one test."""
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        self.old, i18n.EN = i18n.EN, self.table

    def __exit__(self, *a):
        i18n.EN = self.old


def test_tr_thai_returns_key():
    assert i18n.LANG == "th"
    assert i18n.tr("พัก") == "พัก"
    assert i18n.tr("{n} ขั้นตอน", n=2) == "2 ขั้นตอน"


def test_tr_english_and_fallback():
    with _Table({"พัก": "Pause"}), i18n.using("en"):
        assert i18n.tr("พัก") == "Pause"
        assert i18n.tr("ไม่มีในตาราง") == "ไม่มีในตาราง"
    assert i18n.LANG == "th"


def test_tr_singular():
    with _Table({"{n} ขั้นตอน": "{n} steps", "{n} ขั้นตอน#1": "{n} step"}), i18n.using("en"):
        assert i18n.tr("{n} ขั้นตอน", n=1) == "1 step"
        assert i18n.tr("{n} ขั้นตอน", n=2) == "2 steps"


def test_tr_values_not_rescanned():
    assert i18n.tr("{a} {b}", a="{b}", b="x") == "{b} x"
    assert i18n.tr("{a}", a="$& {0}") == "$& {0}"


def test_set_lang_ignores_unknown():
    with i18n.using("th"):
        i18n.set_lang("fr")
        assert i18n.LANG == "th"


def test_no_thai_outside_tr():
    leaks = [x for f in FILES for x in _leaks(HERE / f)]
    assert not leaks, "\n" + "\n".join(leaks)


def test_tr_keys_are_in_table():
    missing = sorted(k for k in _used_keys() if k not in i18n.EN)
    assert not missing, missing


def test_no_unused_keys():
    used = _used_keys()
    unused = sorted(k for k in i18n.EN if k.removesuffix("#1") not in used)
    assert not unused, unused


def test_values_sane():
    for k, v in i18n.EN.items():
        assert isinstance(v, str) and v.strip(), k
        assert not THAI.search(v), (k, v)
        assert set(PH.findall(k)) == set(PH.findall(v)), (k, v)
        if "{n}" in k and not k.endswith("#1"):
            assert k + "#1" in i18n.EN, f"no singular for {k!r}"


if __name__ == "__main__":
    import sys
    import traceback
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
