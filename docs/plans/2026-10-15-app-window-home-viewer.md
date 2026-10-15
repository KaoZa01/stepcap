# StepCap pieces 0+1 — in-app window, Scribe-like home, view/edit mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Edge `--app` window with StepCap's own pywebview window. The window has a Scribe-style light home (sidebar, cards, trash, settings) and a guide page with a view mode and an edit mode with a floating toolbar.

**Architecture:**
- The existing token-gated `127.0.0.1` HTTP server stays the only bridge between page and Python. pywebview just loads its URL in a WinForms/WebView2 window on the main thread; the tray and the tk overlays run on their own threads.
- A new pure module `library.py` owns everything about guides on disk: defaults for old guides, ids, atomic writes, list/search, trash, duplicate, settings and relative time. `app.py` becomes routing glue over it.
- `editor.html` is split into `ui/index.html` + three scripts. `renderGuide` stays self-contained so export reuses the exact view-mode rendering.

**Tech Stack:**
- Python 3.14 (`.venv`), pywebview 6.x + pythonnet 3.x (new), comtypes, Pillow, pystray, tkinter.
- Vanilla HTML/CSS/JS, no build step.

**Spec:** `docs/specs/2026-10-15-app-window-home-viewer-design.md` (Thai; approved 2026-10-15). Section numbers below (§3, §6 …) refer to it.

## Global Constraints

- **Platform and stack:**
  - Windows 11 only; Python 3.14 in the existing `.venv`.
  - Allowed new dependency: `pywebview` (plus `pythonnet` and what it pulls in). No other UI framework (no PySide6, no Electron).
- **Copy and look:**
  - Every user-visible string is Thai. Button copy pinned here:
    - Edit → `แก้ไข`
    - Done → `เสร็จสิ้น`
    - Export → `ส่งออก`
    - New recording → `+ บันทึกใหม่`
  - Light theme always: no `prefers-color-scheme` dark rules anywhere.
- **No browser windows:** No browser window may ever open (no Edge `--app`, no `webbrowser`, no `<a download>`).
- **Local only and token gating:**
  - Server binds `127.0.0.1` only.
  - Every `/api/*`, `/img/*` and `/` request requires the token. Only `/ui/<file>` static source is ungated.
- **Storage layout:**
  - Storage is `Documents\StepCap\`. `STEPCAP_STORAGE` env var overrides it, for tests only.
  - Folders starting with `_` (`_tmp`, `_trash`, `_browser`, `_app.ico`, `_run.json`) are never guides. `_browser` is left alone.
- **Old guides:**
  - Old guides must open with defaults filled in.
  - Reading a guide never rewrites its file; only an explicit save/rename/bookmark/trash writes.
- **Notes (§6):** no number, not counted in step count, not in the TOC — in view mode, edit mode and export alike.
- **Defaults:** default click color `#FB923C`. Hotkeys stay `Ctrl+Alt+R` (start/stop) and `Ctrl+Alt+P` (pause).
- **Capture and self-recording:**
  - StepCap's own window, panel and overlays never appear in guide images.
  - Clicks/typing inside StepCap are never recorded.
- **Close vs quit:**
  - X hides to tray and never quits, even while recording.
  - Tray `ออก` stops and saves a running recording first.
- **Never store password text** (existing rule, keep it).
- **Tests:**
  - Tests use harmless input only: no synthesized clicks or typing on the user's desktop.
  - `test_steps.py` and `test_windows.py` must keep passing.
- **Commands:** run with `cd /d/dev/stepcap && .venv/Scripts/python.exe -X utf8 <file>` (bash). `-X utf8` is required because the console is cp874.

## Review Focus

1. **An old guide with missing fields opens with defaults and its file is byte-identical afterwards.** Example: no `created`, steps without `markers`/`crop`, `image: null`. Covered by `test_normalize_minimal_old_guide` (Task 1) and `test_old_guide_untouched` (Task 3).
2. **A corrupt or half-written `guide.json` next to good guides is skipped, not shown as an error, not deleted, and the rest still list.** Covered by `test_corrupt_guide_skipped` (Task 1).
3. **Pressing X while recording hides the window; the process and the recording keep running, and the window comes back on demand.** Covered by `test_close_hides_while_recording` (Task 3).
4. **A saved default monitor that is no longer plugged in falls back to the primary instead of crashing or recording nothing.** Covered by `test_monitor_index_fallback` (Task 2).
5. **Two guides created in the same second, a copy of a copy, or restoring a trashed guide whose id is taken never overwrite a folder.** Covered by `test_new_id_unique` and `test_restore_refuses_taken_id` (Task 1).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `library.py` | Guides on disk: defaults, ids, atomic JSON, list/search, trash/restore/purge, duplicate, meta, settings, relative time. Pure Python; no Windows or UI imports. | Create |
| `test_library.py` | Plain-assert tests for `library.py` on temp dirs. | Create |
| `recorder.py` | Records exe path → `app`/`app_icon` on new guides; ids via `library.new_id`. Own-window check by PID only. Adds `find_main_window`, `set_capture_excluded`, `extract_icon`, `monitor_index`; `STEPCAP_STORAGE`. | Modify |
| `app.py` | pywebview window on main thread, tray thread, X→hide, single instance, window icon, capture exclusion while recording, all HTTP routes over `library`, native Save As. | Modify |
| `test_app.py` | End-to-end: launches `app.py` on a temp storage and drives it over HTTP + Win32 queries. | Create |
| `test_windows.py` | Add icon/`_write_guide` and capture-exclusion checks. | Modify |
| `test_steps.py` | Add `monitor_index` test. | Modify |
| `requirements.txt` | `comtypes`, `Pillow`, `pystray`, `pywebview`. | Create |
| `ui/index.html` | Markup skeleton, all CSS (shell CSS + `<style id="rg-css">` for rendered guides), loads scripts. | Create |
| `ui/common.js` | `api`, `esc`, `ICON`, `nav`, `uiPrompt`, `uiConfirm`, `toast`, status polling + `followNewGuide`, boot router. | Create |
| `ui/shell.js` | Sidebar, top bar + record menu, recording banner, Home, คู่มือทั้งหมด, ถังขยะ, ตั้งค่า, card/list rendering. | Create |
| `ui/guide.js` | `drawStepCanvas`, `renderGuide`, view mode, edit mode (step cards, image editor, toolbar, grid), `exportGuide`. | Create |
| `editor.html` | — | Delete (Task 4) |

---

### Task 1: `library.py` — guides on disk

**Files:**
- Create: `library.py`
- Test: `test_library.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces (all `storage: Path`; every `gid` validated with `safe_id` inside each function, returning `False`/`None` when invalid):
  - Constants:
    - `DEFAULT_SETTINGS = {"toc": False, "step_count": False, "created": False, "updated": False, "layout": "linear", "click_color": "#FB923C"}`
    - `DEFAULT_APP_SETTINGS = {"monitor": None, "view": "grid"}`
  - Name checks:
    - `safe_name(name: str) -> bool`: the current `_safe` rule (non-empty, no `/`, `\`, `..`).
    - `safe_id(gid: str) -> bool`: `safe_name` and not starting with `_`.
  - Low-level helpers:
    - `now_iso() -> str` (`%Y-%m-%dT%H:%M:%S`, local time)
    - `new_id(storage: Path, now: float | None = None) -> str`
    - `write_json_atomic(path: Path, data: dict) -> None`
    - `normalize(g: dict) -> dict`
    - `step_count(g: dict) -> int`
    - `read_guide(folder: Path) -> dict | None`, which returns the normalized guide.
  - Guide operations:
    - `list_guides(storage, q: str = "", bookmarked_only: bool = False, now: datetime | None = None) -> list[dict]`. Each summary has keys `id, title, created, updated, count, app, icon, bookmarked, ago`. `icon` is a bool: `app_icon` is set and the file exists.
    - `save_guide(storage, gid, data: dict) -> bool`
    - `update_meta(storage, gid, title: str | None = None, bookmarked: bool | None = None) -> bool`
    - `duplicate_guide(storage, gid) -> str | None`
  - Trash:
    - `trash_guide(storage, gid) -> bool`
    - `list_trash(storage, now=None) -> list[dict]`, with keys `id, title, deleted, ago, count`.
    - `restore_guide(storage, gid) -> bool`
    - `purge_guide(storage, gid, recycle: Callable[[Path], None]) -> bool`
    - `empty_trash(storage, recycle) -> int`
  - App settings:
    - `load_settings(storage) -> dict`
    - `save_settings(storage, **changes) -> dict`
  - `rel_time(iso: str, now: datetime) -> str`

- [ ] **Step 1: Write the failing tests** in `test_library.py`. Copy the `__main__` runner from `test_steps.py`. Each test makes its own `tempfile.TemporaryDirectory()` and seeds folders with a helper `_seed(storage, gid, **fields)` that writes `{"id": gid, "title": ..., "created": ..., "steps": [...]}`.

```python
def test_rel_time():
    now = datetime(2026, 10, 15, 12, 0, 0)
    assert rel_time("2026-10-15T11:59:30", now) == "เมื่อสักครู่"
    assert rel_time("2026-10-15T11:55:00", now) == "5 นาทีที่แล้ว"
    assert rel_time("2026-10-15T09:00:00", now) == "3 ชั่วโมงที่แล้ว"
    assert rel_time("2026-10-13T12:00:00", now) == "2 วันที่แล้ว"
    assert rel_time("2026-05-15T12:00:00", now) == "5 เดือนที่แล้ว"
    assert rel_time("2024-10-15T12:00:00", now) == "2 ปีที่แล้ว"
    assert rel_time("2026-10-15T12:00:05", now) == "เมื่อสักครู่"   # clock skew
    assert rel_time("", now) == "" and rel_time("garbage", now) == ""

def test_normalize_minimal_old_guide():
    old = {"id": "20261015-153012", "title": "explorer - 15 ต.ค. 2569 15:30",
           "steps": [{"id": "a", "kind": "click", "text": "x"}, {"id": "b", "kind": "note", "text": "n"}]}
    before = json.dumps(old, sort_keys=True)
    g = normalize(old)
    assert json.dumps(old, sort_keys=True) == before          # input not mutated
    assert g["created"] == "" and g["updated"] == "" and g["bookmarked"] is False
    assert g["app"] == "explorer" and g["app_icon"] is None
    assert g["settings"] == DEFAULT_SETTINGS
    assert g["steps"][0]["markers"] == [] and g["steps"][0]["crop"] is None and g["steps"][0]["image"] is None
    assert normalize(g) == g                                  # idempotent
    assert normalize({"id": "x", "title": "no dash", "steps": []})["app"] == ""
    assert normalize({**old, "settings": {"toc": True}})["settings"]["toc"] is True
    assert normalize({**old, "settings": {"toc": True}})["settings"]["click_color"] == "#FB923C"

def test_step_count_ignores_notes():
    assert step_count({"steps": [{"kind": "click"}, {"kind": "note"}, {"kind": "type"}]}) == 2

def test_corrupt_guide_skipped():
    # seed "a" valid, "b" with guide.json = '{"id": "b", "ti' (truncated), "_tmp" and "_trash" dirs, a stray file
    # list_guides returns only "a"; folder "b" and its file still exist afterwards

def test_list_search_and_order():
    # seed "20261001-100000" title "Notepad - เก่า", step text "บันทึกไฟล์"
    # seed "20261010-100000" title "Excel - ใหม่", bookmarked True
    ids = [s["id"] for s in list_guides(st)]
    assert ids == ["20261010-100000", "20261001-100000"]                  # newest created first
    assert [s["id"] for s in list_guides(st, q="บันทึกไฟล์")] == ["20261001-100000"]   # step text
    assert [s["id"] for s in list_guides(st, q="EXCEL")] == ["20261010-100000"]       # casefold title
    assert [s["id"] for s in list_guides(st, bookmarked_only=True)] == ["20261010-100000"]
    s = list_guides(st)[1]
    assert s["count"] == 1 and s["app"] == "Notepad" and s["icon"] is False and s["ago"] != ""

def test_trash_restore_purge():
    # seed "g1"; trash_guide -> True; (st/"g1") gone; (st/"_trash"/"g1"/"guide.json") has "deleted"
    # list_guides(st) == [] and list_guides(st, q=<its title>) == []
    # list_trash(st)[0]["id"] == "g1"
    # restore_guide -> True; "deleted" key gone from file; list_guides has g1
    # trash again; purge_guide(st, "g1", recycle=calls.append) -> True and calls == [st/"_trash"/"g1"]
    # empty_trash with 2 trashed -> returns 2, recycle called twice
    # trash_guide(st, "_trash") is False; trash_guide(st, "../x") is False; trash_guide(st, "missing") is False

def test_restore_refuses_taken_id():
    # seed g1, trash it, seed a new live "g1"; restore_guide -> False; both folders still exist

def test_new_id_unique():
    t = time.mktime((2026, 10, 15, 12, 0, 0, 0, 0, -1))
    assert new_id(st, t) == "20261015-120000"
    (st / "20261015-120000").mkdir()
    (st / "_trash" / "20261015-120000-2").mkdir(parents=True)
    assert new_id(st, t) == "20261015-120000-3"

def test_duplicate_and_meta():
    # seed "g1" title "A", bookmarked True, one step with image "s1.png" (write a dummy file)
    new = duplicate_guide(st, "g1")
    # new != "g1"; new folder has s1.png; its guide: title "A (สำเนา)", id == new, bookmarked False,
    # created == updated (both now_iso-shaped); duplicate of the copy -> "A (สำเนา) (สำเนา)", a third distinct id
    # update_meta(st, "g1", bookmarked=False) -> True; file's updated unchanged
    # update_meta(st, "g1", title="B") -> True; title B, updated changed
    # update_meta(st, "g1", title="   ") is False

def test_save_guide_sets_id_and_updated_atomically():
    # save_guide(st, "g1", {"id": "evil", "title": "T", "steps": []}) -> True; file id == "g1"; updated set
    # no "*.tmp" left in folder; save_guide(st, "g1", {"steps": "nope"}) is False; save_guide(st, "missing", {...}) is False

def test_settings_roundtrip():
    assert load_settings(st) == DEFAULT_APP_SETTINGS                     # no file yet
    save_settings(st, view="list", bogus=1)
    assert load_settings(st) == {"monitor": None, "view": "list"}        # unknown keys dropped
    (st / "settings.json").write_text("{bad", encoding="utf-8")
    assert load_settings(st) == DEFAULT_APP_SETTINGS                     # corrupt -> defaults
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -X utf8 test_library.py`
Expected: `ModuleNotFoundError: No module named 'library'`

- [ ] **Step 3: Implement `library.py`.** Each rule the tests leave open is pinned here:
  - **`normalize`** returns a new dict:
    - `created`: the existing value, or `""`.
    - `updated`: `updated or created`.
    - `bookmarked`: default `False`.
    - `app`: the existing value, or the title text before the first `" - "`, or `""`.
    - `app_icon`: default `None`.
    - `settings`: `{**DEFAULT_SETTINGS, **(g.get("settings") or {})}`.
    - Each step becomes `{"image": None, "crop": None, "markers": [], **step}`.
  - **`list_guides`:**
    - Iterates `storage.iterdir()`, skipping non-dirs and names failing `safe_id`.
    - Calls `read_guide`; `None` is skipped.
    - Summary `id` is the folder name.
    - Sorts by `(created, id)` descending.
    - `q` is `strip().casefold()` matched against the title and every step `text`.
    - `ago = rel_time(updated, now or datetime.now())`.
  - **Writes:**
    - `write_json_atomic`: `ensure_ascii=False, indent=2`, write `path.with_name(path.name + ".tmp")`, then `os.replace`.
    - `trash_guide`, `restore_guide`, `duplicate_guide` and `update_meta` load the raw JSON (not normalized) and change only their fields.
    - `trash_guide` still moves a folder whose JSON is unreadable; it skips the `deleted` write.
  - **`rel_time` thresholds:** `<60s`, `<60m`, `<24h`, `<30d`, `<365d` (months = days // 30), else years = days // 365. Negative → `เมื่อสักครู่`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -X utf8 test_library.py`
Expected: `11/11 passed`

- [ ] **Step 5: Commit**

```bash
git add library.py test_library.py
git commit -m "feat: library module for guides on disk (defaults, trash, search, ids)"
```

---

### Task 2: recorder — app icon, PID-only self filter, main-window helpers

**Files:**
- Create: `requirements.txt`
- Modify: `recorder.py`
- Test: `test_steps.py`, `test_windows.py`

**Interfaces:**
- Consumes:
  - `library.new_id`, `library.now_iso`, `library.write_json_atomic`, `library.DEFAULT_SETTINGS`.
  - `recorder.py` imports `library` at the top of the Windows-glue section.
- Produces:
  - Pure section:
    - `monitor_index(monitors: list[dict], name: str | None) -> int`: the index whose `"name"` equals `name`, else the primary's index, else `0`.
    - `StepBuilder.add_click(kind, name, noun, app, image=None, marker=None, exe: str = "") -> dict`: the step gains `"exe"`.
  - Windows glue:
    - `window_info(hwnd) -> tuple[str, str, str]`: `(title, app stem, exe full path)`; the path is `""` if unknown.
    - `HOST_APPS = {"ApplicationFrameHost", "StartMenuExperienceHost"}`
    - `extract_icon(exe: str, out: Path) -> bool`
    - `is_own_window(hwnd) -> bool`: PID only.
    - `find_main_window(title: str = APP_TITLE) -> HWND | None`: a top-level window of this PID with exactly that title, visible or hidden.
    - `set_capture_excluded(hwnd, on: bool) -> bool`
  - `default_storage()` honors `STEPCAP_STORAGE`.
  - New guides from `Recorder._write_guide` carry `updated, bookmarked, app, app_icon, settings`, and their steps have no `app`/`exe`.
- Removes: `_is_app_title`, `find_app_window`, `foreground_info` (unused). Superseded by the PID check and `find_main_window`.

- [ ] **Step 1: Install dependencies and probe the pywebview API**

Create `requirements.txt` with lines `comtypes`, `Pillow`, `pystray`, `pywebview`. Then run:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -c "import webview, clr; print(webview.__version__ if hasattr(webview,'__version__') else 'ok', webview.FileDialog.SAVE)"
```

Expected: the install succeeds and the probe prints a version (or `ok`) followed by a `FileDialog.SAVE` value.
- If `webview.FileDialog` is missing, use `webview.SAVE_DIALOG` everywhere this plan says `webview.FileDialog.SAVE`.

- [ ] **Step 2: Write the failing tests**

In `test_steps.py`:

```python
def test_monitor_index_fallback():
    mons = [{"index": 0, "name": r"\\.\DISPLAY1", "primary": False},
            {"index": 1, "name": r"\\.\DISPLAY2", "primary": True}]
    assert monitor_index(mons, r"\\.\DISPLAY1") == 0
    assert monitor_index(mons, r"\\.\DISPLAY9") == 1   # unplugged -> primary
    assert monitor_index(mons, None) == 1
    assert monitor_index([{"index": 0, "name": "x", "primary": False}], None) == 0
```

In `test_windows.py`:

```python
def test_write_guide_fields_and_icon():
    with tempfile.TemporaryDirectory() as d:
        rec = recorder.Recorder(Path(d))
        g = rec._write_guide([{"id": "s1", "kind": "click", "text": "t", "app": "python",
                               "exe": sys.executable, "image": None, "crop": None, "markers": []}])
        disk = json.loads((Path(d) / g["id"] / "guide.json").read_text(encoding="utf-8"))
        assert disk["app"] == "python" and disk["app_icon"] == "app_icon.png"
        assert (Path(d) / g["id"] / "app_icon.png").stat().st_size > 0
        assert disk["updated"] == disk["created"] and disk["bookmarked"] is False
        assert disk["settings"] == library.DEFAULT_SETTINGS
        assert "app" not in disk["steps"][0] and "exe" not in disk["steps"][0]
        g2 = rec._write_guide([{"id": "s2", "kind": "click", "text": "t",
                                "app": "ApplicationFrameHost", "exe": r"C:\Windows\System32\ApplicationFrameHost.exe",
                                "image": None, "crop": None, "markers": []}])
        assert g2["id"] != g["id"] and g2["app_icon"] is None
```

Make the `__main__` block in `test_windows.py` run every `test_*` function, using the same runner as `test_steps.py`.

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python.exe -X utf8 test_steps.py; .venv/Scripts/python.exe -X utf8 test_windows.py`
Expected: `ImportError` for `monitor_index` (test_steps), and a failure in `test_write_guide_fields_and_icon` (test_windows).

- [ ] **Step 4: Implement**
  - **Capture path:**
    - `window_info` returns the full exe path as its third item.
    - `_process` "capture" stores `self._pending = (x, y, name, ct, title, app, img, exe)`. The image stays at index 6, so the `_discard(self._pending[6])` calls are unchanged.
    - `_commit_click` unpacks 8 items and passes `exe=exe` to `add_click`.
  - **`_write_guide`:**
    - `gid = library.new_id(self.storage)`.
    - `app` and `exe` come from the first step with an `app`. Default `"StepCap"` / `""`.
    - Pop `app` and `exe` from every step.
    - `app_icon = "app_icon.png"` only if `exe` is set, `app not in HOST_APPS`, and `extract_icon(exe, folder / "app_icon.png")` succeeds; else `None`.
    - Set `created = updated = library.now_iso()` and `settings = dict(library.DEFAULT_SETTINGS)`.
    - Write with `library.write_json_atomic`.
  - **`extract_icon(exe, out)`:** use pythonnet, which is already installed for pywebview:
    - Load it with `import clr; clr.AddReference("System.Drawing")`.
    - Then call `Icon.ExtractAssociatedIcon(exe).ToBitmap().Save(str(out), ImageFormat.Png)`.
    - Wrap everything in `try/except Exception: return False`.
  - **`set_capture_excluded`:** `user32.SetWindowDisplayAffinity(hwnd, 0x11 if on else 0)`, with typed `argtypes = [wintypes.HWND, wintypes.DWORD]`. Also type `GetWindowDisplayAffinity` (`[HWND, POINTER(DWORD)]`) for tests. A `None` hwnd returns `False`.
  - **Window checks:**
    - `is_own_window`: `window_pid(hwnd) == os.getpid()` only. Update the docstring: the pywebview window lives in this process, and a WebView2 child's `GA_ROOT` is our form.
    - `find_main_window`: `EnumWindows`, matching `window_pid == os.getpid()` and `window_title == title`, with no visibility filter.
  - **`default_storage`:** `Path(os.environ["STEPCAP_STORAGE"])` when that variable is set and non-empty, otherwise the old path.

- [ ] **Step 5: Run to verify pass**

Run: `.venv/Scripts/python.exe -X utf8 test_steps.py && .venv/Scripts/python.exe -X utf8 test_windows.py && .venv/Scripts/python.exe -X utf8 test_library.py`
Expected: `10/10 passed`, then every test_windows test `ok`, then `11/11 passed`.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt recorder.py test_steps.py test_windows.py
git commit -m "feat: record app exe for card icons, PID-only self filter, main-window helpers"
```

---

### Task 3: app.py — pywebview window, tray thread, routes over `library`

**Files:**
- Modify: `app.py`
- Create: `test_app.py`
- Modify: `test_windows.py` (capture-exclusion test)

**Interfaces:**
- Consumes:
  - Everything `library` produces (Task 1).
  - `recorder.find_main_window`, `set_capture_excluded`, `monitor_index`, `default_storage` (Task 2).
- Produces:
  - **Globals:** `WINDOW` (pywebview `Window`), `QUITTING: bool`.
  - **Functions:**
    - `main_hwnd()`: `find_main_window()`, cached once it returns non-None.
    - `show_main()`
    - `quit_app()`
    - `flash_ui(i: int)`
  - **Changed functions:**
    - `start_rec_ui()` and `stop_rec_ui(from_page=False)` keep their signatures.
    - `select_mon_ui(i)` now also persists `monitor` by device name.
  - **Run file:** `STORAGE/_run.json` = `{"port", "token", "pid"}`, written after the server starts and removed on exit.
  - **HTTP routes.** All require `?t=` except `/ui/`. All guide ids are checked with `library.safe_id`. Bad requests return 404 or 400 as today.
    - GET:

      | Route | Returns |
      |---|---|
      | `/` | `editor.html` for now (Task 4 switches it to `ui/index.html`) |
      | `/api/guides?q=&bookmarked=1` | `library.list_guides` |
      | `/api/trash` | `library.list_trash` |
      | `/api/status` | unchanged |
      | `/api/settings` | `{**load_settings, "storage": str(STORAGE)}` |
      | `/api/guide/<id>` | `read_guide` (normalized) |
      | `/img/<id>/<file>` | unchanged; also serves `app_icon.png` |

    - POST:

      | Route | Does |
      |---|---|
      | `/api/start`, `/api/pause`, `/api/stop` | unchanged |
      | `/api/monitor?i=` | select monitor; now persists |
      | `/api/flash?i=` | flash only; ignored while recording |
      | `/api/guide/<id>` | `save_guide` |
      | `/api/guide/<id>/delete` | `trash_guide` |
      | `/api/guide/<id>/meta` | body `{"title"?, "bookmarked"?}` → `update_meta` |
      | `/api/guide/<id>/duplicate` | → `{"id": new}` |
      | `/api/guide/<id>/export` | body = HTML bytes → native Save As → `{"saved": path or null}` |
      | `/api/trash/<id>/restore`, `/api/trash/<id>/purge`, `/api/trash/empty` | trash actions |
      | `/api/settings` | body `{"view": "grid" or "list"}` |
      | `/api/open-folder` | `os.startfile(STORAGE)` |
      | `/api/show` | `show_main()` |
- Removes: `open_editor`, the Edge launch and `import webbrowser`; `list_guides` in app.py and `_safe` (now `library.safe_name`/`safe_id`); the tray item `คู่มือทั้งหมด`.

- [ ] **Step 1: Write the failing end-to-end test** `test_app.py`. It is Windows-only and launches real windows. It uses Win32 *queries* plus `WM_CLOSE` to its own test window, and never synthesizes input.
  - **Setup:**
    - Create a temp storage.
    - Seed the old-format guide `20260101-090000`, with title `"explorer - 1 ม.ค. 2569 09:00"`, one click step (text `คลิกปุ่ม "Start" ใน explorer`, no markers key) and one note. Save its exact bytes.
    - Launch `subprocess.Popen([sys.executable, "app.py"], cwd=HERE, env={**os.environ, "STEPCAP_STORAGE": tmp})`.
    - Wait ≤20 s for `_run.json`.
    - Helpers: `get(path)` and `post(path, body=None)`, built on `urllib` and the token. Define `find_win(pid)` locally with `EnumWindows` (pid + title `StepCap`). Read `GetWindowDisplayAffinity` through ctypes.
  - **Teardown:** `taskkill /PID <pid> /T /F` and remove the temp dir, in a `finally`.

```python
def test_old_guide_untouched():      # GET /api/guide/20260101-090000 -> settings == DEFAULT_SETTINGS, app == "explorer";
                                     # steps[0]["markers"] == []; file bytes on disk == seeded bytes
def test_window_is_ours():           # win visible within 15 s; window_pid(GetAncestor(WindowFromPoint(center), GA_ROOT)) == proc.pid
def test_close_hides_while_recording():
    # POST /api/start; affinity == 0x11; PostMessageW(win, WM_CLOSE); within 5 s: not IsWindowVisible(win)
    # proc.poll() is None; GET /api/status -> recording True
    # POST /api/stop -> {"guide": None}; affinity == 0
def test_second_instance_shows_window():
    # (window hidden from previous test) second = Popen same cmd/env; second.wait(15) == 0; IsWindowVisible(win) within 5 s
def test_library_routes():
    # duplicate -> new id in /api/guides; meta bookmarked True -> summary bookmarked; /api/guides?q=Start finds both;
    # delete original -> not in /api/guides, in /api/trash; restore -> back; POST /api/settings {"view":"list"} -> GET view "list"
    # GET /api/guide/_trash -> 404; GET /api/guides without token -> 403
```

Run the tests in this order; they share one launched app and one temp storage.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -X utf8 test_app.py`
Expected: FAIL. Either `_run.json` never appears, or the window is Edge's, not this PID's.

- [ ] **Step 3: Implement `app.py`.** These decisions are pinned:
  - **Startup order in `main()`:**
    1. Single instance: `CreateMutexW(None, False, "Local\\StepCap-" + sha1(str(STORAGE).lower())[:12])`, with typed restype `HANDLE`. Keep the handle global. If `get_last_error() == 183`, POST `/api/show` using `_run.json` (ignore errors) and `return`.
    2. `shell32.SetCurrentProcessExplicitAppUserModelID("StepCap")`.
    3. Create the Recorder, then call `REC.set_monitor(recorder.monitor_index(REC.monitors, load_settings(STORAGE)["monitor"]))`.
    4. Create the Overlay.
    5. Create the Tray and start `threading.Thread(target=tray.run, daemon=True)`.
    6. Call `REC.start_app()`.
    7. Start the server thread and write `_run.json`.
    8. `WINDOW = webview.create_window("StepCap", url, width=1280, height=820, min_size=(900, 600), background_color="#FFFFFF", text_select=True)`.
    9. Attach the events, then call `webview.start(private_mode=True)` on the main thread.
    10. After `start` returns: `tray.icon.stop()`, then remove `_run.json`.
  - **`closing` handler:**
    - When `QUITTING`, return `True`.
    - Otherwise start `threading.Thread(target=WINDOW.hide, daemon=True)` and return `False`. Calling `hide()` inside the handler can deadlock, because the handler runs while the UI thread waits for it.
  - **`shown` handler:** make `STORAGE/_app.ico` with Pillow. It is a `#FB923C` rounded square with a white ring, saved with sizes 16/32/48/256. Then `LoadImageW(None, path, IMAGE_ICON=1, 0, 0, LR_LOADFROMFILE|LR_DEFAULTSIZE)` and `SendMessageW(hwnd, WM_SETICON=0x80, 0|1, hicon)`. Type every handle argument.
  - **Window state:**
    - Minimize and restore go through Win32 `ShowWindowAsync` (`SW_MINIMIZE` / `SW_RESTORE`) on `main_hwnd()`. This restores a maximized window to maximized.
    - Show and hide go through `WINDOW.show()` / `WINDOW.hide()`, so the WinForms visibility state stays in sync.
    - `show_main()`: restore if iconic, then `WINDOW.show()`.
  - **`start_rec_ui`:** as today, but with `main_hwnd()` in place of `find_app_window()`. Add `set_capture_excluded(h, True)` right after `start_recording()` succeeds. A hidden window counts as "not visible elsewhere", so the panel is shown.
  - **`stop_rec_ui`:**
    1. Call `set_capture_excluded(h, False)`.
    2. If the window is iconic, restore it.
    3. If a guide was produced and the window is hidden, call `WINDOW.show()`.
    4. Remove the `open_editor` branch. The page follows `guide_seq`.
  - **`quit_app` (tray `ออก`):**
    1. Set `QUITTING = True`.
    2. If recording: `REC.stop_recording()`.
    3. `OV.hide_panel()`.
    4. `WINDOW.destroy()`.
  - **Tray menu, in order:**
    1. `เปิด StepCap` (`default=True`, so a left-click opens it) → `show_main`
    2. `เลือกจอ ▸`
    3. start/stop
    4. pause (visible while recording)
    5. separator
    6. `ออก` → `quit_app`
  - **Export route:**
    1. Read the title from `read_guide`. Build the file name as `re.sub(r'[\\/:*?"<>|]', "_", title).strip() or "guide"`.
    2. Call `WINDOW.create_file_dialog(webview.FileDialog.SAVE, save_filename=name + ".html", file_types=("HTML (*.html)",))`. The file_types string must stay ASCII, because pywebview's parser rejects Thai marks.
    3. The result may be a str or a tuple; take `[0]` of a tuple. Empty or `None` means cancelled: return `{"saved": null}` and write nothing.
  - **`/api/guide/<id>` save:** reject a body that is not a JSON object with HTTP 400.

- [ ] **Step 4: Add the capture-exclusion check** to `test_windows.py`. It runs pywebview on the main thread, so put it last in `__main__`.
  1. `webview.create_window("cap-test", html="<body style='margin:0;background:#00ff00'></body>", x=100, y=100, width=400, height=300)`.
  2. `webview.start(func=check, args=(win,))`.
  3. `check` waits for the window, then counts pure-green pixels in `ImageGrab.grab(bbox=rect, all_screens=True)`.
  4. Assert ≥90% green before. Call `set_capture_excluded(hwnd, True)` (hwnd = `find_main_window("cap-test")`). Assert ≤5% green after.
  5. Destroy the window.

  Name it `test_webview_excluded_from_capture`. It proves the WebView2 content inherits the exclusion.

- [ ] **Step 5: Run to verify pass**

Run: `.venv/Scripts/python.exe -X utf8 test_app.py && .venv/Scripts/python.exe -X utf8 test_windows.py && .venv/Scripts/python.exe -X utf8 test_steps.py && .venv/Scripts/python.exe -X utf8 test_library.py`
Expected: all `ok` / `N/N passed`.

- [ ] **Step 6: Point the shortcuts at the new icon.**

Run this once in PowerShell. It also launches the app, so the icon file exists:

```powershell
$s=(New-Object -ComObject WScript.Shell); foreach($p in "$env:USERPROFILE\OneDrive\Desktop\StepCap.lnk","$env:APPDATA\Microsoft\Windows\Start Menu\Programs\StepCap\StepCap.lnk"){ if(Test-Path $p){$l=$s.CreateShortcut($p);$l.IconLocation="$env:USERPROFILE\Documents\StepCap\_app.ico,0";$l.Save()} }
```

Expected: both `.lnk` files show the orange icon.

- [ ] **Step 7: Commit**

```bash
git add app.py test_app.py test_windows.py
git commit -m "feat: own pywebview window, X hides to tray, single instance, library routes, native Save As"
```

---

### Task 4: UI shell — Scribe-like light home, all guides, trash, settings

**Files:**
- Create: `ui/index.html`, `ui/common.js`, `ui/shell.js`, `ui/guide.js` (temporary)
- Delete: `editor.html`
- Modify: `app.py`. `/` serves `ui/index.html`. Add ungated `GET /ui/<name>`: `library.safe_name(name)`, the file must exist in `HERE/"ui"`, and the content type comes from the extension (`.js` → `text/javascript; charset=utf-8`, `.css`, `.svg`).

**Interfaces:**
- Consumes: the HTTP routes of Task 3.
- Produces (globals in `common.js`, used by `shell.js` and `guide.js`):
  - Core helpers:
    - `T` (token)
    - `api(path, opts) -> Promise<Response>` (current behavior)
    - `esc(s)`
    - `ICON: {[name]: svgString}`: home, docs, trash, settings, search, plus, bookmark, bookmarkFill, more, grid, list, app, back, edit, done, export, page, brush, sliders, folder. Lucide-style 24px stroke icons drawn inline.
  - Navigation:
    - `nav(params: object)`: sets `location.search` to `?t=…&…params`.
    - `goGuide(id: string, mode: "view"|"edit")`
  - Dialogs and toast (Thai buttons `ตกลง`/`ยกเลิก`; `toast` hides itself after 2.5 s):
    - `uiPrompt(label, value) -> Promise<string|null>`
    - `uiConfirm(message, okLabel = "ตกลง") -> Promise<boolean>`
    - `toast(text)`
  - Status polling:
    - `startStatusPoll(onStatus, ms, beforeLeave)`: polls `/api/status`, calls `onStatus(st)`, then `followNewGuide`. It catches up on `visibilitychange`. When `guide_seq` changes it awaits `beforeLeave` and then calls `goGuide(st.last_guide, "edit")`.
  - Boot: `?guide=` → `guidePage(id, mode)` (in `guide.js`); otherwise `shellPage(page)` (in `shell.js`); default page `home`.
  - `shell.js` exposes `shellPage(page)`, and also uses `exportGuide(gid)` from `guide.js`.

- [ ] **Step 1: Move the old editor into `ui/guide.js`.** Move it as-is, so guide pages keep working during this task.
  - **What moves:** cut lines 303–509 of `editor.html` (editor, preview, export) plus `regionFor`/`drawStep`/`renderGuide`.
  - **Wrapping:** wrap the moved code in `async function guidePage(id, mode) { GID = id; editor(); }` and have it use `startStatusPoll`.
  - **Temporary export:** `exportGuide(gid)` is a stub that calls `toast("เร็วๆ นี้")`. Task 5 replaces it.

- [ ] **Step 2: Build `ui/index.html` + `ui/common.js` + `ui/shell.js`.** These values are pinned:
  - **Tokens on `:root`:**

    ```text
    --bg:#ffffff; --side:#f7f8fa; --ink:#111827; --muted:#6b7280;
    --line:#e5e7eb; --hover:#f3f4f6; --accent:#fb923c; --dark:#111827;
    --danger:#dc2626; --warn:#b45309
    ```

    - font `"Segoe UI","Leelawadee UI",system-ui,sans-serif`
    - the body background is set explicitly
  - **Shell:**
    - Sidebar is 236 px, `--side` background, right border `--line`.
      - Logo row: an orange rounded-square SVG + `StepCap`.
      - Search box `ค้นหา` with a search icon.
      - Nav: `Home`, `คู่มือทั้งหมด`, `ถังขยะ`, `ตั้งค่า`. The active item gets `--hover` background and bold text.
    - Top bar: page icon + page name on the left; on the right, a dark `+ บันทึกใหม่` button (`--dark` background, white text).
    - Content: max width 1100 px with 32 px padding.
  - **Search:** typing (200 ms debounce) shows the `คู่มือทั้งหมด` page in place using `history.replaceState` (no reload), filtered with `/api/guides?q=`. Clearing the box keeps the user on that page.
  - **Record menu (popover under the button):**
    - One row per monitor: `จอ N · W×H` + `· จอหลัก` on the primary. The selected monitor shows a check.
    - Hovering a row calls `POST /api/flash?i=`, throttled to once per 1.5 s per monitor.
    - Clicking a row calls `POST /api/monitor?i=`.
    - The bottom button `เริ่มบันทึก` calls `POST /api/start` and closes the popover.
    - While recording, the top-bar button becomes red `■ หยุดบันทึก`. It calls `POST /api/stop`, then `goGuide(r.guide, "edit")` if there is a guide.
  - **Banners (above content):**
    - Red hook warning: same text as today, shown when `!st.hooks_ok`.
    - Recording banner (shown when `st.recording`): `● กำลังบันทึก` or `⏸ พักอยู่`, plus `N ขั้นตอน`; the last 5 steps and the italic pending line (`… text`); buttons `พัก`/`ทำต่อ` and `หยุด`.
    - Poll every 500 ms.
  - **Home page:**
    - Heading `ล่าสุด` with the grid/list toggle on the right. The toggle state comes from `/api/settings.view` and is saved with `POST /api/settings`.
    - Recents: up to 8 guides, bookmarked first, then newest. Use a stable sort of `/api/guides` by `bookmarked` descending.
    - Grid view: `repeat(4, 1fr)` at ≥ 1000 px content width, 2 columns below that, gap 16 px.
    - Below the recents: an outlined `ดูทั้งหมด` button → the all-guides page.
    - Then `สถิติ`: one card, `คู่มือทั้งหมด`, with the count from `/api/guides` (trash excluded).
    - Empty state: `ยังไม่มีคู่มือ กด + บันทึกใหม่ เพื่อเริ่ม`.
  - **Card (grid):**
    - Border `--line`, radius 8 px, padding 20 px.
    - Hover: a `0 1px 6px rgba(0,0,0,.08)` shadow, and a floating tool group at the top right (white, bordered, radius 6 px):
      - Bookmark toggle → `POST /meta {"bookmarked": !b}`. The filled icon stays visible when bookmarked, even without hover.
      - `⋯` menu: `เปิด`, `เปลี่ยนชื่อ` (uiPrompt → meta title), `ทำสำเนา` (duplicate → reload list), `ส่งออก` (`exportGuide(id)`), `ลบ` (→ delete, no confirm, because trash restores; then `toast("ย้ายไปถังขยะแล้ว")`).
    - Content:
      - App icon in a 32 px circle with a `--hover` background. Use `/img/<id>/app_icon.png?t=` when `icon` is true, else `ICON.app`.
      - App name in muted 13 px.
      - Title: 16 px semibold, clamped to 2 lines.
      - Meta: `ago · N ขั้นตอน` in muted 13 px.
    - Clicking the card body → `goGuide(id, "view")`.
  - **List view:** one row per guide: icon, title, app, ago, count. The hover tools are the same.
  - **`คู่มือทั้งหมด` page:** a `เฉพาะที่บุ๊กมาร์ก` checkbox and the view toggle in the header; all guides, newest first, from `/api/guides?q=&bookmarked=`. Empty-search text: `ไม่พบคู่มือที่ตรงกับ "q"`.
  - **`ถังขยะ` page:**
    - Rows: title, `ลบเมื่อ <ago>`, `N ขั้นตอน`, and the buttons `กู้คืน` and `ลบถาวร`. `ลบถาวร` asks `uiConfirm("ลบถาวร? ไฟล์จะไปอยู่ในถังขยะของ Windows")`.
    - Header button `ล้างถังขยะ`: `uiConfirm("ล้างถังขยะทั้งหมด N รายการ?")`.
    - Empty state: `ถังขยะว่าง`.
  - **`ตั้งค่า` page, sections:**
    - `จอเริ่มต้นสำหรับบันทึก`: the same rows as the record menu.
    - `ปุ่มลัด`: read-only rows `Ctrl+Alt+R — เริ่ม/หยุดบันทึก` and `Ctrl+Alt+P — พัก/ทำต่อ`.
    - `ที่เก็บคู่มือ`: the path from `/api/settings.storage` and a `เปิดโฟลเดอร์` button → `POST /api/open-folder`.
    - `ซ่อนข้อมูลอัตโนมัติ`: a disabled switch with muted text `เร็วๆ นี้`.

- [ ] **Step 3: Syntax-check and smoke-run**

Run `node --check ui/common.js && node --check ui/shell.js && node --check ui/guide.js`, then `.venv/Scripts/python.exe -X utf8 test_app.py`.
Expected: no output from node; all `test_app` tests `ok`.

- [ ] **Step 4: Visual check against the reference**
  1. Copy the real guides read-only into a scratch storage with `cp -r ~/Documents/StepCap/2* <scratch>/`.
  2. Launch with `STEPCAP_STORAGE=<scratch>`.
  3. Grab the window rect with `ImageGrab` into the scratchpad. Inspect the PNG next to `docs/specs/refs/scribe-home-light-card-hover.png`. It is gitignored; it lives only on this machine.
  4. Check the sidebar, 4-per-row cards, hover tools, the stats card and Thai text.

Expected: the layout matches the reference structure, and no Edge window opened.

- [ ] **Step 5: Commit**

```bash
git rm editor.html
git add ui app.py
git commit -m "feat: Scribe-like light home, all guides, trash and settings in the app window"
```

---

### Task 5: Guide view mode + export through the same renderer

**Files:**
- Modify: `ui/guide.js` (replace the moved preview/regionFor/old renderGuide), `ui/index.html` (the `#rg-css` style block)

**Interfaces:**
- Consumes:
  - From `common.js`: `api`, `esc`, `ICON`, `nav`, `goGuide`, `toast`, `startStatusPoll`.
  - Routes: `GET /api/guide/<id>`, `POST /api/guide/<id>/export`.
- Produces:
  - `drawStepCanvas(canvas: HTMLCanvasElement, img: HTMLImageElement, step) -> void`:
    - The source region is `step.crop` or the full image; never zoomed.
    - The canvas is sized to the region's natural pixels; CSS scales it to `width:100%`.
    - Markers are drawn as today: fill `color+"26"`, stroke width `max(3, r*0.14)`.
  - `renderGuide(guide, root) -> Promise<void>`:
    - Self-contained except for `drawStepCanvas`. Each image comes from `step._src`.
  - `guidePage(id, mode)`: `mode` `"view"` (default) or `"edit"`.
  - `exportGuide(gid) -> Promise<void>`.
- Removes: `regionFor`, `drawStep`, `preview()`, the `ดูตัวอย่าง` button and the blob download.

- [ ] **Step 1: Implement `renderGuide`.** Order and copy are pinned:
  1. `<h1>` title.
  2. Meta line, only for the switches that are on, joined with ` · `:
     - `N ขั้นตอน` (`N` excludes notes)
     - `สร้างเมื่อ D`
     - `แก้ไขล่าสุด D`

     Dates use `new Date(iso).toLocaleDateString("th-TH", {year:"numeric", month:"short", day:"numeric"})`, which gives e.g. `15 ต.ค. 2569`. An empty or invalid ISO hides that item.
  3. When `settings.toc` is on: `<nav class="rg-toc"><b>สารบัญ</b><ol>`. Each numbered step is `<li><a href="#step-<id>">text</a>`.
  4. Steps:
     - Numbered steps: `<div class="rg-step" id="step-<id>">` with the number badge + text + canvas.
     - Notes: a `.rg-note` callout, no number.

  `#rg-css` holds only the `rg-` classes (wrap max 960 px, number badge in `#fb923c`, note callout, TOC, `canvas{width:100%;border:1px solid #e5e7eb;border-radius:8px}`). Export embeds exactly this block.

- [ ] **Step 2: Implement view mode** in `guidePage(id, "view")`:
  - **Top bar:**
    - `ICON.back` button → `nav({page: "home"})`.
    - The guide title as text.
    - On the right: `แก้ไข` (`ICON.edit`) → `goGuide(id, "edit")`, and `ส่งออก` (`ICON.export`) → `exportGuide(id)`.
  - **Body:** `renderGuide(normalizedGuide, root)`. Each `_src` is `/img/<id>/<image>?t=`.
  - **Polling:** `startStatusPoll(() => {}, 1000)`.

- [ ] **Step 3: Implement `exportGuide(gid)`:**
  1. Fetch the guide.
  2. Embed each image as a data URL in `_src` and drop `image`.
  3. Build the HTML string:

     ```text
     <!doctype html> + <meta charset> + <title>esc(title)</title>
     + <style>${#rg-css}</style> + <div id="root">
     + <script>const guide=${json}; ${drawStepCanvas}; (${renderGuide})(guide, document.getElementById("root"));</script>
     ```

     `json` is `JSON.stringify(g).replace(/</g, "\\u003c")`, so step text containing `</script>` cannot break out.
  4. `POST /api/guide/<gid>/export` with the HTML as the body.
  5. On `saved`: `toast("บันทึกไฟล์แล้ว")`. On `null` (cancelled): do nothing.

- [ ] **Step 4: Check**
  1. `node --check ui/guide.js`.
  2. Launch on the scratch storage and open a real guide. Screenshot it and inspect: full screenshots, not zoomed; a cropped step shows the crop; notes have no number.
  3. Turn on all four switches by editing that scratch guide's `settings` in its JSON. Reload and verify the meta line and the TOC links.
  4. Click `ส่งออก`: a Windows Save As dialog appears. Save into the scratchpad, then open the saved file's HTML in pywebview via a throwaway script (no browser) or inspect its text. Cancelling the dialog writes nothing and shows no toast.

  Expected: as described in 2–4.

- [ ] **Step 5: Commit**

```bash
git add ui
git commit -m "feat: guide view mode with full screenshots, TOC/meta switches, export via Save As"
```

---

### Task 6: Edit mode — Done, floating toolbar, click color, doc settings, Grid

**Files:**
- Modify: `ui/guide.js`, `ui/index.html` (edit-mode CSS)

**Interfaces:**
- Consumes:
  - From Task 5: `drawStepCanvas`, `renderGuide`, `exportGuide`, `guidePage`.
  - From Task 4 (`common.js`): `startStatusPoll(onStatus, ms, beforeLeave)`.
  - Routes: `POST /api/guide/<id>` (save).
- Produces:
  - `guidePage(id, "edit")`.
  - `setClickColor(hex: string) -> void`: sets `STATE.settings.click_color`, recolors every marker in every step, sets the color used for new markers, re-renders, and saves.
  - `KIND_TH = {click: "คลิก", rightclick: "คลิกขวา", doubleclick: "ดับเบิลคลิก", type: "พิมพ์", password: "รหัสผ่าน", shortcut: "ปุ่มลัด", note: "หมายเหตุ"}`: replaces the uppercase English kind tag.

- [ ] **Step 1: Port the editor into edit mode.**
  - **Keep every current ability:**
    - title edit; step text edit
    - delete step; drag reorder
    - `+ เพิ่มหมายเหตุ`
    - markers: add / drag / per-marker color and size / delete
    - crop draw / clear
    - autosave with 500 ms debounce
  - **Changes:**
    - Step numbers skip notes. A note card shows the `หมายเหตุ` tag instead of a number badge and is still draggable.
    - New markers use `STATE.settings.click_color`.
  - **Top bar:**
    - back → `saveNow()` then home.
    - title input.
    - dark `เสร็จสิ้น` (`ICON.done`) → `await saveNow()` then `goGuide(id, "view")`.
    - `ส่งออก`.
  - **Polling:** `startStatusPoll(() => {}, 1000, () => SAVET ? saveNow() : null)`, so a guide recorded meanwhile opens after flushing edits.

- [ ] **Step 2: Build the floating toolbar.**
  - **Placement and tooltips:**
    - Fixed to the right edge at `top: 88px`: a vertical white panel with border `--line`, radius 10 px, 3 icon buttons of 36 px.
    - CSS tooltip to the left from `data-tip` (dark pill, white 13 px text, shown on hover).
  - **Buttons, top to bottom:**
    1. `ICON.page`: disabled, `data-tip="เพิ่มลงหน้า · เร็วๆ นี้"`.
    2. `ICON.brush`, `data-tip="สีวงจุดคลิก"`.
       - Opens a popover with swatches `#FB923C #EF4444 #EAB308 #22C55E #3B82F6 #A855F7`, an `<input type="color">` and a hex text box.
       - A hex value matching `/^#[0-9a-f]{6}$/i` is applied; anything else is ignored.
       - Every choice calls `setClickColor`. The current color shows a ring.
    3. `ICON.sliders`, `data-tip="ตั้งค่าเอกสาร"`. Opens a popover with:
       - four switches: `สารบัญ`, `จำนวนขั้นตอน`, `วันที่สร้าง`, `วันที่แก้ไขล่าสุด` → `settings.toc` / `step_count` / `created` / `updated`;
       - a two-button segment `เรียงต่อกัน | ตาราง` → `settings.layout` `"linear"` / `"grid"`.

       Each change saves and re-renders.
  - **Closing:** popovers close on outside click or Esc.

- [ ] **Step 3: Build the Grid layout.** It is used when `settings.layout == "grid"`, and only in edit mode.
  - **Grid:** `repeat(3, 1fr)`, gap 16 px.
  - **Cards:**
    - Each card shows a thumbnail (`drawStepCanvas` into a canvas with `aspect-ratio: 16/10; object-fit: contain` on a `#f3f4f6` background), the number badge (none for notes) and the text clamped to 2 lines.
    - Steps without an image render as a text card.
  - **Reorder:** same `dataTransfer` logic as linear, then save.
  - **Click a card:**
    1. Set `settings.layout = "linear"` and save.
    2. Re-render.
    3. `document.getElementById("edit-<id>").scrollIntoView({block: "start"})`. Linear step cards get `id="edit-<step id>"`.

- [ ] **Step 4: Check**
  1. `node --check ui/guide.js`.
  2. On the scratch storage, open a guide → `แก้ไข`. Then:
     - pick a swatch: all circles change, and a newly added circle uses that color;
     - change one circle's color: only it changes;
     - toggle the TOC on → `เสร็จสิ้น`: the view shows the TOC;
     - switch to `ตาราง`: 3 per row; drag a card: the order persists after reload; click a card: linear, scrolled to it.
  3. Reopen the scratch guide JSON: `settings` holds the values; markers have the new color.
  4. Run all four test files.

  Expected: as described; all tests pass.

- [ ] **Step 5: Commit**

```bash
git add ui
git commit -m "feat: edit mode with Done, floating toolbar, click color, doc settings and grid layout"
```

---

### Task 7: Acceptance on the real setup

**Files:** none new.

- [ ] **Step 1: Full test run**

Run: `.venv/Scripts/python.exe -X utf8 test_steps.py && .venv/Scripts/python.exe -X utf8 test_library.py && .venv/Scripts/python.exe -X utf8 test_windows.py && .venv/Scripts/python.exe -X utf8 test_app.py`
Expected: every test `ok` / `N/N passed`.

- [ ] **Step 2: Hand the checklist to the user.**

The user runs it on their real storage, because we never synthesize input. In Thai:
  - **Start and close:**
    - Open from the desktop shortcut: only the StepCap window appears (no Edge); the icon is orange.
    - Press X: the window hides and the tray stays.
    - Open the shortcut again: the same window returns.
    - Left-click the tray icon: the window opens.
  - **Recording:**
    - `+ บันทึกใหม่`: hovering or clicking a monitor flashes it; `เริ่มบันทึก` → the window collapses to the panel.
    - Click a few things and type → `หยุดบันทึก`: the window returns in **edit mode** of the new guide, and the card shows the app's icon.
    - No StepCap window appears in any screenshot.
  - **Old guides:** they open in view mode with full screenshots; editing still works.
  - **Card actions:** bookmark / rename / duplicate / delete → trash → restore / permanent delete → Windows Recycle Bin.
  - **Export:** the Save As dialog saves a file that opens and looks like view mode.
  - **Quit:** tray `ออก` while recording → the guide is saved, then the app exits.

- [ ] **Step 3: Record the outcome.** Mark the spec status `สร้างแล้ว (pieces 0+1)` with the date, then commit.

```bash
git add docs/specs/2026-10-15-app-window-home-viewer-design.md
git commit -m "docs: pieces 0+1 built and accepted"
```
