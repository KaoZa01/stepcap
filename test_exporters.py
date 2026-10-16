"""Self-check for exporters.py (Markdown zip, Word). Run: python test_exporters.py"""
import sys
import zipfile
from io import BytesIO

from PIL import Image

from exporters import build_markdown, doc_date, md_escape, meta_line


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


def test_doc_date():
    assert doc_date("2026-10-16T10:00:00") == "16 ต.ค. 2569"
    assert doc_date("x") == ""


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
        "1\\. \\# a\\*b\\_c \\[x\\](y) \\<i\\> \\| \\`q\\` \\!"
    assert md_escape("a & b ~~c~~ =") == "a \\& b \\~\\~c\\~\\~ \\="
    # line starts that would turn a note into a list, rule or code block
    assert md_escape("- a\n+ b\n2) c\n    d\n---") == "\\- a  \n\\+ b  \n2\\) c  \nd  \n\\---"


def test_docx_metadata_is_guide_only():
    from exporters import build_docx
    cp = _doc(build_docx(G, {})).core_properties
    assert cp.title == G["title"] and cp.author == "" and cp.comments == ""
    assert cp.last_modified_by == "" and cp.created.year == 2026


def test_md_no_images():
    z = _zip(build_markdown({**G, "steps": [G["steps"][1]]}, {}))
    assert list(z) == ["คู่มือ_ ทดสอบ.md"], list(z)


def test_md_keeps_gif():
    assert _zip(build_markdown(G, {"b": ("gif", b"GIF89a..")}))["images/step-02.gif"] == b"GIF89a.."


def test_md_safe_inner_name():
    assert list(_zip(build_markdown({**G, "title": ' a/b\\c?*"<>| '}, {}))) == ["a_b_c______.md"]


PAGE_DOC = {"title": "เริ่มงาน", "created": "2026-10-16T10:00:00", "updated": "",
            "settings": {"toc": True, "created": True}, "meta_count": "2 คู่มือ",
            "steps": [{"id": "sec0", "kind": "section", "text": "ก", "gid": "g1"},
                      {"id": "g1.s1", "kind": "click", "text": "a", "gid": "g1"},
                      {"id": "sec1", "kind": "section", "text": "ข้อความ", "body": "อธิบาย *x*"},
                      {"id": "sec2", "kind": "section", "text": "ข", "gid": "g2"},
                      {"id": "g2.s1", "kind": "click", "text": "b", "gid": "g2"},
                      {"id": "sec3", "kind": "section", "text": "คู่มือนี้ถูกลบแล้ว", "missing": True}]}


def test_numbered_restarts_after_section():
    from exporters import numbered
    assert [n for n, _ in numbered(PAGE_DOC)] == [None, 1, None, None, 1, None]


def test_meta_count_override():
    assert meta_line(PAGE_DOC) == "2 คู่มือ · สร้างเมื่อ 16 ต.ค. 2569"


def test_md_sections_images_unique():
    z = _zip(build_markdown(PAGE_DOC, {"g1.s1": ("png", PNG), "g2.s1": ("png", _png((9, 9, 9)))}))
    assert {"images/00-01.png", "images/02-01.png"} <= set(z), set(z)
    md = z["เริ่มงาน.md"].decode("utf-8")
    assert "## ก" in md and "### 1. a" in md and "### 1. b" in md, md
    assert "อธิบาย \\*x\\*" in md and "[ก](#a0)" in md and '<a id="a0"></a>' in md, md
    assert "ลบแล้ว" not in md, md
    assert md.startswith("# เริ่มงาน\n\n2 คู่มือ · สร้างเมื่อ"), md


def test_page_description_exported():
    from exporters import build_docx
    doc = {**PAGE_DOC, "description": "สำหรับพนักงานใหม่"}
    assert "สำหรับพนักงานใหม่" in _zip(build_markdown(doc, {}))["เริ่มงาน.md"].decode("utf-8")
    assert "สำหรับพนักงานใหม่" in [p.text for p in _doc(build_docx(doc, {})).paragraphs]


def test_untitled_text_block_no_empty_heading():
    from exporters import build_docx
    doc = {**PAGE_DOC, "steps": PAGE_DOC["steps"][:3] +
           [{"id": "sec9", "kind": "section", "text": "", "body": "แค่ข้อความ"}]}
    md = _zip(build_markdown(doc, {}))["เริ่มงาน.md"].decode("utf-8")
    assert "## \n" not in md and "[](#" not in md and "แค่ข้อความ" in md, md
    d = _doc(build_docx(doc, {}))
    assert [p.text for p in d.paragraphs if p.style.name in ("Heading 1", "List Number")] == \
        ["ก", "ข้อความ", "ก", "ข้อความ"]
    assert "แค่ข้อความ" in [p.text for p in d.paragraphs]


def test_only_deleted_sections_dropped():
    # a plain step that happens to carry "missing" is still a step
    from exporters import build_docx
    doc = {**G, "steps": [{"id": "a", "kind": "click", "text": "ยังอยู่", "missing": True}]}
    assert "ยังอยู่" in _zip(build_markdown(doc, {}))["คู่มือ_ ทดสอบ.md"].decode("utf-8")
    assert "1. ยังอยู่" in [p.text for p in _doc(build_docx(doc, {})).paragraphs]


def test_docx_sections():
    from exporters import build_docx
    d = _doc(build_docx(PAGE_DOC, {}))
    heads = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert heads == ["ก", "ข้อความ", "ข"], heads
    texts = [p.text for p in d.paragraphs]
    assert "อธิบาย *x*" in texts and "1. b" in texts and "คู่มือนี้ถูกลบแล้ว" not in texts


def test_docx_no_template_leftovers():
    from exporters import build_docx
    b = build_docx(G, {})
    z = _zip(b)
    assert not any("thumbnail" in k for k in z), list(z)
    assert b"<Application>StepCap</Application>" in z["docProps/app.xml"]
    assert b"Macintosh" not in z["docProps/app.xml"] and b"thumbnail" not in z["_rels/.rels"]
    assert b'w:val="th-TH"' in z["word/styles.xml"] and b'w:bidi="th-TH"' in z["word/styles.xml"]
    d = _doc(b)
    steps = [p.text for p in d.paragraphs if p.style.name == "Heading 2"]
    assert steps == ["1. คลิก *บันทึก*", "2. ภาพ"], steps  # in Word's Navigation Pane
    assert str(d.styles["Heading 1"].font.color.rgb) == "111827"


def test_english_export_labels():
    import i18n
    from exporters import build_docx, doc_date
    g = {**G, "settings": {**G["settings"], "updated": True}}
    with i18n.using("en"):
        assert doc_date("2026-10-16T10:00:00") == "16 Oct 2026"
        assert meta_line(g) == "2 steps · Created 16 Oct 2026 · Last edited 16 Oct 2026"
        md = _zip(build_markdown(g, {}))
        assert "**Contents**" in next(v for k, v in md.items() if k.endswith(".md")).decode("utf-8")
        b = build_docx(g, {})
    assert "Contents" in [p.text for p in _doc(b).paragraphs]
    styles = _zip(b)["word/styles.xml"]
    assert b'w:val="en-US"' in styles and b'w:bidi="th-TH"' in styles


def _doc(b: bytes):
    import docx
    return docx.Document(BytesIO(b))


def _media(b: bytes) -> list[bytes]:
    return [v for k, v in _zip(b).items() if k.startswith("word/media/")]


def test_docx_text_and_images():
    from exporters import build_docx
    b = build_docx(G, {"a": ("png", PNG)})
    d = _doc(b)
    texts = [p.text for p in d.paragraphs]
    for t in ("คู่มือ: ทดสอบ", "2 ขั้นตอน · สร้างเมื่อ 16 ต.ค. 2569", "1. คลิก *บันทึก*", "ระวัง", "2. ภาพ"):
        assert t in texts, (t, texts)
    assert texts.count("คลิก *บันทึก*") == 1, texts  # the TOC entry
    assert len(d.inline_shapes) == 1
    assert _media(b) == [PNG]


def test_docx_thai_font():
    from docx.oxml.ns import qn
    from exporters import build_docx
    rf = _doc(build_docx(G, {})).styles["Normal"].element.find(qn("w:rPr")).find(qn("w:rFonts"))
    assert rf.get(qn("w:cs")) == "Leelawadee UI" and rf.get(qn("w:ascii")) == "Leelawadee UI"


def test_docx_thai_bold_italic():
    # Word styles Thai as complex script: bold/italic need bCs/iCs, not just b/i
    from docx.oxml.ns import qn
    from exporters import build_docx
    runs = {r.text: r._r.find(qn("w:rPr")) for p in _doc(build_docx(G, {})).paragraphs for r in p.runs}
    for t in ("1. คลิก *บันทึก*", "สารบัญ"):
        assert runs[t].find(qn("w:bCs")) is not None, t
    assert runs["ระวัง"].find(qn("w:iCs")) is not None


def test_docx_gif_first_frame():
    from exporters import build_docx
    frames = [Image.new("RGB", (8, 8), c) for c in ((255, 0, 0), (0, 0, 255))]
    g = BytesIO()
    frames[0].save(g, "GIF", save_all=True, append_images=frames[1:])
    b = build_docx(G, {"b": ("gif", g.getvalue())})
    assert len(_doc(b).inline_shapes) == 1
    m = _media(b)
    assert len(m) == 1 and m[0].startswith(b"\x89PNG")
    assert Image.open(BytesIO(m[0])).getpixel((0, 0))[:3] == (255, 0, 0)


def test_docx_notes_only():
    from exporters import build_docx
    d = _doc(build_docx({**G, "steps": [G["steps"][1]]}, {}))
    assert len(d.inline_shapes) == 0 and "ระวัง" in [p.text for p in d.paragraphs]


def _app():
    """app.py in this process on its own temp storage (never the real one)."""
    import os
    import tempfile
    from pathlib import Path
    if "app" not in sys.modules:
        import atexit
        import shutil
        os.environ["STEPCAP_STORAGE"] = tempfile.mkdtemp(prefix="stepcap-exp-")
        atexit.register(shutil.rmtree, os.environ["STEPCAP_STORAGE"], True)
    import app
    assert str(app.STORAGE) == os.environ["STEPCAP_STORAGE"]
    return app


def test_export_images_binary_and_missing():
    import json
    app = _app()
    st = app.STORAGE
    (st / "g2").mkdir()
    (st / "g2" / "bad.gif").write_bytes(b"GIF89a junk")
    guide = {"id": "g2", "steps": [
        {"id": "s1", "kind": "click", "text": "a", "image": "a.png"},
        {"id": "n", "kind": "note", "text": "x"},
        {"id": "s2", "kind": "image", "text": "b", "image": "gone.gif"},
        {"id": "s3", "kind": "image", "text": "c", "image": "bad.gif"}]}
    head = json.dumps({"images": [{"id": "s1", "ext": "png", "size": len(PNG)},
                                  {"id": "s2", "ext": "gif"}, {"id": "s3", "ext": "gif"}]})
    images, missing = app._export_images("g2", guide, head.encode() + b"\n" + PNG)
    assert images == {"s1": ("png", PNG)} and missing == [2, 3], (images, missing)
    images, missing = app._export_images("g2", guide, head.encode() + b"\n" + PNG[:10])
    assert images == {} and missing == [1, 2, 3], (images, missing)  # cut-off body


def test_safe_title_windows_names():
    from exporters import safe_title
    assert safe_title("con") == "_con" and safe_title("NUL.txt") == "_NUL.txt"
    assert safe_title("a\x07b. . ") == "a_b" and safe_title("...") == "guide"


def test_export_write_error_reported():
    # Save As picked a place that can't be written: say so, don't pretend it saved
    import json
    app = _app()
    st = app.STORAGE
    (st / "g1").mkdir()
    (st / "g1" / "guide.json").write_text(json.dumps(
        {"id": "g1", "title": "t", "created": "2026-10-16T10:00:00", "steps": []}), encoding="utf-8")
    bad = str(st / "no" / "such" / "x.html")
    app.WINDOW = type("W", (), {"create_file_dialog": lambda self, *a, **k: (bad,)})()
    for fmt, body in (("html", b"<html></html>"), ("md", b'{"images": []}\n')):
        assert app.export_guide("g1", fmt, body) == app.save_failed()
    assert app.download_image("g1", "1", "png", PNG) == app.save_failed()
    assert app.save_failed()["error"].startswith("บันทึกไฟล์ไม่ได้")


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
