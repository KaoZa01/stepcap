# Installer (.exe) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `dist/StepCap-Setup-1.0.0.exe` that installs StepCap per-user, without admin, with the language chosen in the installer becoming the app's first language.

**Architecture:**
- PyInstaller (onedir, windowed) turns `app.py` and its `ui/` and `samples/` files into `dist/StepCap/StepCap.exe`.
- Inno Setup 6 wraps that folder in a per-user installer that asks Thai or English and writes the choice to `{app}\lang.txt`, which the app reads on first start.
- `app.py --selfcheck` exercises every part that freezing can break (UI files, translations, samples, UI Automation, OCR, Word export, tray, Tk, WebView2), so a frozen build is tested without any clicks.
- `build.py` runs the whole pipeline.

**Tech Stack:**
- Build tools: PyInstaller 6.22.3, in `.venv` from `requirements-build.txt`, and Inno Setup 6 (winget `JRSoftware.InnoSetup`).
- App: Python 3.14 and the existing deps; no new runtime dependencies.

**Spec:** `docs/specs/2026-10-16-installer-design.md` (approved 2026-10-16)

## Global Constraints

- **Version:** `"1.0.0"`, defined once as `app.VERSION`. `build.py` reads it with a regex and does not import `app` to get it.
- **Installer settings:**
  - per-user only: `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\Programs\StepCap`
  - x64 only
  - `AppPublisher=StepCap`
  - output file `dist/StepCap-Setup-1.0.0.exe`
- **Installer language:** a language dialog (Thai via `installer/Thai.isl`, English via `compiler:Default.isl`) comes first. Its choice is written to `{app}\lang.txt` as `th` or `en`.
- **First-start language:** `ensure_lang` order:
  1. unreadable `settings.json` → `th`, and nothing is written
  2. valid saved `lang` → keep it
  3. valid installer lang → save it and use it
  4. existing user → `th`
  5. fresh storage → from the Windows display language, then save it
- **Uninstall:** never touches `Documents\StepCap`. It removes `{app}` (including `lang.txt`) and the shortcuts.
- **App-running check:** the app holds the fixed mutex `StepCapRunning` while it runs. The installer uses `AppMutex=StepCapRunning`.
- **WebView2 missing:** the installer shows a message and stops. It never downloads anything.
- **Build output:** `build/` and `dist/` are git-ignored. The build tools are not in `requirements.txt`.
- **Testing on this machine:**
  - Tests never click or type on the desktop.
  - The app always runs with `STEPCAP_STORAGE` pointing at a temp dir. Real guides in `Documents\StepCap` are read-only.
  - The real-installer test runs once, by hand, and is announced to the user first.

## Review Focus

1. **Machine without WebView2:** the installer stops with the message. Check the registry keys in `InitializeSetup`. This can't be reproduced on this machine.
2. **StepCap open during install or uninstall:** `AppMutex` asks the user to close it. In test 3 of Task 1, check the mutex exists while the app runs.
3. **Install path with a space** (a user folder name like "Jane Doe"): the frozen app finds `ui/`, the samples and `lang.txt`. Covered because `test_installer.py` installs under the profile.
4. **A part used only on a rare path is missing from the freeze** (winrt OCR submodules, docx templates, comtypes UIA gen, pystray win32 backend, WebView2 DLLs). Covered by `--selfcheck` running real work for each one, in Task 2.
5. **Upgrade over an existing install with a different installer language:** a saved `lang` is not changed. Covered by the `ensure_lang` test in Task 1. `test_installer.py` installs twice.

---

### Task 1: App side — version, installer language, running mutex, self-check

**Files:**
- Modify: `library.py` (`ensure_lang`, new `read_installer_lang`), `app.py` (`VERSION`, `single_instance`, `main`, `selfcheck`, `__main__`)
- Test: `test_library.py`, `test_exporters.py` (it already imports `app` on a temp storage), `test_app.py`

**Interfaces:**
- Produces:
  - `library.read_installer_lang(folder: Path) -> str | None`
    - returns the stripped content of `folder/"lang.txt"` if it is in `i18n.LANGS`
    - otherwise `None`, including when the file is missing or unreadable
  - `library.ensure_lang(storage: Path, windows_thai: bool, installer_lang: str | None = None) -> str`, following the order in Global Constraints
  - `app.VERSION = "1.0.0"`
  - `app.selfcheck() -> dict[str, str]`
    - keys: `ui`, `samples`, `uia`, `ocr`, `docx`, `tray`, `tk`, `webview`
    - each value is `"ok"` or a short error
  - `python app.py --selfcheck OUT.json` writes that dict as JSON and exits `0` if all are `"ok"`, else `1`, with no window and no mutex.
  - In `main()`, the installer language comes from `read_installer_lang(Path(sys.executable).parent)` when `getattr(sys, "frozen", False)`, else `None`.

- [ ] **Step 1: Write the failing tests**

`test_library.py`:
```python
def test_ensure_lang_installer_choice():
    # fresh: installer wins over Windows; saved
    # empty dir: ensure_lang(st, True, "en") == "en" and load_settings(st)["lang"] == "en"
    # existing user without lang (g1/guide.json): ensure_lang(st, False, "en") == "en", then saved
    # saved lang wins: settings {"lang": "th"} -> ensure_lang(st, False, "en") == "th"
    # corrupt settings b'{"vi' -> ensure_lang(st, False, "en") == "th", bytes unchanged
    # bad installer value: ensure_lang(fresh, True, "fr") == "th"
def test_read_installer_lang():
    # lang.txt "en\n" -> "en"; "th" -> "th"; "fr" -> None; missing -> None; a directory named lang.txt -> None
```

`test_exporters.py` `test_selfcheck_from_source`:
- `app.selfcheck()` returns a dict
- its keys equal `{"ui", "samples", "uia", "ocr", "docx", "tray", "tk", "webview"}`
- every value is `"ok"` (on failure, report the dict)

`test_app.py` `test_running_mutex`:
- while the app runs, `OpenMutexW(0x00100000, False, "StepCapRunning")` returns a non-zero handle
- close the handle afterwards

- [ ] **Step 2: Run, verify RED.** Expected: `ensure_lang` gets an unexpected argument, `read_installer_lang` and `selfcheck` are missing, and the mutex handle is 0.

- [ ] **Step 3: Implement.** What each self-check does:

| check | real work |
|---|---|
| `ui` | `index.html` and `en.json` exist, and `i18n.EN` is non-empty |
| `samples` | both `SAMPLE_DIRS` have a readable guide with 10 steps |
| `uia` | `recorder._UIA().at_point(0, 0)`, which only reads |
| `ocr` | `redact.ocr_lines` on a 64×32 white PNG written to a temp file; returns a list, so the winrt modules load. If `redact.available()` gives a reason, report `"ok"` when the reason is the "no English OCR" one, since that is a machine fact and not a freeze fault |
| `docx` | `exporters.build_docx` on a one-step guide; bytes start with `PK` |
| `tray` | `import pystray`, and `pystray.Icon.__module__` ends with `_win32` |
| `tk` | `tkinter.Tcl().eval("info patchlevel")` |
| `webview` | `from webview.platforms.winforms import BrowserView` |

Other implementation points:
- `single_instance()` first also calls `CreateMutexW(None, False, "StepCapRunning")` and keeps the handle in a module global.
- `__main__`: when `"--selfcheck"` is in `sys.argv`, write the JSON to the next argument and `raise SystemExit`. Otherwise call `main()`.

- [ ] **Step 4: Run, verify GREEN.** `test_library`, `test_exporters` and `test_app` pass, then all other suites.
- [ ] **Step 5: Commit** `feat: installer language hand-off, running mutex, --selfcheck`

---

### Task 2: Build pipeline — PyInstaller + frozen tests

**Files:**
- Create: `requirements-build.txt` (`pyinstaller==6.22.3`), `build.py`, `test_build.py`
- Modify: `.gitignore` (`build/`, `dist/`)

**Interfaces:**
- Consumes: `app.VERSION`, `--selfcheck`, `app.ensure_app_icon(path)`
- Produces:
  - `build.py` with `freeze() -> Path` returning the path of `dist/StepCap/StepCap.exe`
  - `build.py` with `installer() -> Path` (Task 3)
  - `python build.py` runs `freeze()`, then the frozen `--selfcheck` (aborts on failure), then `installer()` if ISCC is found, else it says so
  - `test_build.py` runs against an existing `dist/StepCap/StepCap.exe`

- [ ] **Step 1: Install the build tool:** `.venv/Scripts/python.exe -m pip install -r requirements-build.txt`. Expected: `pyinstaller 6.22.3` is installed.
- [ ] **Step 2: Write the failing test** `test_build.py`, which uses the same `__main__` runner as test_library:

```python
def test_frozen_selfcheck():      # dist/StepCap/StepCap.exe --selfcheck <tmp>.json -> exit 0, all "ok"
def test_frozen_app_starts():     # STEPCAP_STORAGE=<new temp>: _run.json within 30 s; GET / 200 contains 'const LANG="'
                                  # GET /api/guides lists exactly one guide titled a SAMPLE_TITLES value
                                  # POST /api/settings {"lang": "en"} then GET / contains 'const LANG="en"' and '"Contents"'
                                  # taskkill /T /F, then no process left with the exe's path (tasklist /FI "IMAGENAME eq StepCap.exe" + path check via PID)
def test_frozen_has_no_console(): # PE header of StepCap.exe: Subsystem == 2 (WINDOWS_GUI)
```

- [ ] **Step 3: Run, verify RED.** Expected: fails because `dist/StepCap/StepCap.exe` does not exist.
- [ ] **Step 4: Implement `build.py` `freeze()`:**
  - Set `STEPCAP_STORAGE` to a temp dir before `import app`, so a build never touches `Documents\StepCap`.
  - Write `build/StepCap.ico` with `app.ensure_app_icon`.
  - Run `PyInstaller.__main__.run(...)` with:
    - `--noconfirm --windowed --name StepCap --icon build/StepCap.ico`
    - `--distpath dist --workpath build/pyi --specpath build`
    - `--add-data` for `ui`, `samples/getting-started` and `samples/getting-started-en`, each to the same path
    - `--hidden-import pystray._win32`
    - `--collect-submodules winrt`
  - Add hidden imports or collects only when `--selfcheck` names something missing, and ledger each one.
- [ ] **Step 5: Run `python build.py`, then `test_build.py`. Verify GREEN.** Also record the size of `dist/StepCap` in the ledger.
- [ ] **Step 6: Commit** `build: PyInstaller freeze with self-check and frozen smoke tests`

---

### Task 3: Installer — Inno Setup script

**Files:**
- Create: `installer/StepCap.iss`, `installer/Thai.isl` (downloaded once), `test_installer.py`
- Modify: `build.py` (`installer()`)

**Interfaces:**
- Consumes: `dist/StepCap/`, `build/StepCap.ico`, `app.VERSION`
- Produces:
  - `dist/StepCap-Setup-1.0.0.exe`
  - `test_installer.py`, which is run by hand

- [ ] **Step 1: Install the tools:**
  - `winget install --id JRSoftware.InnoSetup --scope user --silent --accept-package-agreements --accept-source-agreements`
  - Download `Thai.isl` from the Inno Setup unofficial translations (`https://jrsoftware.org/files/istrans/`) into `installer/`.
  - Expected: `ISCC.exe` is found under `%LOCALAPPDATA%\Programs\Inno Setup 6\` or `Program Files (x86)\Inno Setup 6\`, and `Thai.isl` starts with `[LangOptions]`.
- [ ] **Step 2: Write the failing test** `test_installer.py`. It is never part of a routine run. It runs once, by hand, after telling the user. Add a module docstring that says so and lists what it touches.

It installs and uninstalls twice:

```python
def test_install_run_uninstall():
    # 1. dist/StepCap-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LANG=en /TASKS="" /DIR=<tmp under %LOCALAPPDATA%>
    #    -> exit 0; <dir>/StepCap.exe exists; <dir>/lang.txt == "en"; Start menu shortcut StepCap.lnk exists under %APPDATA%\Microsoft\Windows\Start Menu\Programs
    # 2. <dir>/StepCap.exe --selfcheck <tmp>.json -> all "ok"
    # 3. install again with /LANG=th over it -> lang.txt == "th" (upgrade path)
    # 4. <dir>/unins000.exe /VERYSILENT /SUPPRESSMSGBOXES -> wait; <dir> gone or empty of files; shortcut gone
    # 5. Documents\StepCap listing + mtimes identical before and after
```

- [ ] **Step 3: Run, verify RED.** Expected: fails because the setup exe does not exist.
- [ ] **Step 4: Implement `installer/StepCap.iss`** with every value from Global Constraints, plus:
  - `ShowLanguageDialog=yes`, `WizardStyle=modern`, `DisableProgramGroupPage=yes`
  - `Compression=lzma2/max`, `SolidCompression=yes`
  - `SetupIconFile=..\build\StepCap.ico`, `UninstallDisplayIcon={app}\StepCap.exe`
  - `[Tasks]`: `desktopicon`, checked by default
  - `[Icons]`: `{autoprograms}\StepCap` and `{autodesktop}\StepCap` (only with the desktopicon task)
  - `[Run]`: a `postinstall` checkbox "Open StepCap" / "เปิด StepCap" (`skipifsilent`)
  - `[Code]`:
    - `CurStepChanged(ssPostInstall)` writes `ActiveLanguage` to `{app}\lang.txt`
    - `InitializeSetup` looks up the WebView2 `pv` value under these keys, and fails with the message if none is set:
      - `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`
      - `HKCU\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`
    - "set" means present and not `0.0.0.0`
    - the message, in Thai or English: "ต้องติดตั้ง Microsoft Edge WebView2 Runtime ก่อน" / "Microsoft Edge WebView2 Runtime is needed first"
  - `[CustomMessages]`: Thai and English for both texts above
  - `[UninstallDelete]`: `Type: files; Name: "{app}\lang.txt"`. The `[Code]` step creates it, so the uninstaller doesn't track it.
  - `build.py` `installer()` runs ISCC with `/DMyVersion=<VERSION>` and returns the output path.
- [ ] **Step 5: Announce to the user, run `test_installer.py`, then verify GREEN.** Then open the setup once by hand, only on the user's request.
- [ ] **Step 6: Commit** `build: per-user Inno Setup installer with language choice`

---

### Task 4: Docs

**Files:**
- Create: `docs/install-guide.md`. It is the text the user copies into a chat or email with the file, in Thai then English, and covers:
  - what the file is
  - double-click to install
  - the blue "Windows protected your PC" screen: click "More info", then "Run anyway"
  - choose the language, then Next
  - where to find StepCap afterwards
  - uninstalling from Settings > Apps keeps your guides
- Modify:
  - `README.md`:
    - the ติดตั้ง section: for users, the setup file plus the install guide; for developers, the existing commands
    - a new section ทำไฟล์ติดตั้ง: `pip install -r requirements-build.txt`, the Inno Setup winget line, `python build.py`, `test_build.py`, and `test_installer.py` (run by hand)
  - spec status line.

- [ ] **Step 1:** Write the docs, then run `test_i18n.py`. Expected: passes (docs aren't linted).
- [ ] **Step 2: Commit** `docs: install guide and build instructions`
