"""Guide export formats built from the guide on disk plus the finished step
pictures the page renders (so redaction is baked in one place, the page).

Markdown: a zip of `<title>.md` + `images/step-NN.<ext>`. Word: a .docx.
Pure Python (no Windows calls); test_exporters.py covers it.
"""
from __future__ import annotations

import re
import zipfile
from datetime import datetime
from io import BytesIO

_TH_MONTHS = ("ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
              "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.")


def thai_date(iso: str) -> str:
    """'2026-10-16T10:00:00' -> '16 ต.ค. 2569', like the page's th-TH date."""
    try:
        d = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"{d.day} {_TH_MONTHS[d.month - 1]} {d.year + 543}"


def numbered(guide: dict) -> list[tuple[int | None, dict]]:
    """(step number, step); notes and sections get None and don't count, and
    a section (a page's guide or text block) starts the numbering again."""
    out, n = [], 0
    for s in guide.get("steps") or []:
        if s.get("kind") == "section":
            n = 0
            out.append((None, s))
        elif s.get("kind") == "note":
            out.append((None, s))
        else:
            n += 1
            out.append((n, s))
    return out


def meta_line(guide: dict) -> str:
    S = guide.get("settings") or {}
    parts = [guide["meta_count"]] if guide.get("meta_count") else []  # a page counts guides
    if S.get("step_count"):
        parts.append(f"{sum(1 for n, _ in numbered(guide) if n)} ขั้นตอน")
    if S.get("created") and thai_date(guide.get("created", "")):
        parts.append("สร้างเมื่อ " + thai_date(guide["created"]))
    if S.get("updated") and thai_date(guide.get("updated", "")):
        parts.append("แก้ไขล่าสุด " + thai_date(guide["updated"]))
    return " · ".join(parts)


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10))}


def safe_title(title: str) -> str:
    """A Windows file name: no reserved chars, no trailing dots, no CON/NUL..."""
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title or "").strip().rstrip(". ")
    if t.split(".")[0].upper() in _RESERVED:
        t = "_" + t
    return t or "guide"


def md_escape(text: str) -> str:
    """Plain text in Markdown: inline syntax escaped, and line starts that
    would make a list, rule or code block neutralised."""
    out = []
    for line in (text or "").split("\n"):
        line = re.sub(r"([\\`*_\[\]<>#|!&~=])", r"\\\1", line.lstrip())
        line = re.sub(r"^([-+])", r"\\\1", line)
        out.append(re.sub(r"^(\d+)([.)])", r"\1\\\2", line))
    return "  \n".join(out)


def _one_line(text: str) -> str:
    return md_escape(" ".join((text or "").split()))


def _kept(guide: dict) -> list:
    """numbered(), without a page's deleted guides."""
    return [(n, s) for n, s in numbered(guide)
            if not (s.get("kind") == "section" and s.get("missing"))]


def build_markdown(guide: dict, images: dict[str, tuple[str, bytes]]) -> bytes:
    """images: step id -> (ext, bytes); a step without one has no picture."""
    steps = _kept(guide)
    secs = [s for _, s in steps if s.get("kind") == "section"]
    lines = [f"# {_one_line(guide.get('title', ''))}", ""]
    meta = meta_line(guide)
    if meta:
        lines += [meta, ""]
    if guide.get("description"):  # a page's
        lines += [md_escape(guide["description"]), ""]
    toc = (guide.get("settings") or {}).get("toc")
    if toc and secs:  # a page: its guides and text blocks
        lines += ["**สารบัญ**", ""]
        lines += [f"1. [{_one_line(s.get('text'))}](#a{i})" for i, s in enumerate(secs) if s.get("text")]
        lines.append("")
    elif toc and any(n for n, _ in steps):
        lines += ["**สารบัญ**", ""]
        lines += [f"{n}. [{_one_line(s.get('text'))}](#step-{n})" for n, s in steps if n]
        lines.append("")
    files, sec = {}, -1
    step_h = "###" if secs else "##"
    for n, s in steps:
        if s.get("kind") == "section":
            sec += 1
            if s.get("text"):  # a text block may have no title
                lines += [f'<a id="a{sec}"></a>', f"## {_one_line(s.get('text'))}", ""]
            if s.get("body"):
                lines += [md_escape(s["body"]), ""]
            continue
        if n is None:
            lines += [f"> {md_escape(line)}" for line in (s.get("text") or "").split("\n")]
            lines.append("")
            continue
        if not secs:
            lines.append(f'<a id="step-{n}"></a>')
        lines += [f"{step_h} {n}. {_one_line(s.get('text'))}", ""]
        if s.get("id") in images:
            ext, data = images[s["id"]]
            name = f"images/{sec:02d}-{n:02d}.{ext}" if secs else f"images/step-{n:02d}.{ext}"
            files[name] = data
            lines += [f"![]({name})", ""]
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(safe_title(guide.get("title", "")) + ".md", "\n".join(lines))
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Word (.docx)
# ---------------------------------------------------------------------------
THAI_FONT = "Leelawadee UI"


def _thai_font(style) -> None:
    """Pin a style's fonts (incl. complex script, which Thai uses) to THAI_FONT;
    theme-font attributes would win over them, so they go."""
    from docx.oxml.ns import qn
    rpr = style.element.get_or_add_rPr()
    f = rpr.find(qn("w:rFonts"))
    if f is None:
        f = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, f)
    for a in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
        f.attrib.pop(qn("w:" + a), None)
    for a in ("ascii", "hAnsi", "cs", "eastAsia"):
        f.set(qn("w:" + a), THAI_FONT)


def _png_bytes(ext: str, data: bytes) -> bytes:
    """Word shows PNG; a GIF becomes its first frame."""
    if ext == "png":
        return data
    from PIL import Image
    with Image.open(BytesIO(data)) as im:
        out = BytesIO()
        im.convert("RGB").save(out, "PNG")
        return out.getvalue()


def _run(p, text: str, bold=False, italic=False):
    """A run whose bold/italic also reach Thai, which Word styles as complex
    script (bCs/iCs); plain b/i would leave the Thai part regular."""
    r = p.add_run(text)
    rpr = r._r.get_or_add_rPr()
    if bold:
        r.bold = True
        rpr.get_or_add_bCs()
    if italic:
        r.italic = True
        rpr.get_or_add_iCs()
    return r


_APP_XML = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            b'<Application>StepCap</Application></Properties>')
INK = (0x11, 0x18, 0x27)  # DESIGN.md --ink


def _template_leftovers(doc) -> None:
    """The python-docx template ships a blank page thumbnail and app.xml naming
    "Microsoft Macintosh Word"; the file should say StepCap and show no fake
    preview."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    pkg = doc.part.package
    for rid, rel in list(pkg.rels.items()):
        if rel.reltype == RT.THUMBNAIL:
            del pkg.rels[rid]
        elif rel.reltype == RT.EXTENDED_PROPERTIES:
            rel.target_part._blob = _APP_XML


def _thai_lang(doc) -> None:
    """Document language Thai, so Word spell-checks Thai text as Thai."""
    from docx.oxml.ns import qn
    rpr = doc.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = rpr.makeelement(qn("w:lang"), {})
        rpr.append(lang)
    for a in ("val", "bidi", "eastAsia"):
        lang.set(qn("w:" + a), "th-TH")


def build_docx(guide: dict, images: dict[str, tuple[str, bytes]]) -> bytes:
    import docx
    from docx.oxml.ns import qn
    from docx.shared import Emu, Inches, Mm, RGBColor
    from PIL import Image
    doc = docx.Document()
    _template_leftovers(doc)
    _thai_lang(doc)
    cp = doc.core_properties  # the template says "python-docx", 2013: guide's own instead
    cp.title, cp.author, cp.comments, cp.last_modified_by = guide.get("title", ""), "", "", ""
    for k in ("created", "modified"):
        try:
            setattr(cp, k, datetime.fromisoformat(guide.get(k if k == "created" else "updated", "")))
        except (TypeError, ValueError):
            pass
    for name in ("Normal", "Title", "List Number", "Heading 1", "Heading 2"):
        _thai_font(doc.styles[name])
    for name in ("Title", "Heading 1", "Heading 2"):  # the template's blue -> the app's ink
        doc.styles[name].font.color.rgb = RGBColor(*INK)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)  # A4
    text_w = sec.page_width - sec.left_margin - sec.right_margin
    steps = _kept(guide)
    secs = [s for _, s in steps if s.get("kind") == "section"]

    doc.add_paragraph(guide.get("title", ""), style="Title")
    meta = meta_line(guide)
    if meta:
        doc.add_paragraph(meta)
    if guide.get("description"):  # a page's
        doc.add_paragraph(guide["description"])
    if (guide.get("settings") or {}).get("toc") and (secs or any(n for n, _ in steps)):
        _run(doc.add_paragraph(), "สารบัญ", bold=True)
        for n, s in steps:
            if (s.get("kind") == "section" and s.get("text")) if secs else n:
                doc.add_paragraph(s.get("text") or "", style="List Number")
    for n, s in steps:
        if s.get("kind") == "section":
            if s.get("text"):
                doc.add_paragraph(s["text"], style="Heading 1")
            if s.get("body"):
                doc.add_paragraph(s["body"])
            continue
        if n is None:
            p = doc.add_paragraph()
            _run(p, s.get("text") or "", italic=True)
            shd = p._p.get_or_add_pPr().makeelement(
                qn("w:shd"), {qn("w:val"): "clear", qn("w:fill"): "F3F4F6"})
            p._p.get_or_add_pPr().append(shd)
            continue
        # a heading, so steps show in Word's Navigation Pane
        _run(doc.add_paragraph(style="Heading 2"), f"{n}. {s.get('text') or ''}", bold=True)
        if s.get("id") in images:
            png = _png_bytes(*images[s["id"]])
            with Image.open(BytesIO(png)) as im:
                w = Inches(im.width / 96)
            doc.add_picture(BytesIO(png), width=Emu(min(w, text_w)))
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
