"""Self-check for exporters.py (Markdown zip, Word). Run: python test_exporters.py"""
import sys
import zipfile
from io import BytesIO

from PIL import Image

from exporters import build_markdown, md_escape, meta_line, thai_date


def _png(color=(0, 200, 0)) -> bytes:
    b = BytesIO()
    Image.new("RGB", (4, 4), color).save(b, "PNG")
    return b.getvalue()


PNG = _png()
G = {"title": "คู่มือ: ทดสอบ", "created": "2026-10-16T10:00:00", "updated": "2026-10-16T10:00:00",
     "settings": {"toc": True, "step_count": True, "created": True, "updated": False},
     "steps": [{"id": "a", "kind": "click", "text": "คลิก *บันทึก*"},
               {"id": "n", "kind": "note", "text": "ระวัง"},
               {"id": "b", "kind": "image", "text": "ภาพ"}]}


def _zip(b: bytes) -> dict:
    with zipfile.ZipFile(BytesIO(b)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_thai_date():
    assert thai_date("2026-10-16T10:00:00") == "16 ต.ค. 2569"
    assert thai_date("x") == ""


def test_meta_line():
    assert meta_line(G) == "2 ขั้นตอน · สร้างเมื่อ 16 ต.ค. 2569"


def test_md_layout():
    z = _zip(build_markdown(G, {"a": ("png", PNG)}))
    assert set(z) == {"คู่มือ_ ทดสอบ.md", "images/step-01.png"}, set(z)
    md = z["คู่มือ_ ทดสอบ.md"].decode("utf-8")
    assert md.startswith("# คู่มือ: ทดสอบ\n"), md
    assert "1. [คลิก \\*บันทึก\\*](#step-1)" in md and '<a id="step-1"></a>' in md, md
    assert "## 1. คลิก \\*บันทึก\\*\n" in md and "![](images/step-01.png)" in md, md
    assert "> ระวัง" in md and "## 2. ภาพ" in md, md
    assert "step-02" not in md.split("## 2. ภาพ")[1], md
    assert z["images/step-01.png"] == PNG


def test_md_escapes_text():
    assert md_escape("1. # a*b_c [x](y) <i> | `q` !") == \
        "1. \\# a\\*b\\_c \\[x\\](y) \\<i\\> \\| \\`q\\` \\!"


def test_md_no_images():
    z = _zip(build_markdown({**G, "steps": [G["steps"][1]]}, {}))
    assert list(z) == ["คู่มือ_ ทดสอบ.md"], list(z)


def test_md_keeps_gif():
    assert _zip(build_markdown(G, {"b": ("gif", b"GIF89a..")}))["images/step-02.gif"] == b"GIF89a.."


def test_md_safe_inner_name():
    assert list(_zip(build_markdown({**G, "title": ' a/b\\c?*"<>| '}, {}))) == ["a_b_c______.md"]


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
