# Onboarding (sample guide + tours) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A first-time user finds a ready-made sample guide "ตัวอย่าง: เริ่มต้นใช้ StepCap" in the library and gets a short look-only tour on the home and guide-edit screens, so they can make and export a first guide alone.

**Architecture:** The sample guide is static files in `samples/getting-started/`, copied into storage once (`library.ensure_sample`, flag `sample_added` in settings.json) and again on demand (`POST /api/sample`). Tours are one small engine in a new `ui/tour.js` (`runTour` / `maybeTour`) with two data sets; "seen" lives in settings.json `tours_seen`. A dev script `samples/make_getting_started.py` regenerates the sample's screenshots from the app's own windows.

**Tech Stack:** Python 3.14 stdlib + existing deps (pywebview/WebView2, Pillow, tkinter), vanilla JS/CSS. No new libraries.

**Spec:** `docs/specs/2026-10-16-onboarding-design.md` (approved 2026-10-16). Tour copy and sample guide copy are fixed there (3.1 / 3.2): use them verbatim.

## Global Constraints

- Windows 11, Python 3.14, local only, no new libraries.
- All UI text Thai, light theme, everything inside the app window; follow `DESIGN.md` (tokens, `:focus-visible`, `activatable`, `toast` / `toastErr`).
- Sample title exactly `ตัวอย่าง: เริ่มต้นใช้ StepCap`; app `StepCap`; no `redact_pending`.
- Settings keys: `sample_added` (bool, page may NOT write it), `tours_seen` (list ⊆ `["home", "edit"]`, page may write it).
- Tests never click/type on the real desktop and use `STEPCAP_STORAGE` temp dirs; run as `.venv/Scripts/python.exe test_X.py`.
- Tour postponed (not shown, not marked seen) while recording, while `#redcover` exists, when `innerWidth < 760`, or when the first stop's target is missing; a stop whose target is missing is skipped.
- Tour keys: Enter = next, Esc = skip; Esc must not also reach other Esc handlers (record menu, image editor, popMenu).

## Review Focus

1. First-ever run where the storage folder doesn't exist yet: `ensure_sample` creates it and still copies (test in Task 1).
2. Window resized while a tour is open: the ring and box follow the target (test in Task 2).
3. Home re-renders while its tour is open (view toggle / status poll `refresh()`): still exactly one tour, not two (test in Task 2).
4. Sample guide renamed or deleted by the user: home tour skips stop 2 and shows "1/2" (test in Task 2).
5. Esc during a tour on the edit page with the record menu / a popMenu open: only the tour closes (test in Task 3).

---

### Task 1: Sample copy + settings keys + route

**Files:**
- Modify: `library.py` (DEFAULT_APP_SETTINGS, `_clean_settings`, new functions after `duplicate_guide`)
- Modify: `app.py` (`SAMPLE_DIR`, `_settings_ok`, `POST /api/sample` in `_post`, call in `main()`)
- Test: `test_library.py`, `test_app.py`

**Interfaces:**
- Produces:
  - `library.SAMPLE_TITLE = "ตัวอย่าง: เริ่มต้นใช้ StepCap"`
  - `library.TOURS = ("home", "edit")`
  - `library.add_sample(storage: Path, src: Path) -> str | None`: copies `src` to `storage/<new_id>`, rewrites guide.json with `id`, `created`=`updated`=`now_iso()`, `bookmarked: False`, drops `redact_pending`. Never raises (returns `None` on missing src / OSError / unreadable guide, leaving no half-made folder).
  - `library.ensure_sample(storage: Path, src: Path) -> str | None`: if `load_settings(storage)["sample_added"]` is false, `add_sample`, and on success `save_settings(storage, sample_added=True)`. Returns the new id or `None`. Creates `storage` if missing.
  - `DEFAULT_APP_SETTINGS` gains `"sample_added": False, "tours_seen": []`; `_clean_settings` drops non-bool `sample_added` and keeps only `tours_seen` names in `TOURS`.
  - `app.SAMPLE_DIR = HERE / "samples" / "getting-started"`
  - `POST /api/sample` -> `200 {"id": <id>}` or `500 "no sample"`.

- [ ] **Step 1: Write the failing tests (test_library.py)**

```python
def _fake_sample(root: Path) -> Path:
    src = root / "src"; src.mkdir()
    (src / "a.png").write_bytes(_img_bytes("PNG"))
    (src / "guide.json").write_text(json.dumps({"title": L.SAMPLE_TITLE, "app": "StepCap",
        "redact_pending": True, "steps": [{"id": "s1", "kind": "click", "text": "x", "image": "a.png"}]},
        ensure_ascii=False), encoding="utf-8")
    return src

def test_ensure_sample_once():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d); src = _fake_sample(root); st = root / "store"  # does not exist yet
        gid = L.ensure_sample(st, src)
        g = L.read_guide(st / gid)
        assert g["title"] == L.SAMPLE_TITLE and "redact_pending" not in g and g["created"]
        assert (st / gid / "a.png").is_file()
        assert L.load_settings(st)["sample_added"] is True
        assert L.ensure_sample(st, src) is None and len(list_guides(st)) == 1
        trash_guide(st, gid)
        assert L.ensure_sample(st, src) is None and list_guides(st) == []  # deleted stays deleted

def test_ensure_sample_failure_retries_later():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d) / "store"
        assert L.ensure_sample(st, Path(d) / "missing") is None
        assert L.load_settings(st)["sample_added"] is False
        assert not st.exists() or not any(p.is_dir() for p in st.iterdir())

def test_add_sample_makes_new_copies():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d); src = _fake_sample(root); st = root / "store"; st.mkdir()
        a, b = L.add_sample(st, src), L.add_sample(st, src)
        assert a and b and a != b and len(list_guides(st)) == 2

def test_onboarding_settings_cleaned():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        assert L.save_settings(st, tours_seen=["home", "nope"], sample_added="yes")["tours_seen"] == ["home"]
        assert L.load_settings(st)["sample_added"] is False
```

(`import library as L` / `json` at the top if not already imported.)

- [ ] **Step 2: Run** `.venv/Scripts/python.exe test_library.py` — Expected: the 4 new tests FAIL (AttributeError `SAMPLE_TITLE` / `ensure_sample`).

- [ ] **Step 3: Implement** the library interfaces above. Copy with `shutil.copytree` into `storage / new_id(storage)`; on any exception after the copy started, `shutil.rmtree(dst, ignore_errors=True)` and return `None`.

- [ ] **Step 4: Run** `.venv/Scripts/python.exe test_library.py` — Expected: all pass.

- [ ] **Step 5: Write the failing app test (test_app.py)**, added to `TESTS` after `test_library_routes`. The real sample folder arrives in Task 4, so the route is checked both ways:

```python
def test_sample_route_and_settings():
    titles = lambda: [g["title"] for g in get("/api/guides")].count(library.SAMPLE_TITLE)
    if (HERE / "samples" / "getting-started" / "guide.json").is_file():
        n = titles()
        assert n == 1  # copied once at first launch
        assert get(f"/api/guide/{post('/api/sample')['id']}")["title"] == library.SAMPLE_TITLE
        assert titles() == n + 1
    else:
        assert post("/api/sample") == 500
    post("/api/settings", {"tours_seen": ["home"]})
    assert get("/api/settings")["tours_seen"] == ["home"]
    assert post("/api/settings", {"tours_seen": ["bogus"]}) == 400
    assert post("/api/settings", {"sample_added": False}) == 400
```

- [ ] **Step 6: Implement** in `app.py`:
  - `SAMPLE_DIR`
  - `_settings_ok` check `"tours_seen": lambda v: strs(v) and set(v) <= set(library.TOURS)`
  - the route in `_post` next to `/api/pages`, returning `self._json({"id": gid})` or `self._send(500, "no sample", "text/plain")`
  - in `main()` after `ensure_app_icon`: `try: library.ensure_sample(STORAGE, SAMPLE_DIR) except Exception: pass` (a failure must never stop the app)

- [ ] **Step 7: Run** `.venv/Scripts/python.exe test_app.py` and `test_library.py` — Expected: all pass.

- [ ] **Step 8: Commit** `feat: sample guide copy, onboarding settings, /api/sample`

---

### Task 2: Tour engine, home tour, home intro, settings card

**Files:**
- Create: `ui/tour.js`
- Modify: `ui/index.html` (tour CSS after the toast block; `<script src="ui/tour.js">` after `common.js`)
- Modify: `ui/shell.js` (`renderHome`, `drawGuides` adds `el.dataset.id`, `renderSettings` card, remove `FIRST_RUN`)
- Modify: `ui/common.js` (`NAV_MSG` entries become `[text, kind]`; add `sample: ["เพิ่มคู่มือตัวอย่างแล้ว", "ok"]`)
- Test: `test_render.py`

**Interfaces:**
- Consumes:
  - settings `tours_seen`, `/api/settings` (Task 1)
  - `/api/status` `.recording`, `#redcover`
  - `library.SAMPLE_TITLE` text, from the card's `.title` / `.r-title`
- Produces (`ui/tour.js`):
  - `const TOURS = {home: [...], edit: [...]}`. Each stop is `{target: () => Element | null, title, text}`, with copy from spec 3.2.
  - `async function maybeTour(name)`:
    - checks every postpone rule (Global Constraints)
    - shows nothing if a tour is already open (`TOUR_OPEN`)
    - runs `runTour(name, stops)` and, when it closes, POSTs `tours_seen` with `name` added
  - `function runTour(name, stops) -> Promise<void>` resolves on skip / finish / Esc. It renders:
    - `.tour-ring`: fixed on the target rect + 4px, `box-shadow: 0 0 0 9999px rgba(17,24,39,.45)`, 2px `var(--focus)` outline, radius 8
    - `.tour-shade`: transparent full-window layer that eats clicks
    - `.tour-box[role=dialog][aria-modal=true]`, 320px wide, white, radius 12, dialog shadow, containing:
      - `.tour-title`
      - `.tour-text`
      - `.tour-count` showing `"i/N"`
      - buttons `[data-t=skip] ข้าม`, `[data-t=back] ย้อนกลับ` (disabled on stop 1), `[data-t=next] ถัดไป` (`เสร็จสิ้น` on the last stop)
  - `runTour` behaviour:
    - `scrollIntoView({block: "center"})` on each target
    - box goes below the target if it fits, else above, clamped 12px from the edges
    - re-places on `resize` / `scroll`
    - Enter = next, Esc = skip, handled in the **capture** phase with `stopPropagation`
    - focus stays in the box (Tab cycles) and returns to the previously focused element on close

- [ ] **Step 1: Write the failing tests (test_render.py)**.
  - In `seed()`, write `settings.json` = `{"tours_seen": ["home", "edit"], "sample_added": true}` so existing tests never see a tour.
  - Add the helper `_reset_tours()` = `js("await post('/api/settings', {tours_seen: []});")`.
  - Add these tests to `TESTS`:

```python
def test_home_tour_first_time_only():
    page("page=home"); _reset_tours()
    js("await post('/api/sample');")
    page("page=home")
    got = js(_until("document.querySelector('.tour-box')") +
             "const c = () => document.querySelector('.tour-count').textContent; const a = c();"
             "document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));"
             "const b = c(); const inBox = document.querySelector('.tour-box').contains(document.activeElement);"
             "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));"
             "await new Promise(r => setTimeout(r, 400));"
             "return [a, b, inBox, !!document.querySelector('.tour-box'), (await getJSON('/api/settings')).tours_seen];")
    assert got == ["1/3", "2/3", True, False, ["home"]], got
    page("page=home")
    assert js("await new Promise(r => setTimeout(r, 1200)); return !!document.querySelector('.tour-box');") is False

def test_home_tour_skips_missing_sample_and_follows_resize():
    page("page=home"); _reset_tours()
    js("for (const g of await getJSON('/api/guides')) if (g.title.startsWith('ตัวอย่าง:'))"
       " await post('/api/guide/' + encodeURIComponent(g.id) + '/delete');")
    page("page=home")
    got = js(_until("document.querySelector('.tour-box')") +
             "refresh(); await new Promise(r => setTimeout(r, 600));"
             "return [document.querySelector('.tour-count').textContent, document.querySelectorAll('.tour-box').length];")
    assert got == ["1/2", 1], got
    CTX["win"].resize(1000, 700); time.sleep(0.8)
    got = js("const t = document.getElementById('recbtn').getBoundingClientRect(),"
             " r = document.querySelector('.tour-ring').getBoundingClientRect();"
             "return Math.abs(r.left - (t.left - 4)) < 2 && Math.abs(r.top - (t.top - 4)) < 2;")
    assert got is True
    js("document.querySelector('[data-t=skip]').click();")

def test_tour_postponed():
    page("page=home"); _reset_tours()
    CTX["win"].resize(700, 700); page("page=home")  # narrow
    assert js("await new Promise(r => setTimeout(r, 1200)); return !!document.querySelector('.tour-box');") is False
    page("page=home")
    got = js("redactCover([0, 0]); await maybeTour('home'); const a = !!document.querySelector('.tour-box');"
             "redactCover(null); const f = window.fetch; window.fetch = async (u, o) => String(u).startsWith('/api/status')"
             " ? new Response(JSON.stringify({recording: true})) : f(u, o);"
             "await maybeTour('home'); window.fetch = f; return [a, !!document.querySelector('.tour-box'),"
             " (await getJSON('/api/settings')).tours_seen];")
    assert got == [False, False, []], got

def test_settings_replay_and_add_sample():
    page("page=settings")
    js(_until("document.getElementById('replaytour')") + "document.getElementById('replaytour').click();")
    time.sleep(2.5); CTX["win"].evaluate_js(_B64)
    assert js(_until("document.querySelector('.tour-box')") + "return location.search.includes('page=home');")
    js("document.querySelector('[data-t=skip]').click(); await new Promise(r => setTimeout(r, 300));")
    page("page=settings")
    CTX["win"].evaluate_js("document.getElementById('addsample').click(); 1")
    time.sleep(2.5); CTX["win"].evaluate_js(_B64)
    assert js("return [location.search.includes('guide='), STATE.title];")[1].startswith("ตัวอย่าง:")

def test_home_has_no_first_run_list():
    page("page=home")
    assert js(_until("document.querySelector('.intro')") + "return document.querySelector('.intro ol');") is None
```

(`test_tour_postponed` creates its narrow window via `page()` after `resize`. If `page()` recreates the window at 1200 wide, add an optional `width` parameter to `page()` instead and use `page("page=home", width=700)`.)

- [ ] **Step 2: Run** `.venv/Scripts/python.exe test_render.py` — Expected: the 5 new tests FAIL (no `.tour-box` / no `#replaytour`); all old tests still pass.

- [ ] **Step 3: Implement** `ui/tour.js` per the Interfaces block, the CSS in `index.html`, and the script tag.

- [ ] **Step 4: Wire the home page and settings** in `shell.js`:
  - `renderHome`:
    - remove `FIRST_RUN` and its use
    - after `drawGuides`, call `if (PAGE === "home") maybeTour("home")`
  - home stop 2's target is the first `.card` / `.row` whose `.title` / `.r-title` text starts with `"ตัวอย่าง:"`
  - `renderSettings` gets a `.set` card `<h3>การแนะนำการใช้งาน</h3>` with:
    - `#replaytour`: `busy`, POST `tours_seen: []`, then `go("home")`
    - `#addsample`: `busy`, POST `/api/sample`, then `nav({guide: id, mode: "view", msg: "sample"})`, or `toastErr(FAILED)`
  - `boot()` uses `NAV_MSG[m]` as `[text, kind]` (`kind === "err"` → `toastErr`, else `toast`)

- [ ] **Step 5: Run** `.venv/Scripts/python.exe test_render.py` — Expected: all pass.

- [ ] **Step 6: Commit** `feat: tour engine, home tour, onboarding settings card`

---

### Task 3: Edit-page tour

**Files:**
- Modify: `ui/tour.js` (`TOURS.edit`), `ui/guide.js` (`editPage` calls `maybeTour("edit")` after `renderSteps()`)
- Test: `test_render.py` (seed adds guide `textonly`: two `click` steps with `image: null`)

**Interfaces:**
- Consumes: `maybeTour`, `runTour` (Task 2)
- Produces: `TOURS.edit` targets, in order:
  1. `.step .stext`
  2. `.step .sbtns`
  3. `.step .etools:not([hidden]) .ed`
  4. `.etb`
  5. `#exp`

  Copy is from spec 3.2.

- [ ] **Step 1: Write the failing tests**

```python
def test_edit_tour_stops_and_skips():
    page("guide=noise&mode=edit"); _reset_tours(); page("guide=noise&mode=edit")
    got = js(_until("document.querySelector('.tour-box')") +
             "const c = () => document.querySelector('.tour-count').textContent, seen = [c()];"
             "for (let i = 0; i < 4; i++) { document.querySelector('[data-t=next]').click(); seen.push(c()); }"
             "const last = document.querySelector('[data-t=next]').textContent.trim();"
             "document.querySelector('[data-t=next]').click(); await new Promise(r => setTimeout(r, 400));"
             "return [seen, last, (await getJSON('/api/settings')).tours_seen];")
    assert got == [["1/5", "2/5", "3/5", "4/5", "5/5"], "เสร็จสิ้น", ["edit"]], got
    _reset_tours(); page("guide=textonly&mode=edit")
    assert js(_until("document.querySelector('.tour-box')") +
              "const n = document.querySelector('.tour-count').textContent;"
              "document.querySelector('[data-t=skip]').click(); return n;") == "1/4"

def test_tour_esc_only_closes_tour():
    page("guide=noise&mode=edit"); _reset_tours(); page("guide=noise&mode=edit")
    got = js(_until("document.querySelector('.tour-box')") +
             "popMenu(document.getElementById('exp'), [{label: 'x', run() {}}]);"
             "document.querySelector('.tour-box button').focus();"
             "document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));"
             "return [!!document.querySelector('.tour-box'), !!document.querySelector('.menu-pop')];")
    assert got == [False, True], got
    js("closePopMenu();")
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe test_render.py` — Expected: the 2 new tests FAIL.
- [ ] **Step 3: Implement** `TOURS.edit` and the `editPage` call.
- [ ] **Step 4: Run** `.venv/Scripts/python.exe test_render.py` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: edit-page tour`

---

### Task 4: Sample guide content + generator

**Files:**
- Create: `samples/make_getting_started.py`
- Create (generated): `samples/getting-started/guide.json`, `step-01.png` … `step-07.png`, `app_icon.png`
- Test: `test_library.py`

**Interfaces:**
- Consumes:
  - `app.py` launched like `test_render.launch()` on a temp storage
  - `overlay.Overlay().show_panel(work_rect, get_state, on_pause, on_stop)`
- Produces: the files `app.SAMPLE_DIR` copies (Task 1). The guide.json is shaped like a recorder guide:
  - `title` = `SAMPLE_TITLE`, `app` = `"StepCap"`, `app_icon` = `"app_icon.png"`
  - `settings` = `DEFAULT_SETTINGS`
  - 10 steps in spec 3.1's order and copy:
    - note
    - click / click / image / click / image / click / click
    - note, note
  - each step has a stable id `s01`… and click steps carry one marker `{x, y, size: 44, color: "#FB923C", shape: "circle"}` at the clicked control's centre

- [ ] **Step 1: Write the failing test (test_library.py)**

```python
def test_repo_sample_guide():
    from library import SAMPLE_TITLE, read_guide, image_kind
    src = Path(__file__).parent / "samples" / "getting-started"
    g = read_guide(src)
    assert g and g["title"] == SAMPLE_TITLE and "redact_pending" not in g
    kinds = [s["kind"] for s in g["steps"]]
    assert kinds.count("note") == 3 and len(kinds) == 10
    for s in g["steps"]:
        if s["image"]:
            data = (src / s["image"]).read_bytes()
            assert image_kind(data) == "png"
            w, h = Image.open(src / s["image"]).size
            assert all(0 <= m["x"] <= w and 0 <= m["y"] <= h for m in s["markers"])
    assert [len(s["markers"]) for s in g["steps"] if s["kind"] == "click"] == [1, 1, 1, 1, 1]
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe test_library.py` — Expected: `test_repo_sample_guide` FAILs (no folder).

- [ ] **Step 3: Write `samples/make_getting_started.py`** (run: `.venv/Scripts/python.exe samples/make_getting_started.py`).
  - **Storage:** seed a temp storage with 3 fake guides:
    - "ระบบลางาน - 16 ต.ค. 2569 09:12"
    - "ตั้งค่าอีเมล Outlook - 15 ต.ค. 2569 14:30"
    - "เบิกค่าเดินทาง - 14 ต.ค. 2569 10:05"
    - each with 3 steps, plain PIL-drawn images, and no real data
    - `settings.json` = `{"tours_seen": ["home", "edit"], "sample_added": true}`
  - **Window:** launch `app.py` on it, then open a pywebview window at 1280×820.
  - **Web shots:** capture only the web view, with `CoreWebView2.CapturePreviewAsync(Png, stream)` through `win.native.Invoke` (never a screen grab). Marker coordinates are `getBoundingClientRect()` centres × `devicePixelRatio`.
    - `step-01`: home, marker on `#recbtn`
    - `step-02`: record menu open, marker on `#startrec`
    - `step-05`: edit page of "ระบบลางาน"
    - `step-06`: same page, marker on the first `.ed`
    - `step-07`: export menu open, marker on `#exp`
  - **Panel shots:** `Overlay().show_panel` with fake state, then `PrintWindow(hwnd, hdc, 2)` of the panel window only.
    - fake state is `{"recording": True, "paused": False, "steps": [...3 fake steps about ระบบลางาน...], "pending": None}`
    - `step-03`: the panel, no marker
    - `step-04`: the same panel, marker on the "หยุดบันทึก" button centre from its Tk geometry
  - **Icon:** `app_icon.png` is 64×64, drawn like `app.ensure_app_icon`.
  - **Finish:** write `guide.json`, then tear everything down and delete the temp storage.

- [ ] **Step 4: Run the script, then look at every PNG** (Read tool) — each must show only StepCap with fake data, Thai rendered, and the marker on the right control. Fix and re-run until they all do.

- [ ] **Step 5: Run** `.venv/Scripts/python.exe test_library.py` and `test_app.py` (`test_sample_route_and_settings` now takes its real-sample branch: one sample at launch, `/api/sample` adds a second) — Expected: all pass.

- [ ] **Step 6: Commit** `feat: getting-started sample guide and its generator` (check the diff holds no screenshots of anything but StepCap).

---

### Task 5: Whole-branch check

- [ ] **Step 1:** Run every suite except `test_windows.py`: `test_steps`, `test_library`, `test_exporters`, `test_redact`, `test_app`, `test_render` — Expected: all pass.
- [ ] **Step 2:** Open the sample guide with `page("guide=<id>")` in a scratch script, export HTML via `buildExportHtml`, and confirm it has 7 numbered steps and 7 `<img>`.
- [ ] **Step 3:** In `README.md` "วิธีใช้แบบสั้น", add one line: the first launch brings a sample guide and a short tour, and the tour can be replayed from ตั้งค่า.
- [ ] **Step 4:** Update the spec status line to "สร้างแล้ว รอผู้ใช้ทดสอบจริง".
- [ ] **Step 5:** Commit `docs: onboarding in README, spec status`.
