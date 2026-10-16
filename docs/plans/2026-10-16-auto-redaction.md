# ส่วนที่ 3 ซ่อนข้อมูลอัตโนมัติ — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Blur emails, Thai phone numbers, Thai ID numbers, card numbers, bank account numbers and user-chosen words found in step images (Windows OCR) and mask them in typed-step text.

**Architecture:** New `redact.py`: pure rule matching on top (importable anywhere, like `recorder.py`), Windows OCR glue below. After a recording stops, `app.py` runs `redact.redact_guide` on a thread before opening the guide; images added later go through a new `POST /api/guide/<id>/redact` that the page calls and then writes into `STATE` itself (the page stays the only writer of an open guide).

**Tech Stack:** Python 3.14, `winrt-*` 3.2.1 (pywinrt) for `Windows.Media.Ocr`, Pillow, existing pywebview page JS.

**Spec:** `docs/specs/2026-10-16-auto-redaction-design.md`

## Global Constraints

- Local only; no network calls, no AI services. OCR language `en-US` only (Thai is not available on Windows OCR).
- All UI copy in Thai, light theme, everything inside the app window.
- Auto items are plain `{"type": "blur", "x", "y", "w", "h"}` in `step.redactions` (image coords, before crop) — no new keys, so old guides and export are untouched.
- Failure is never silent: OCR unavailable, unreadable image, or GIF → the user is told which steps were not covered.
- A new guide is not shown (so cannot be exported) until its redaction pass finished.
- Tests: `STEPCAP_STORAGE` temp dir, images generated in the test, no real desktop clicks/typing, never touch `Documents\StepCap`. Run each as `.venv/Scripts/python.exe test_X.py`.
- Defaults: `redact_on: True`, all five rules on, custom words empty.

## Review Focus

- Text split by OCR into several words ("081 234 5678", "me @ mail.com") → still one blur covering all its words. Pinned in Task 1 (`test_rects_join_split_words`).
- A long number that is not an ID/card (e.g. order no. `1234567890123` failing checksum) → not blurred. Pinned in Task 1 (`test_checksums_reject`).
- Blur rect near the image edge → clamped inside the image, never negative/oversized. Pinned in Task 1 (`test_rects_clamped`).
- Pressing the editor button twice → no duplicate blurs. Pinned in Task 1 (`test_new_rects_skips_covered`) and Task 5 page test.
- Big screenshot (4K, over `OcrEngine.max_image_dimension`) → rects still map back to full-size coords. Pinned in Task 2 (`test_ocr_large_image_scales_back`).

---

### Task 1: Pure rules in `redact.py`

**Files:**
- Create: `redact.py` (pure part only)
- Test: `test_redact.py` (same `__main__` runner style as `test_steps.py`)

**Interfaces:**
- Produces:
  - `RULES = ("email", "phone", "thai_id", "card", "bank")`
  - `find_spans(text: str, rules: Iterable[str], custom: Iterable[str]) -> list[tuple[int, int]]` — sorted, overlapping spans merged.
  - `mask_text(text: str, rules, custom) -> str` — each span becomes `"•••"`.
  - `line_rects(words: list[tuple[str, tuple[float, float, float, float]]], rules, custom, size: tuple[int, int]) -> list[dict]` — words of one OCR line, `(x, y, w, h)` each; joins words with one space, maps each span to the union of overlapping words, pads by `PAD = 4`, clamps to `size`, returns `{"type": "blur", "x", "y", "w", "h"}` as ints.
  - `new_rects(found: list[dict], existing: list[dict]) -> list[dict]` — drops a found rect fully inside any existing redaction.

Patterns (exact intent; tune the regex, not the intent):
- email `[\w.+-]+@[\w-]+(\.[\w-]+)+`
- phone: `0` + 8–9 digits, or `+66` + 8–9 digits, digits may be separated by single spaces/dashes, not part of a longer digit run
- thai_id: 13 digits (separators allowed, e.g. `1-2345-67890-12-1`), checksum `(11 - sum(d[i]*(13-i) for i in 0..11) % 11) % 10 == d[12]`
- card: 13–19 digits (separators allowed), Luhn valid
- bank: 10 digits as `xxx-x-xxxxx-x` or 10 in a row
- custom: each non-empty word, `re.escape`, case-insensitive

- [ ] **Step 1: Write failing tests**

```python
def test_email_and_custom():
    assert find_spans("mail me@x.co now", RULES, []) == [(5, 12)]
    assert find_spans("ACME Corp", [], ["acme"]) == [(0, 4)]
def test_phone_formats():
    for s in ("081-234-5678", "081 234 5678", "0812345678", "02-123-4567", "+66 81 234 5678"):
        assert find_spans(s, ["phone"], []) == [(0, len(s))], s
def test_checksums_reject():
    assert find_spans("1101700230708", ["thai_id"], []) == [(0, 13)]   # valid checksum
    assert find_spans("1101700230705", ["thai_id"], []) == []          # last digit wrong
    assert find_spans("1234567890123", ["thai_id", "card"], []) == []
    assert find_spans("4111 1111 1111 1111", ["card"], []) == [(0, 19)]
def test_mask_text():
    assert mask_text('พิมพ์ "me@x.co" ในช่อง', RULES, []) == 'พิมพ์ "•••" ในช่อง'
def test_rules_off():
    assert find_spans("me@x.co 0812345678", [], []) == []
def test_rects_join_split_words():
    words = [("call", (0, 0, 40, 20)), ("081", (50, 0, 30, 20)), ("234", (85, 0, 30, 20)), ("5678", (120, 0, 40, 20))]
    assert line_rects(words, RULES, [], (400, 100)) == [{"type": "blur", "x": 46, "y": 0, "w": 118, "h": 24}]
def test_rects_clamped():
    r = line_rects([("me@x.co", (2, 1, 60, 18))], RULES, [], (60, 18))[0]
    assert (r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]) == (0, 0, 60, 18)
def test_new_rects_skips_covered():
    a = {"type": "blur", "x": 10, "y": 10, "w": 50, "h": 20}
    assert new_rects([a], [{"type": "black", "x": 0, "y": 0, "w": 100, "h": 100}]) == []
    assert new_rects([a], []) == [a]
```

- [ ] **Step 2:** Run `.venv/Scripts/python.exe test_redact.py` — FAIL (`ModuleNotFoundError: redact`).
- [ ] **Step 3:** Implement the pure part of `redact.py` (stdlib `re` only).
- [ ] **Step 4:** Run `test_redact.py` — all pass.
- [ ] **Step 5:** Commit `feat: rule matching for auto-redaction`.

### Task 2: Windows OCR glue

**Files:**
- Modify: `redact.py` (Windows part below the pure part), `requirements.txt`
- Test: `test_redact.py`

**Interfaces:**
- Consumes: `line_rects`.
- Produces:
  - `class RedactError(Exception)` — message is Thai, shown to the user.
  - `available() -> str | None` — `None` when OCR works, else Thai reason (`"ไม่มี OCR ภาษาอังกฤษในเครื่อง"`, `"โหลดตัวอ่านตัวอักษรไม่ได้"`).
  - `ocr_lines(path: Path) -> list[list[tuple[str, tuple[float, float, float, float]]]]` — one list of words per OCR line, rects in the file's pixel coords.
  - `find_rects(path: Path, rules, custom) -> list[dict]` — raises `RedactError` when OCR is unavailable or the image can't be read.

- [ ] **Step 1:** Install and record deps: `winrt-runtime`, `winrt-Windows.Media.Ocr`, `winrt-Windows.Graphics.Imaging`, `winrt-Windows.Storage.Streams`, `winrt-Windows.Globalization`, `winrt-Windows.Foundation`, `winrt-Windows.Foundation.Collections` (all `==3.2.1`) into `.venv` and `requirements.txt`. Check: `.venv/Scripts/python.exe -c "from winrt.windows.media.ocr import OcrEngine; print(OcrEngine.max_image_dimension)"` prints a number.
- [ ] **Step 2: Write failing tests** (Pillow draws the text; `ImageFont.truetype("arial.ttf", 28)`):

```python
def test_ocr_finds_email_rect():
    p = _text_png("contact: someone@example.com", (640, 80))   # text drawn at x=20,y=20
    rs = find_rects(p, RULES, [])
    assert len(rs) == 1 and rs[0]["x"] < 160 < rs[0]["x"] + rs[0]["w"], rs   # covers the email, not "contact:"
def test_ocr_large_image_scales_back():
    p = _text_png("0812345678", (5000, 300), at=(4000, 200))
    r = find_rects(p, ["phone"], [])[0]
    assert 3990 <= r["x"] <= 4010, r
def test_unreadable_image_raises():
    bad = TMP / "bad.png"; bad.write_bytes(b"\x89PNG junk")
    try: find_rects(bad, RULES, []); assert False
    except RedactError: pass
```

- [ ] **Step 3:** Run — FAIL (`find_rects` undefined).
- [ ] **Step 4:** Implement: Pillow → RGBA → BGRA bytes → `SoftwareBitmap.create_copy_from_buffer`; downscale first if either side exceeds `OcrEngine.max_image_dimension` and scale rects back; `OcrEngine.try_create_from_language(Language("en-US"))`; run the async call with `asyncio.run`. Engine created once and reused.
- [ ] **Step 5:** Run `test_redact.py` — all pass.
- [ ] **Step 6:** Commit `feat: Windows OCR for auto-redaction`.

### Task 3: Settings

**Files:**
- Modify: `library.py:22` (`DEFAULT_APP_SETTINGS`, `save_settings` validation), `app.py:138-190` (GET/POST `/api/settings`), `ui/shell.js:299-301` (settings page)
- Test: `test_library.py`, `test_app.py`

**Interfaces:**
- Produces settings keys `redact_on: bool`, `redact_rules: list[str]` (subset of `RULES`), `redact_custom: list[str]`; GET `/api/settings` also returns `redact_error: str | None` from `redact.available()`.
- POST `/api/settings` accepts any of `view`, `redact_on`, `redact_rules`, `redact_custom`; rejects (400) wrong types or unknown rule names; custom words are stripped, empty ones dropped.

- [ ] **Step 1: Failing tests**
  - `test_library.py::test_redact_settings_defaults_and_validation`: fresh storage → `load_settings` has `redact_on is True`, `redact_rules == list(redact.RULES)`, `redact_custom == []`; `save_settings(st, redact_rules=["email", "x"])` keeps only valid names; `redact_custom=[" acme ", ""]` → `["acme"]`.
  - `test_app.py::test_redact_settings_route`: POST `{"redact_on": False}` then GET → `redact_on is False` and `"redact_error" in` response; POST `{"redact_on": "yes"}` → 400.
- [ ] **Step 2:** Run both — FAIL.
- [ ] **Step 3:** Implement. Settings page replaces the "เร็วๆ นี้" block: switch "ซ่อนข้อมูลอัตโนมัติ", a checkbox per rule (อีเมล / เบอร์โทรศัพท์ / เลขบัตรประชาชน / เลขบัตรเครดิต/เดบิต / เลขบัญชีธนาคาร), textarea "คำที่กำหนดเอง (บรรทัดละคำ)" saved on change, note "อ่านได้เฉพาะตัวอักษรอังกฤษและตัวเลข ตรวจภาพอีกครั้งก่อนส่งให้คนอื่น". When `redact_error` is set: switch disabled and the reason shown as "ใช้ไม่ได้บนเครื่องนี้: <reason>".
- [ ] **Step 4:** Run `test_library.py`, `test_app.py` — all pass.
- [ ] **Step 5:** Commit `feat: auto-redaction settings`.

### Task 4: After recording — mask typed text, blur images before the guide opens

**Files:**
- Modify: `recorder.py:86-120` (`_Typing`, `StepBuilder`), `recorder.py:505-515` (`start_recording`), `redact.py`, `app.py:304-317` (`stop_rec_ui`), `app.py:350-359` (`rec_status`), `ui/common.js:131-150` (status poll), `ui/guide.js` (show `note` param)
- Test: `test_steps.py`, `test_redact.py`

**Interfaces:**
- Consumes: `mask_text`, `find_rects`, `RedactError`, settings keys from Task 3.
- Produces:
  - `StepBuilder(mask: Callable[[str], str] | None = None)` — typed (non-password) text goes through `mask` in `_Typing.text()` (so live pending text is masked too).
  - `redact_guide(storage: Path, guide: dict, rules, custom, progress: Callable[[int, int], None] | None = None, find=find_rects) -> list[int]` — appends `new_rects` to each image step's `redactions`, writes `guide.json` once at the end, returns 1-based numbers of steps not covered (GIF, missing file, `RedactError`).
  - `/api/status` adds `redacting: [done, total] | None` and `redact_note: str | None`.

- [ ] **Step 1: Failing tests**
  - `test_steps.py::test_mask_typed_text`: `StepBuilder(mask=lambda t: t.replace("me@x.co", "•••"))`, type `me@x.co` + Enter → `'พิมพ์ "•••" แล้วกด Enter'`.
  - `test_redact.py::test_redact_guide_marks_and_reports`: temp guide with steps [png, gif, missing png]; fake `find` returning one rect → step 1 gets one blur, return value `[2, 3]`, `guide.json` on disk has the blur; progress called with `(3, 3)` last.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement.
  - `start_recording` loads settings; when `redact_on`, passes `mask=lambda t: redact.mask_text(t, rules, custom)`.
  - `stop_rec_ui`: when a guide was produced and `redact_on`, call `show_main()` first, set `REDACTING = [0, n]`, run `redact_guide` on a `threading.Thread`, then set `REDACT_NOTE` and only then bump `GUIDE_SEQ`/`LAST_GUIDE`. When `redact.available()` is not `None`, skip the pass and set the note to `"ไม่ได้ซ่อนข้อมูลอัตโนมัติ: <reason>"`. Uncovered steps → `"ซ่อนข้อมูลไม่สำเร็จ 2 ภาพ (ขั้นที่ 3, 7) ตรวจเองก่อนส่ง"`.
  - Status poll: while `st.redacting`, show a full-window cover "กำลังซ่อนข้อมูล… 3/20" (one element, updated in place, removed when `null`); on navigation to the new guide pass `note: st.redact_note` as a URL param; guide page `toast`s it on load (toast uses `textContent`, keep it that way). Keep the note visible longer than the default 2.5 s (≥ 6 s).
- [ ] **Step 4:** Run `test_steps.py`, `test_redact.py`, `test_app.py` — all pass.
- [ ] **Step 5:** Commit `feat: auto-redact new recordings`.

### Task 5: Images added later, and the editor button

**Files:**
- Modify: `app.py:86-87, 218-234` (`_GUIDE_RE` gains `redact`; new route), `ui/guide.js:372-392` (`addImageStep`), `ui/editor.js` (`iedReplace`, new toolbar button)
- Test: `test_render.py` (seed a guide `"pii"` whose `p.png` is drawn with `someone@example.com`), `test_app.py`

**Interfaces:**
- Consumes: `find_rects`, `new_rects`, `RedactError`, `available`.
- Produces: `POST /api/guide/<id>/redact` body `{"image": str, "existing": [redactions], "force": bool}` → `{"rects": [...]}` | `{"error": str}` (200 both; GIF → `{"error": "ภาพ GIF ซ่อนข้อมูลไม่ได้"}`). Without `force`, returns `{"rects": []}` when `redact_on` is false. `image` must pass `library.safe_name` and exist in the guide folder, else 404.
- JS: `autoRedact(step, force) -> Promise<number | null>` in `guide.js` — calls the route, pushes rects into `step.redactions`, returns how many were added (`null` on error, after `toast`ing the error).

- [ ] **Step 1: Failing tests**
  - `test_app.py::test_redact_route`: unknown image → 404; `../x.png` → 404.
  - `test_render.py::test_editor_redact_button`: open editor on `pii`, click `.ied [data-act=redact]`, wait for `IED.step.redactions.length === 1`; its rect covers x≈160; click again → still 1 and toast "ไม่พบข้อมูลที่ต้องซ่อน"; `IED.undo()` → 0.
  - `test_render.py::test_pasted_image_redacted`: paste the `pii` PNG as a new step (settings on) → new step gets 1 blur.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement. `addImageStep` and `iedReplace` call `autoRedact(step, false)` after upload (in the editor, `iedPush` is the same history entry as the replace — undo removes both). Editor button `data-act="redact"`, tip "ซ่อนข้อมูลอัตโนมัติ", disabled for GIF; calls `autoRedact(IED.step, true)` with `iedPush()` first, toasts "ซ่อนเพิ่ม N จุด" or "ไม่พบข้อมูลที่ต้องซ่อน", then `iedChanged()`. While waiting, the button shows busy and ignores clicks.
- [ ] **Step 4:** Run all five test files — all pass.
- [ ] **Step 5:** Commit `feat: auto-redact added images and editor button`.

### Task 6: Final check

- [ ] Run all test files; record counts.
- [ ] Ask the user to quit via tray "ออก", reopen, and try: record a short session typing an email, check blur and `•••`; paste a screenshot; editor button on an old guide; turn the switch off and confirm nothing is blurred.
- [ ] Update spec status line to "สร้างแล้ว รอผู้ใช้ทดสอบ" and commit.
