# StepCap piece 2 — image editor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Scribe-style screenshot editing to StepCap: guide-wide click-target style (colour, shape, size); a full-window image editor (click targets, arrows, boxes, text, blur, black-out, crop, undo, replace, download); image and GIF steps; and exports and downloads in which hidden pixels are really gone.

**Architecture:**
- **Data and server.**
  - `library.py` gains the new fields' defaults and the uploaded-image sniffing and saving.
  - `app.py` gains an upload route, a "save image as" route, and correct image content types.
- **Rendering.** All drawing stays in the page's canvas. `drawStepCanvas` (self-contained, also embedded in exports) learns redactions, annotations and square markers.
- **Export and download.** Both "flatten" every non-GIF step to a PNG first, so originals never leave the machine.
- **Editor.** The full-window editor is a new `ui/editor.js`. The edit-mode step card stops editing inline and shows a preview plus buttons.

**Tech Stack:** Python 3.14 (`.venv`), pywebview 6.2.1 / WebView2, vanilla JS + `<canvas>`. No new dependencies; Pillow is used **in tests only** to make and read images.

**Spec:** `docs/specs/2026-10-15-image-editor-design.md` (Thai, approved 2026-10-15). Section numbers (§3.5, §6 …) refer to it.

## Global Constraints

- **Stack and dependencies:**
  - No new dependencies.
  - All flattening happens in the page canvas, not in Pillow (§6).
  - Everything stays inside the app window. Native Windows open/save dialogs are fine; no browser windows.
- **Copy and look:** every user-visible string is Thai; light theme; reuse the existing tokens and `SWATCHES` in `ui/index.html` / `ui/guide.js`.
- **Coordinates:** every coordinate is in natural image pixels of the full image. Crop is applied only when drawing.
- **Draw order:** image → redactions (blur/black) → annotations (box/arrow/text) → click markers.
- **Self-contained rendering:** `drawStepCanvas` and `renderGuide` must not reference any page global (exports embed their source).
- **Hidden pixels really gone (§3.5):**
  - Exports and downloads contain only flattened PNGs for non-GIF steps.
  - The original image bytes never appear in either.
  - Originals on disk are never modified.
- **GIF steps (§3.3, §6):**
  - Shown animated; no crop, markers, annotations or redactions; download and export the file as-is.
  - Detection: `/\.gif$/i` on `step.image`, or `step._gif` in exports.
- **Uploads:** PNG, JPEG or GIF by magic bytes only, ≤ 25 MB (`25 * 1024 * 1024`), saved under a new server-chosen name in the guide folder.
- **Old guides:**
  - Old guides open unchanged.
  - Defaults are added only by `library.normalize` on read; files are rewritten only on save.
- **Tests:**
  - No synthesized desktop input; DOM events dispatched inside our own page are fine.
  - Temp storage via `STEPCAP_STORAGE`.
  - Existing tests keep passing.
- **Commands:**
  - Run tests: `cd /d/dev/stepcap && .venv/Scripts/python.exe -X utf8 <file>`.
  - JS syntax check: `node --check ui/<file>.js`.

## Review Focus

1. **A redaction that crosses the crop edge.** It is flattened correctly: the output PNG is crop-sized, and every pixel of the hidden part inside the crop is changed. Pinned by `test_bake_redaction_across_crop` (Task 3).
2. **An old guide opened in the editor and exported.** Example: markers without `shape`, no `annotations`/`redactions`. Nothing throws, and the export flattens it. Pinned by `test_old_guide_exports_flattened` (Task 3).
3. **Pasting text (not an image) on the edit page or in the editor.** No upload, no new step, and normal text paste into inputs still works. Pinned by `test_text_paste_ignored` (Task 4).
4. **A step whose image file is corrupt or missing.** The card shows `เปิดภาพนี้ไม่ได้`, the page keeps working, and the step stays deletable. Pinned by `test_broken_image_tolerated` (Task 4).
5. **Undo after "เปลี่ยนภาพ".** It restores the old image file and all its markers, annotations, redactions and crop. Pinned by `test_undo_restores_replaced_image` (Task 5).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `library.py` | Defaults for the new fields, shape checks, `image_kind`, `add_image`, `IMAGE_MIME` | Modify |
| `app.py` | `POST /api/guide/<id>/image`, `POST /api/guide/<id>/download`, `/img/` content types, shared `save_as` | Modify |
| `ui/guide.js` | Renderer (`drawStepCanvas` layers, GIF `<img>`), `renderStepPng`, `buildExportHtml`; edit-page click-style popover, step card preview and buttons, `+ เพิ่มภาพ`, paste-to-add, `downloadStepImage` | Modify |
| `ui/editor.js` | Full-window image editor (`openImageEditor`, the `IED` test hooks) | Create |
| `ui/index.html` | Load `ui/editor.js`; editor and card CSS | Modify |
| `test_library.py` | New field defaults and upload sniffing tests | Modify |
| `test_app.py` | Upload, content-type and download (Save As) route tests | Modify |
| `test_render.py` | Page-level checks run in a pywebview window against a launched app (flattening, export, paste, broken images, editor) | Create |

---

### Task 1: library — new fields, shape checks, uploaded images

**Files:** Modify `library.py`; Test `test_library.py`

**Interfaces:**
- Produces:
  - Constants:
    - `DEFAULT_SETTINGS` gains `"click_shape": "circle"` and `"click_size": 44`.
    - `MAX_IMAGE = 25 * 1024 * 1024`
    - `IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif"}`
  - `normalize(g)`:
    - Each step becomes `{"image": None, "crop": None, "markers": [], "annotations": [], "redactions": [], **s}`.
    - Each marker becomes `{"shape": "circle", **m}`.
  - `_is_guide(g)`: also rejects a step whose `markers`, `annotations` or `redactions` is present but is not a list of dicts.
  - `image_kind(data: bytes) -> str | None` returns `"png"`, `"jpg"` or `"gif"` by magic bytes:
    - PNG: `b"\x89PNG\r\n\x1a\n"`
    - JPEG: `b"\xff\xd8\xff"`
    - GIF: `b"GIF87a"` / `b"GIF89a"`
  - `add_image(storage: Path, gid: str, data: bytes) -> str | None`:
    - Returns the saved file name `i<8 hex>.<kind>`, unique in the folder.
    - Returns `None` for a bad id, a missing folder, an unknown kind, an empty body, or `len(data) > MAX_IMAGE`.

- [ ] **Step 1: Write the failing tests** (in `test_library.py`; Pillow makes the real image bytes)

```python
def _img_bytes(fmt):            # helper: 4x4 image in that Pillow format
    from io import BytesIO; from PIL import Image
    b = BytesIO(); Image.new("RGB", (4, 4), (255, 0, 0)).save(b, fmt); return b.getvalue()

def test_normalize_new_image_fields():
    g = normalize({"id": "x", "title": "A - b", "steps": [
        {"id": "s1", "kind": "click", "text": "t", "markers": [{"x": 1, "y": 2, "color": "#FB923C", "size": 44}]}]})
    s = g["steps"][0]
    assert s["annotations"] == [] and s["redactions"] == []
    assert s["markers"][0]["shape"] == "circle" and s["markers"][0]["size"] == 44
    assert g["settings"]["click_shape"] == "circle" and g["settings"]["click_size"] == 44
    keep = normalize({**g, "steps": [{**s, "markers": [{**s["markers"][0], "shape": "rect"}]}]})
    assert keep["steps"][0]["markers"][0]["shape"] == "rect"
    assert normalize(g) == g

def test_wrong_shape_layers_skipped():
    # seed "a" ok; "b" with markers "x"; "c" with annotations [1]; "d" with redactions {"x":1}
    # list_guides(st) ids == ["a"]

def test_image_kind():
    assert image_kind(_img_bytes("PNG")) == "png"
    assert image_kind(_img_bytes("JPEG")) == "jpg"
    assert image_kind(_img_bytes("GIF")) == "gif"
    assert image_kind(b"hello") is None and image_kind(b"") is None

def test_add_image_saves_only_real_images():
    # seed "g1"; n = add_image(st, "g1", _img_bytes("GIF")) -> matches r"^i[0-9a-f]{8}\.gif$", file bytes equal input
    # a second add returns a different name
    # add_image(st, "g1", b"<html>") is None; add_image(st, "g1", b"") is None
    # add_image(st, "g1", b"\x89PNG\r\n\x1a\n" + b"0" * MAX_IMAGE) is None   (too large)
    # add_image(st, "../x", png) is None; add_image(st, "missing", png) is None
    # no files other than guide.json + the two saved images exist in st/"g1"
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -X utf8 test_library.py`. Expected: ImportError for `image_kind`.
- [ ] **Step 3: Implement** the Produces block in `library.py`. `add_image` writes with `Path.write_bytes` in a `try/except OSError → None`.
- [ ] **Step 4: Run** again. Expected: `18/18 passed`.
- [ ] **Step 5: Commit** `feat: image fields defaults and uploaded image checks in library`.

---

### Task 2: app — upload, download (Save As), image content types

**Files:** Modify `app.py`; Test `test_app.py`

**Interfaces:**
- Consumes: `library.add_image`, `library.image_kind`, `library.IMAGE_MIME`, `library.MAX_IMAGE` (Task 1).
- Produces:
  - **Routes** (token-gated; ids checked with `library.safe_id`; `_GUIDE_RE` action group gains `image|download`):

    | Route | Body | Returns |
    |---|---|---|
    | `POST /api/guide/<id>/image` | raw image bytes | `{"image": name}`. Status 400 `bad image` when `add_image` returns None. Status 413 when `Content-Length > MAX_IMAGE`, without reading the body and with `self.close_connection = True`. |
    | `POST /api/guide/<id>/download?n=<step number>` | PNG or GIF bytes | Native Save As → `{"saved": path or null}`. Status 400 if `image_kind(body)` is not png/gif. |

  - **`/img/<id>/<file>`:** answers `IMAGE_MIME` by the file's extension (`.jpeg` counts as jpg); unknown extensions → 404.
  - `save_as(filename: str, data: bytes, file_type: str) -> str | None` replaces the body of `export_guide`:
    - The title is sanitized as today (`re.sub(r'[\\/:*?"<>|]', "_", …)`).
    - `file_type` is an ASCII filter such as `"PNG (*.png)"`.
    - Returns None when cancelled.
  - **Download file name:** `f"{title} - ขั้นตอน {n}.{ext}"` with `ext` from `image_kind`.

- [ ] **Step 1: Write the failing tests** in `test_app.py`. Add them before `test_shutdown_not_blocked`, which must stay last.

```python
def test_upload_and_content_types():
    png, gif = _img("PNG"), _img("GIF")          # local helper like test_library._img_bytes
    name = post(f"/api/guide/{OLD_ID}/image", png)["image"]
    code, ctype = head_type(f"/img/{OLD_ID}/{name}")   # helper: urllib GET -> (status, Content-Type)
    assert code == 200 and ctype == "image/png"
    gname = post(f"/api/guide/{OLD_ID}/image", gif)["image"]
    assert head_type(f"/img/{OLD_ID}/{gname}")[1] == "image/gif"
    assert post(f"/api/guide/{OLD_ID}/image", b"<html>") == 400
    assert get(f"/api/guide/{OLD_ID}")["steps"] == get(f"/api/guide/{OLD_ID}")["steps"]  # upload alone changes no step

def test_download_save_as():
    # same pattern as test_export_save_as: export_async-like thread posting to
    # f"/api/guide/{OLD_ID}/download?n=2" with PNG bytes; the dialog's name box ends with "09_00 - ขั้นตอน 2.png";
    # set the path to CTX["storage"]/"step2.png" -> saved resolves to it; file bytes == body
    # posting b"hello" -> 400 (no dialog opens)
```

- [ ] **Step 2: Run** `timeout 260 .venv/Scripts/python.exe -X utf8 test_app.py`. Expected: the two new tests FAIL (404 on the routes).
- [ ] **Step 3: Implement** the Produces block. `export_guide` becomes a thin call to `save_as(title + ".html", html, "HTML (*.html)")`.
- [ ] **Step 4: Run** again. Expected: `10/10 passed`.
- [ ] **Step 5: Commit** `feat: image upload, save-image-as route and real image content types`.

---

### Task 3: renderer — layers, GIF, flattening for export and download

**Files:** Modify `ui/guide.js` (renderer + export section only); Create `test_render.py`

**Interfaces:**
- Consumes: `/img/` content types (Task 2).
- Produces (globals in `ui/guide.js`):
  - **`drawStepCanvas(canvas, img, step, maxW)`** keeps its signature. After drawing the cropped image it draws, in the global draw order:
    - **Redactions** (each clipped to its rect):
      - `black`: fill `#000`.
      - `blur`: redraw the image through `ctx.filter = "blur(" + Math.max(16, Math.round(Math.min(w, h) / 4)) + "px)"`.
    - **Annotations:**
      - `box`: stroke rect.
      - `arrow`: line plus a filled head. Head length `Math.max(14, width * 3.5)`, half-angle 28°.
      - `text`: font `"bold " + size + 'px "Leelawadee UI","Segoe UI",sans-serif'`. Draw `strokeText` in `#fff` with `lineWidth = size * 0.18` and `lineJoin = "round"`, then `fillText` in its colour, with `textBaseline = "top"`.
    - **Markers:** `circle` as today. `rect` is a rounded square with side `size` and corner radius `size * 0.2`, using the same fill and stroke rules.
    - All helpers are nested inside the function.
  - **`renderGuide`:** a GIF step (`step._gif || /\.gif$/i.test(step.image || "")`) renders `<img src=_src style="max-width:100%">` instead of a canvas.
  - **`renderStepPng(step, gid) -> Promise<Blob>`:** loads `imgUrl(gid, step.image)` and calls `drawStepCanvas` without `maxW`, then `canvas.toBlob(…, "image/png")`. Rejects if the image fails to load.
  - **`buildExportHtml(gid) -> Promise<string>`:**
    - **Non-GIF image steps:** `_src` becomes the data URL of `renderStepPng`. Then `crop = null` and `markers`, `annotations` and `redactions` become `[]`.
    - **GIF steps:** `_src` becomes the original bytes as a data URL, and `_gif` is set to `true`.
    - **Every step:** `image` is deleted.
    - The rest is today's export HTML.
  - **`exportGuide(gid)`:** becomes `buildExportHtml` followed by the POST.

- [ ] **Step 1: Write `test_render.py` (failing).**
  - **Harness:** reuse the `test_app` helpers (`setup`, `teardown`, `CTX`, `post`, `get`), but seed the guides below before `setup()` launches the app. Run all checks inside one `webview.start(func)`, in a window titled `render-test` that loads `base + "&guide=<id>&mode=edit"`. The `js(expr)` helper calls `evaluate_js`. If pywebview does not resolve promises, the helper stores the result on `window.__r` and polls until it is set.
  - **Guide `noise`:**
    - **Image `n.png`:** 320×200 random RGB noise (Pillow, fixed seed 7).
    - **Redactions:** black `{x:20, y:20, w:60, h:40}` and blur `{x:200, y:100, w:80, h:60}`.
    - **Annotations:** one box and one arrow.
    - **Marker:** one, with `shape: "rect"`.
    - **Crop:** none.
  - **Guide `cropx`:** the same image with crop `{x:100, y:50, w:150, h:100}` and black redaction `{x:220, y:120, w:80, h:60}` (it crosses the crop's right/bottom edge).
  - **Guide `old`:** pieces-0+1 shape: markers without `shape`, no `annotations`/`redactions`, no `click_shape` setting.

```python
def test_bake_hides_pixels():
    png = b64decode(js("renderStepPng(STATE.steps[0], GID).then(blobToB64)"))   # blobToB64: small in-test JS helper
    img, orig = Image.open(BytesIO(png)).convert("RGB"), NOISE
    assert img.size == (320, 200)
    assert all(img.getpixel((x, y)) == (0, 0, 0) for x in range(20, 80) for y in range(20, 60))
    same = sum(img.getpixel((x, y)) == orig.getpixel((x, y)) for x in range(205, 275) for y in range(105, 155))
    assert same / (70 * 50) < 0.05                      # blurred: originals gone
    assert img.getpixel((300, 10)) == orig.getpixel((300, 10))   # untouched elsewhere

def test_export_contains_no_original():
    html = js("buildExportHtml(GID)")
    assert b64encode(NOISE_PNG_BYTES).decode()[:200] not in html
    data = json.loads(re.search(r"const guide=(.*?);\n", html, re.S).group(1))
    s = data["steps"][0]
    assert s["crop"] is None and s["markers"] == [] and s["annotations"] == [] and s["redactions"] == []
    assert "image" not in s and s["_src"].startswith("data:image/png;base64,")
    # decoding s["_src"] gives the same black block as test_bake_hides_pixels

def test_bake_redaction_across_crop():          # guide "cropx"
    img = <renderStepPng of cropx step 0>
    assert img.size == (150, 100)
    assert all(img.getpixel((x, y)) == (0, 0, 0) for x in range(120, 150) for y in range(70, 100))

def test_old_guide_exports_flattened():         # guide "old"
    html = js(f"buildExportHtml({json.dumps('old')})")
    assert "data:image/png;base64," in html and '"markers":[]' in html.replace(" ", "")
```

- [ ] **Step 2: Run** `timeout 200 .venv/Scripts/python.exe -X utf8 test_render.py`. Expected: FAIL (`renderStepPng is not defined`).
- [ ] **Step 3: Implement** the Produces block in `ui/guide.js`.
- [ ] **Step 4: Run** `node --check ui/guide.js`, then `test_render.py`. Expected: `4/4 passed`. Then run `test_app.py`. Expected: `10/10 passed`. The export dialog test still passes.
- [ ] **Step 5: Commit** `feat: draw redactions, annotations and square markers; flatten images for export and download`.

---

### Task 4: edit page — click style, step cards, add image, paste, download

**Files:** Modify `ui/guide.js` (edit-mode section), `ui/index.html` (card CSS); Test `test_render.py`

**Interfaces:**
- Consumes:
  - From Task 3: `drawStepCanvas`, `renderStepPng`.
  - Routes: `POST /api/guide/<id>/image`, `POST /api/guide/<id>/download?n=` (Task 2).
- Produces (globals in `ui/guide.js`):
  - **`clickStyle() -> {color, shape, size}`** returns the guide's current `settings.click_color` / `click_shape` / `click_size`, with the defaults `#FB923C` / `circle` / `44`.
  - **`setClickStyle(patch: {color?, shape?, size?})`** replaces `setClickColor`.
    - It writes `settings.click_color` / `click_shape` / `click_size` for each key present.
    - It writes the same keys onto **every marker in every step**, and only those keys. Other annotation colours are untouched (§6).
    - Then it re-renders and saves.
  - **Toolbar button:** `data-tip="จุดคลิก (สี รูปทรง ขนาด)"`. Its popover, titled `จุดคลิก`, has:
    - colour swatches, the colour input and the hex box (as today);
    - the segment `วงกลม | สี่เหลี่ยม`;
    - `ขนาด`: `<input type=range min=24 max=96>` (`oninput` updates the label, `onchange` applies);
    - the note `เปลี่ยนทุกวงในคู่มือนี้ และวงที่เพิ่มใหม่`.
  - **`uploadImage(blob) -> Promise<string | null>`:** posts to `/api/guide/<GID>/image`. On failure it shows `toast("ไฟล์นี้ใช้ไม่ได้ รองรับ PNG, JPG, GIF ขนาดไม่เกิน 25 MB")` and returns null.
  - **`addImageStep(blob)`:**
    - Uploads, then pushes `{id: newStepId(), kind: "image", text: "", image, crop: null, markers: [], annotations: [], redactions: []}`.
    - Re-renders, saves, and focuses that card's text box.
  - **`KIND_TH.image = "ภาพ"`.**
  - **Buttons:**
    - Under the steps, next to `+ เพิ่มหมายเหตุ`, a `+ เพิ่มภาพ` button opens a hidden `<input type=file accept="image/png,image/jpeg,image/gif">`.
    - The page `paste` listener runs only when the editor is closed and `!e.target.closest("input,textarea")`. It takes the first `clipboardData.items` entry whose `kind === "file"` and whose type starts with `image/`, then calls `addImageStep`. Anything else is ignored: no `preventDefault`, no upload.
  - **Step card** (replaces the inline `imageEditor`, which moves to Task 5):
    - **Preview:** a canvas through `drawStepCanvas(…, 860)`, or `<img>` for GIF.
    - **On image load error:** a muted box `เปิดภาพนี้ไม่ได้`; the card stays deletable.
    - **Buttons:** `แก้ไขภาพ` calls `openImageEditor(step.id)` (Task 5; until then a stub `toast("เร็วๆ นี้")`), and `ดาวน์โหลดภาพ` calls `downloadStepImage(step)`.
  - **Grid cards:** use `<img>` for GIF thumbnails.
  - **`downloadStepImage(step) -> Promise<void>`:**
    - The body is the original bytes for GIF, else `renderStepPng`.
    - It posts to `/download?n=<step number>`; the step number skips notes.
    - On `saved` it shows `toast("บันทึกภาพแล้ว")`.
- Removes:
  - `setClickColor`, replaced by `setClickStyle`;
  - the colour-only `renderColorPop`, replaced by the `จุดคลิก` popover;
  - `imageEditor` from `guide.js`, which moves to Task 5;
  - the globals `lastSize` and `sel`.

- [ ] **Step 1: Add the failing tests** to `test_render.py`.
  - **Seeds:** guide `noise` gets a second click step with two markers. A new guide `broken` has one step with image `missing.png` and a second with image `bad.png`, which is the PNG magic followed by junk.

```python
def test_click_style_all_markers():
    js("setClickStyle({shape: 'rect', size: 70}); 1")
    ms = js("STATE.steps.flatMap(s => s.markers)")
    assert ms and all(m["shape"] == "rect" and m["size"] == 70 for m in ms)
    assert js("STATE.settings.click_shape + STATE.settings.click_size") == "rect70"
    assert {a["color"] for a in js("STATE.steps[0].annotations")} == <colours seeded>   # untouched

def test_text_paste_ignored():
    n = js("STATE.steps.length")
    js("const dt=new DataTransfer(); dt.setData('text/plain','hi'); document.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true})); 1")
    time.sleep(1); assert js("STATE.steps.length") == n

def test_image_paste_adds_step():
    # dispatch a paste whose DataTransfer holds new File([<4x4 png bytes>], "p.png", {type:"image/png"})
    # within 3 s: STATE.steps.length == n + 1, last step kind == "image", its image ends with ".png",
    # and that file exists in the guide folder

def test_broken_image_tolerated():              # page on guide "broken", mode=edit
    assert js("document.querySelectorAll('.step').length") == 2
    assert js("[...document.querySelectorAll('.imgfail')].length") == 2   # 'เปิดภาพนี้ไม่ได้'
    js("STATE.steps.splice(0,1); renderSteps(); 1"); assert js("document.querySelectorAll('.step').length") == 1
```

- [ ] **Step 2: Run** `test_render.py`. Expected: the 4 new tests FAIL.
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Check.**
  - `node --check ui/guide.js`, then `test_render.py` → `8/8 passed`.
  - `test_app.py` → `10/10`.
  - Visual check with the scratch `shot.py` approach on a copy of the real guides: the edit page shows previews and both buttons, and the `จุดคลิก` popover has a colour, a shape and a size.
- [ ] **Step 5: Commit** `feat: guide-wide click style, image steps, paste-to-add and per-step image download`.

---

### Task 5: full-window image editor

**Files:** Create `ui/editor.js`; Modify `ui/index.html` (load it after `guide.js`, editor CSS) and `ui/guide.js` (the `แก้ไขภาพ` button calls the real editor); Test `test_render.py`

**Interfaces:**
- Consumes:
  - `STATE`, `GID`, `scheduleSave`, `renderSteps`, `SWATCHES` and `clickStyle()` (the current `{color, shape, size}`) from `guide.js`.
  - `drawStepCanvas`, `uploadImage`, `downloadStepImage`, plus `uiPrompt` and `toast` from `common.js`.
- Produces:
  - **`openImageEditor(stepId: string) -> void`** opens a fixed full-window overlay `.ied` (z-index 50) over the edit page. `closeImageEditor()` closes it and calls `renderSteps()`.
  - **`IED`** is a global test hook: `{step, tool, sel, history, toImage(clientX, clientY) -> {x, y}, undo(), replaceImage(blob) -> Promise<bool>}`.
  - **Top bar,** left to right. Every button has a Thai `data-tip` tooltip shown below it.
    - **Tools:** `เลือก` (default), `จุดคลิก`, `ลูกศร`, `กรอบ`, `ข้อความ`, `เบลอ`, `ปิดดำ`, `ครอป`.
    - **Then:** `ย้อนกลับ (Ctrl+Z)`, `เปลี่ยนภาพ` (hidden file input), `ดาวน์โหลดภาพ` (calls `downloadStepImage(IED.step)`), and a dark `เสร็จ` button.
  - **Options row** under the bar, for the active tool or the selection:
    - colour swatches;
    - `เส้น` `บาง | กลาง | หนา` = width 4 / 8 / 14 (default 8);
    - `ขนาดตัวอักษร` `เล็ก | กลาง | ใหญ่` = 28 / 40 / 56 (default 40);
    - for a selected marker: shape segment and size range 24–96;
    - for crop: `ล้างครอป`;
    - for any selection: `ลบ`.
  - **Stage:** one canvas showing the **full uncropped** image fitted to the available area (contain; no zoom or pan).
    - Every redraw uses `drawStepCanvas` on a copy of the step with `crop: null`.
    - When a crop exists, the area outside it is dimmed (`rgba(0,0,0,.45)`) and its border dashed.
    - The selection gets a 2px `#2563eb` outline.
    - `toImage` maps client coordinates to natural pixels.
  - **Interaction:**
    - **Marker tool:** click adds `{x, y, ...clickStyle()}`.
    - **Arrow:** drag from start to end; ignored under 10 natural px.
    - **Box, blur, black, crop:** drag a rect; ignored under 10×10.
    - **Text:** click, then `uiPrompt("พิมพ์ข้อความ")`; an empty result adds nothing.
    - **Select:** hit-test topmost first (markers → annotations → redactions) with 8 screen-px tolerance. Drag moves the object; `Delete`/`Backspace` removes it (not while typing); double-clicking text calls `uiPrompt("แก้ข้อความ", text)`.
    - **Esc:** returns the active tool to `เลือก`, then deselects.
    - **New annotations:** their colour defaults to `clickStyle().color`.
    - **Ctrl+V:** while the editor is open, an image paste calls `IED.replaceImage`.
    - **GIF:** every drawing tool and crop is disabled (`aria-disabled`, tip `ใช้กับ GIF ไม่ได้`). Replace, download and done still work.
  - **History:**
    - Before every mutation (add, move end, delete, colour/size/shape change, crop, clear crop, text edit, replace), push the JSON snapshot `{image, crop, markers, annotations, redactions}`. Each mutation then calls `scheduleSave()`.
    - `undo()` pops a snapshot and restores it (reloading the image if `image` changed).
    - The history is reset on close.
  - **`replaceImage(blob)`:** calls `uploadImage`, then pushes history, sets `step.image` to the new name, and clears crop, markers, annotations and redactions. Old files are never deleted.

- [ ] **Step 1: Add the failing tests** to `test_render.py`. They dispatch DOM events inside the page only.

```python
def test_editor_draws_box_and_undoes():
    js("openImageEditor(STATE.steps[0].id); 1")
    js("IED.tool='box'; const c=document.querySelector('.ied canvas'), r=c.getBoundingClientRect();"
       "const ev=(t,x,y)=>c.dispatchEvent(new PointerEvent(t,{clientX:r.left+x,clientY:r.top+y,bubbles:true}));"
       "ev('pointerdown',20,20); ev('pointermove',120,90); ev('pointerup',120,90); 1")
    n = js("IED.step.annotations.length"); assert n == <seeded> + 1
    a = js("IED.step.annotations.at(-1)"); assert a["type"] == "box" and a["w"] > 10
    js("IED.undo(); 1"); assert js("IED.step.annotations.length") == n - 1

def test_editor_maps_coordinates():
    p = js("(() => { const c=document.querySelector('.ied canvas'), r=c.getBoundingClientRect(); return IED.toImage(r.right-1, r.bottom-1); })()")
    assert 318 <= p["x"] <= 320 and 198 <= p["y"] <= 200        # noise image 320x200

def test_undo_restores_replaced_image():
    before = js("JSON.stringify([IED.step.image, IED.step.markers, IED.step.annotations, IED.step.redactions, IED.step.crop])")
    js("IED.replaceImage(new Blob([<png bytes>], {type:'image/png'}))")      # awaited via the js() helper
    assert js("IED.step.markers.length + IED.step.annotations.length + IED.step.redactions.length") == 0
    js("IED.undo(); 1")
    assert js("JSON.stringify([IED.step.image, IED.step.markers, IED.step.annotations, IED.step.redactions, IED.step.crop])") == before

def test_editor_gif_tools_disabled():           # step with a .gif image (uploaded in setup)
    js(f"openImageEditor({json.dumps(GIF_STEP_ID)}); 1")
    assert js("[...document.querySelectorAll('.ied [data-tool]')].filter(b => b.dataset.tool !== 'select').every(b => b.getAttribute('aria-disabled') === 'true')")
```

- [ ] **Step 2: Run** `test_render.py`. Expected: the 4 new tests FAIL (`openImageEditor is not defined`).
- [ ] **Step 3: Implement** `ui/editor.js` and wire the `แก้ไขภาพ` button.
- [ ] **Step 4: Check.**
  - `node --check ui/editor.js ui/guide.js`, then `test_render.py` → `12/12 passed`. Then the full suite.
  - **Visual check** on the scratch copy, using `shot.py` with `@js:` openers:
    1. The editor is open over a real guide.
    2. A box, an arrow, text, a blur and a black-out have been added through the `IED` hooks.
    3. The export of that guide looks right in a pywebview viewer window.
- [ ] **Step 5: Commit** `feat: full-window image editor (click targets, arrows, boxes, text, blur, black-out, crop, undo, replace)`.

---

### Task 6: Acceptance

- [ ] **Step 1: Run the full suite:**

  ```bash
  test_steps; test_library; test_windows; test_app; test_render; node --check ui/*.js
  ```

  Expected: all pass.
- [ ] **Step 2: Hand the user a Thai checklist** for their real use:
  - **Click targets:** the `จุดคลิก` popover changes the size, shape and colour of every ring at once. Changing one ring still works.
  - **Editor:** open `แก้ไขภาพ`. Draw an arrow, a box, text, a blur and a black-out; Ctrl+Z works; crop and clear crop work.
  - **Images:** `เปลี่ยนภาพ` from a file and with Ctrl+V; `+ เพิ่มภาพ` and Ctrl+V on the page add image steps; a GIF plays in view mode and in the export.
  - **Downloads and export:** `ดาวน์โหลดภาพ` saves a PNG through Save As. The export opens with the blurred and blacked-out parts hidden.
  - **Old guides:** they still open, and their rings look the same as before.
- [ ] **Step 3: Mark the spec status** `สร้างแล้ว รอผู้ใช้ทดสอบจริง (ส่วนที่ 2)` and commit `docs: piece 2 built, awaiting the user's acceptance run`.
