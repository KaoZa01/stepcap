# ส่วนที่ 4 ส่งออก PDF / Markdown / Word — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export a guide as PDF, Markdown (.zip) or Word (.docx) besides the existing HTML, from one format menu, with every image already redacted.

**Architecture:** The page keeps producing the finished pixels (`renderStepPng`), so redaction is baked in one place. Markdown and Word are assembled in a new pure module `exporters.py` from the guide on disk plus the PNGs the page sends. PDF prints the existing export HTML through WebView2 (`CoreWebView2.PrintToPdfAsync`) in a hidden pywebview window. All four go through one route and the existing Save As, which now reports write failures.

**Tech Stack:** Python 3.14, `python-docx==1.2.0` (+ `lxml`), `zipfile`, Pillow, pywebview 6.2.1 / WebView2 via pythonnet, page JS.

**Spec:** `docs/specs/2026-10-16-export-formats-design.md`

## Global Constraints

- No original pixels of hidden areas in any output (zip images, docx media, PDF). Images come only from `renderStepPng` (GIF: the original file for Markdown, its first frame for PDF/Word).
- No browser and no visible window while making a PDF; local only.
- All UI copy Thai; Save As file-type filters ASCII (`"PDF (*.pdf)"`, `"ZIP (*.zip)"`, `"Word (*.docx)"`).
- Output holds only guide content: no local paths, no Windows user name.
- Content of every format follows the guide's document settings (`toc`, `step_count`, `created`, `updated`); notes are unnumbered; step numbers skip notes.
- Failure is never silent: cancel → nothing; write/print error → `{"saved": null, "error": "<Thai>"}` and a toast.
- Tests: temp `STEPCAP_STORAGE`, generated images, no real desktop input (driving the app's own Save As dialog the way `test_export_save_as` does is fine). Run each as `.venv/Scripts/python.exe test_X.py`.

## Review Focus

- Step text full of Markdown syntax (`# * _ [ ] < > | \`` and a leading `1.`) → shows as plain text in the .md. Pinned in Task 1 (`test_md_escapes_text`).
- Guide with no images at all, or only notes → every format still produces a valid file. Pinned in Task 1 (`test_md_no_images`) and Task 2 (`test_docx_notes_only`).
- GIF step → Markdown keeps the GIF bytes, Word gets a PNG first frame without crashing. Pinned in Task 1 (`test_md_keeps_gif`) and Task 2 (`test_docx_gif_first_frame`).
- Title with `\ / : * ? " < > |` → safe name for the .md inside the zip. Pinned in Task 1 (`test_md_safe_inner_name`).
- Unreadable step image → exported without its picture and the toast names the step. Pinned in Task 4 (`test_export_images_skip_broken`, uses the existing `broken` render seed).

---

### Task 1: Markdown zip in `exporters.py`

**Files:**
- Create: `exporters.py`, `test_exporters.py` (`__main__` runner like `test_steps.py`)

**Interfaces:**
- Produces:
  - `thai_date(iso: str) -> str` — `"2026-10-16T10:00:00"` → `"16 ต.ค. 2569"` (Buddhist year, short month, same as the page's `toLocaleDateString("th-TH", {year: "numeric", month: "short", day: "numeric"})`); `""` for bad input.
  - `meta_line(guide: dict) -> str` — parts joined by `" · "`: `"<n> ขั้นตอน"`, `"สร้างเมื่อ <date>"`, `"แก้ไขล่าสุด <date>"` per settings; `""` when none.
  - `numbered(guide) -> list[tuple[int | None, dict]]` — `(n, step)`, `n` is `None` for notes.
  - `md_escape(text: str) -> str` — backslash before each of ``\ ` * _ [ ] < > # | !``; newlines become `"  \n"`.
  - `safe_title(title: str) -> str` — `[\\/:*?"<>|]` → `_`, stripped, `"guide"` if empty (same rule as `app._file_title`, which then calls this).
  - `build_markdown(guide: dict, images: dict[str, tuple[str, bytes]]) -> bytes` — zip bytes. `images` maps step id → (`"png"` | `"gif"`, bytes); a step without an entry has no picture. Entries: `<safe_title>.md`, `images/step-NN.<ext>` (NN = step number, 2 digits min).
  - md layout: `# title`, blank, meta line (if any), blank, `**สารบัญ**` + `1. [text](#step-1)` list (if `toc`), then per step `<a id="step-N"></a>` + `## N. text` + `![](images/step-NN.png)`; notes `> text`.

- [ ] **Step 1: Failing tests**

```python
G = {"title": "คู่มือ: ทดสอบ", "created": "2026-10-16T10:00:00", "updated": "2026-10-16T10:00:00",
     "settings": {"toc": True, "step_count": True, "created": True, "updated": False},
     "steps": [{"id": "a", "kind": "click", "text": "คลิก *บันทึก*"},
               {"id": "n", "kind": "note", "text": "ระวัง"},
               {"id": "b", "kind": "image", "text": "ภาพ"}]}
def test_thai_date():
    assert thai_date("2026-10-16T10:00:00") == "16 ต.ค. 2569" and thai_date("x") == ""
def test_meta_line():
    assert meta_line(G) == "2 ขั้นตอน · สร้างเมื่อ 16 ต.ค. 2569"
def test_md_layout():
    z = _zip(build_markdown(G, {"a": ("png", PNG)}))
    assert set(z) == {"คู่มือ_ ทดสอบ.md", "images/step-01.png"}
    md = z["คู่มือ_ ทดสอบ.md"].decode("utf-8")
    assert md.startswith("# คู่มือ: ทดสอบ\n")
    assert "1. [คลิก \\*บันทึก\\*](#step-1)" in md and '<a id="step-1"></a>' in md
    assert "## 1. คลิก \\*บันทึก\\*\n" in md and "![](images/step-01.png)" in md
    assert "> ระวัง" in md and "## 2. ภาพ" in md and "step-02" not in md.split("## 2. ภาพ")[1]
    assert z["images/step-01.png"] == PNG
def test_md_escapes_text():
    assert md_escape("1. # a*b_c [x](y) <i> | `q` !") == "1. \\# a\\*b\\_c \\[x\\](y) \\<i\\> \\| \\`q\\` \\!"
def test_md_no_images():
    z = _zip(build_markdown({**G, "steps": [G["steps"][1]]}, {}))
    assert list(z) == ["คู่มือ_ ทดสอบ.md"]
def test_md_keeps_gif():
    assert _zip(build_markdown(G, {"b": ("gif", b"GIF89a..")}))["images/step-02.gif"] == b"GIF89a.."
def test_md_safe_inner_name():
    assert list(_zip(build_markdown({**G, "title": ' a/b\\c?*"<>| '}, {}))) == ["a_b_c______.md"]
```
(`PNG` = a 4×4 Pillow PNG; `_zip(b)` = `{name: bytes}` from `zipfile.ZipFile(BytesIO(b))`.)

- [ ] **Step 2:** Run `test_exporters.py` — FAIL (`ModuleNotFoundError: exporters`).
- [ ] **Step 3:** Implement with stdlib only (`zipfile`, `re`, `datetime`). Thai month abbreviations: `ม.ค. ก.พ. มี.ค. เม.ย. พ.ค. มิ.ย. ก.ค. ส.ค. ก.ย. ต.ค. พ.ย. ธ.ค.`
- [ ] **Step 4:** Run — all pass.
- [ ] **Step 5:** Commit `feat: Markdown export (zip)`.

### Task 2: Word export

**Files:**
- Modify: `exporters.py`, `requirements.txt` (`python-docx==1.2.0`)
- Test: `test_exporters.py`

**Interfaces:**
- Consumes: `meta_line`, `numbered`, the `images` shape from Task 1.
- Produces: `build_docx(guide: dict, images: dict[str, tuple[str, bytes]]) -> bytes`.
  - Title as `Title` style, meta line as normal paragraph, TOC as `List Number` paragraphs (plain text), step: bold paragraph `"N. text"` then picture (width = min(image px at 96 dpi, page text width)), note: italic paragraph with light shading (`F3F4F6`).
  - Every run gets the Thai font: `w:rFonts` with `w:ascii`, `w:hAnsi`, `w:cs` = `"Leelawadee UI"` (set on the `Normal` style is enough if runs inherit).
  - GIF → first frame converted to PNG with Pillow before inserting.

- [ ] **Step 1:** Install `python-docx==1.2.0` into `.venv`; add to `requirements.txt`. Check: `.venv/Scripts/python.exe -c "import docx; print(docx.__version__)"` prints `1.2.0`.
- [ ] **Step 2: Failing tests** (read the result back with `docx.Document(BytesIO(b))`):
  - `test_docx_text_and_images`: paragraphs include `"คู่มือ: ทดสอบ"`, `"2 ขั้นตอน · สร้างเมื่อ 16 ต.ค. 2569"`, `"1. คลิก *บันทึก*"`, `"ระวัง"`, `"2. ภาพ"`; `len(doc.inline_shapes) == 1`; the single media part's blob equals `PNG`.
  - `test_docx_thai_font`: `doc.styles["Normal"].element` has `w:rFonts` with `w:cs="Leelawadee UI"`.
  - `test_docx_gif_first_frame`: a 2-frame GIF for step `b` → one inline shape, its blob starts with `b"\x89PNG"`.
  - `test_docx_notes_only`: guide with just the note → valid document, 0 inline shapes.
- [ ] **Step 3:** Run — FAIL (`build_docx` undefined).
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Run `test_exporters.py` — all pass.
- [ ] **Step 6:** Commit `feat: Word export`.

### Task 3: PDF via WebView2

**Files:**
- Modify: `app.py` (new `print_pdf`), `ui/guide.js` (`buildExportHtml` print variant), `ui/index.html` only if print CSS lives there
- Test: `test_app.py`

**Interfaces:**
- Produces:
  - `print_pdf(html: str) -> bytes` in `app.py` — writes `html` to `STORAGE/_tmp/print-<uuid>.html`, opens `webview.create_window(..., url=<file URL>, hidden=True)`, waits for `events.loaded` and then for `document.images` all `complete` (poll `evaluate_js`, ≤ 30 s), calls `CoreWebView2.PrintToPdfAsync(<tmp pdf>, settings)` on the window's UI thread (`form.Invoke`, as in the spike: `win.native.browser.webview.CoreWebView2`), settings: A4 portrait (`PageWidth=8.27`, `PageHeight=11.69` inches), `ShouldPrintBackgrounds=True`; returns the PDF bytes; always destroys the window and deletes both temp files; raises `RuntimeError` on failure or timeout.
  - `buildExportHtml(gid, {print: true})` — same document, but each baked image is an `<img>` (no canvas, so print waits on real image loads) and adds print CSS: `@page { size: A4; margin: 14mm }`, `.rg-step { break-inside: avoid }`, `img { max-width: 100% }`. GIFs stay `<img>` (print takes the first frame).
- [ ] **Step 1: Failing test** `test_app.py::test_export_pdf`: POST `/api/guide/{OLD_ID}/export?format=pdf` with a small Thai HTML containing one `<img>` (data URL PNG) through `export_async`, drive the Save As dialog to `CTX["storage"] / "x.pdf"` like `test_export_save_as`; assert response `saved` is that path, the file starts with `b"%PDF"`, and contains `b"/Type /Page"`. Also assert no `print-*.html`/`*.pdf` left in `CTX["storage"] / "_tmp"`.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement `print_pdf` and the `format=pdf` branch of the export route (route detail in Task 4; here only `pdf` and the existing `html` default).
- [ ] **Step 4:** Run `test_app.py` — all pass.
- [ ] **Step 5:** Commit `feat: PDF export via WebView2`.

### Task 4: One export route, format menu, failure messages

**Files:**
- Modify: `app.py` (`save_as`, `export_guide`, `download_image`, export route), `ui/guide.js` (`exportGuide`, new `exportImages`), `ui/shell.js:192` (card menu), `ui/guide.js:164, 285` (export buttons)
- Test: `test_app.py`, `test_render.py`

**Interfaces:**
- Consumes: `build_markdown`, `build_docx`, `safe_title` (Task 1–2), `print_pdf` (Task 3).
- Produces:
  - `POST /api/guide/<id>/export?format=html|pdf|md|docx` → `{"saved": str | None, "error": str | None}`. `html`/`pdf` body: the HTML text. `md`/`docx` body: JSON `{"images": {"<step id>": {"ext": "png"|"gif", "data": "<base64>"}}}`; text comes from the guide on disk. Unknown format → 400. GIF bytes for `md` are read by the server from the guide folder, not trusted from the page.
  - `save_as` raises `OSError` on write failure; route turns it into `error: "บันทึกไฟล์ไม่ได้"`; `print_pdf` failure → `"สร้าง PDF ไม่สำเร็จ"`. Download route gets the same treatment.
  - JS `exportImages(g) -> Promise<{images, failed: number[]}>` — `renderStepPng` for every non-GIF image step (failures → step number in `failed`); GIF steps send `{ext: "gif"}` with no data.
  - JS `exportGuide(gid, format)`; buttons open `popMenu` with `HTML / PDF / Markdown (.zip) / Word (.docx)`. While running: toast `"กำลังส่งออก…"`, a module flag blocks a second export. After: `"บันทึกไฟล์แล้ว"`, or `"ส่งออกไม่สำเร็จ: <error>"`; if `failed` non-empty also `"ภาพของขั้นที่ 3, 7 อ่านไม่ได้ ส่งออกโดยไม่มีภาพ"`.
- [ ] **Step 1: Failing tests**
  - `test_app.py::test_export_md_and_docx`: for `md` and `docx`, POST a JSON body with one 4×4 PNG for the old guide's first image step, drive Save As to `x.zip` / `x.docx`; zip has the `.md` and `images/step-01.png` with those bytes; docx opens with `docx.Document` and has 1 inline shape. `format=nope` → 400.
  - `test_app.py::test_export_write_error_reported`: Save As target inside a path that doesn't exist (`CTX["storage"] / "no" / "such" / "x.html"`) → `{"saved": None, "error": "บันทึกไฟล์ไม่ได้"}`.
  - `test_render.py::test_export_menu_formats`: click `#exp` in edit mode → `.menu-pop` items text == `["HTML", "PDF", "Markdown (.zip)", "Word (.docx)"]`.
  - `test_render.py::test_export_images_no_original`: `exportImages` on guide `noise` → step `a1` PNG has the black-out area black (`_black`) and does not contain the original noise base64 slice (as `test_export_contains_no_original`).
  - `test_render.py::test_export_images_skip_broken`: `exportImages` on guide `broken` → `failed == [1, 2]`, `images == {}`.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run all six test files — all pass.
- [ ] **Step 5:** Commit `feat: export menu with PDF, Markdown and Word`.

### Task 5: Final check

- [ ] Run all test files; record counts.
- [ ] Ask the user to quit via tray "ออก", reopen, export one real guide in all four formats and open each file (PDF reader, a Markdown viewer after unzipping, Word); check Thai text, pictures, blurs, TOC.
- [ ] Update spec status line to "สร้างแล้ว รอผู้ใช้ทดสอบ" and commit.
