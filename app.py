"""StepCap: global recorder + its own window (pywebview) + tray.

Run with: pythonw app.py   (or: python app.py for a console)

Threads: pywebview owns the main thread (WinForms/WebView2); the tray, the tk
overlays, the hooks and the local HTTP server each run on their own. The page
talks to Python only through the token-gated server on 127.0.0.1.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import secrets
import time
import threading
import urllib.request
from ctypes import wintypes
from functools import partial
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import webview

import exporters
import library
import overlay
import recorder
import redact
from recorder import Recorder, default_storage

recorder.set_dpi_aware()

HERE = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(16)
STORAGE = default_storage()
STORAGE.mkdir(parents=True, exist_ok=True)
RUN_FILE = STORAGE / "_run.json"   # port + token, so a second launch can poke us
ICON_FILE = STORAGE / "_app.ico"

user32 = recorder.user32
kernel32 = recorder.kernel32
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                  wintypes.LPCWSTR]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                              wintypes.UINT, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT]
user32.SendMessageW.restype = recorder.LRESULT
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]


# ---------------------------------------------------------------------------
# Recycle-bin delete (no extra dependency)
# ---------------------------------------------------------------------------
def recycle(path: Path):
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint),
                    ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                    ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", ctypes.c_wchar_p)]
    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40
    FOF_NOCONFIRMATION = 0x10
    FOF_SILENT = 0x04
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = str(path) + "\0\0"
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))


# ---------------------------------------------------------------------------
# HTTP handler (127.0.0.1 only, token-gated)
# ---------------------------------------------------------------------------
_UI_TYPES = {".js": "text/javascript; charset=utf-8",
             ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
_GUIDE_RE = re.compile(
    r"/api/guide/([^/]+)(?:/(delete|meta|duplicate|export|image|download|redact))?")
_TRASH_RE = re.compile(r"/api/trash/([^/]+)/(restore|purge)")
_PAGE_RE = re.compile(r"/api/page/([^/]+)(?:/(doc|delete|add|export))?")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _auth(self, qs) -> bool:
        tok = qs.get("t", [""])[0]
        return secrets.compare_digest(tok, TOKEN)

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        return self._send(code, json.dumps(obj, ensure_ascii=False))

    def _missing(self):
        return self._send(404, "not found", "text/plain")

    def _redact(self, gid: str, data: dict | None):
        """Blur rects for one image of the guide, minus what `existing` covers.
        Without `force` it honours the redact_on switch."""
        if data is None or not isinstance(data.get("image"), str) \
                or not isinstance(data.get("existing", []), list):
            return self._send(400, "bad request", "text/plain")
        folder = STORAGE / gid
        f = folder / data["image"]
        if not library.safe_name(data["image"]) or f.parent != folder or not f.is_file():
            return self._missing()
        cfg = library.load_settings(STORAGE)
        if not (data.get("force") or cfg["redact_on"]):
            return self._json({"rects": []})
        if f.suffix.lower() == ".gif":
            return self._json({"error": "ภาพ GIF ซ่อนข้อมูลไม่ได้"})
        try:
            found = redact.find_rects(f, cfg["redact_rules"], cfg["redact_custom"])
        except redact.RedactError as e:
            return self._json({"error": str(e)})
        existing = [r for r in data.get("existing", []) if isinstance(r, dict)
                    and all(isinstance(r.get(k), (int, float)) for k in "xywh")]
        return self._json({"rects": redact.new_rects(found, existing)})

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        p = u.path
        if p.startswith("/ui/"):  # page source only; no data, so no token
            name = unquote(p[len("/ui/"):])
            f = HERE / "ui" / name
            ctype = _UI_TYPES.get(f.suffix)
            if library.safe_name(name) and ctype and f.is_file():
                return self._send(200, f.read_bytes(), ctype)
            return self._missing()
        if not self._auth(qs):
            return self._send(403, "forbidden", "text/plain")
        if p == "/":
            html = (HERE / "ui" / "index.html").read_text(encoding="utf-8")
            return self._send(200, html, "text/html; charset=utf-8")
        if p == "/api/guides":
            return self._json(library.list_guides(
                STORAGE, q=qs.get("q", [""])[0],
                bookmarked_only=qs.get("bookmarked", [""])[0] == "1"))
        if p == "/api/pages":
            return self._json(library.list_pages(STORAGE))
        m = _PAGE_RE.fullmatch(p)
        if m and m.group(2) in (None, "doc"):
            pid = unquote(m.group(1))
            if m.group(2) == "doc":
                d = page_doc(pid)
                if d == 409:
                    return self._send(409, "redacting", "text/plain")
                return self._json(d) if isinstance(d, dict) else self._missing()
            page = library.read_page(STORAGE, pid)
            if page is None:
                return self._missing()
            guides = {}
            for s in page["sections"]:
                if s["type"] == "guide":
                    g = library.read_guide(STORAGE / s["guide"])
                    guides[s["guide"]] = {"title": g.get("title", "")} if g else None
            return self._json({**page, "guides": guides})
        if p == "/api/trash":
            return self._json(library.list_trash(STORAGE))
        if p == "/api/status":
            return self._json(rec_status())
        if p == "/api/settings":
            return self._json({**library.load_settings(STORAGE),
                               "storage": str(STORAGE),
                               "redact_error": redact.available()})
        m = _GUIDE_RE.fullmatch(p)
        if m and not m.group(2):
            g = guide_for_page(unquote(m.group(1)))
            if g == 409:
                return self._send(409, "redacting", "text/plain")
            return self._json(g) if isinstance(g, dict) else self._missing()
        if p.startswith("/img/"):
            parts = [unquote(x) for x in p[len("/img/"):].split("/", 1)]
            if len(parts) == 2 and library.safe_id(parts[0]) \
                    and library.safe_name(parts[1]):
                f = STORAGE / parts[0] / parts[1]
                ext = f.suffix.lower().lstrip(".").replace("jpeg", "jpg")
                if f.is_file() and ext in library.IMAGE_MIME:
                    return self._send(200, f.read_bytes(),
                                      library.IMAGE_MIME[ext])
            return self._send(404, "no image", "text/plain")
        return self._missing()

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._auth(qs):
            return self._send(403, "forbidden", "text/plain")
        p = u.path
        length = int(self.headers.get("Content-Length", 0))
        if p.endswith("/image") and length > library.MAX_IMAGE:
            self.close_connection = True  # body left unread
            return self._send(413, "too large", "text/plain")
        body = self.rfile.read(length) if length else b""
        if p == "/api/start":
            start_rec_ui()
            return self._json({})
        if p == "/api/pause":
            pause_ui()
            return self._json({"paused": REC.paused})
        if p == "/api/stop":
            guide = stop_rec_ui()
            return self._json({"guide": guide["id"] if guide else None})
        if p in ("/api/monitor", "/api/flash"):
            try:
                i = int(qs.get("i", [""])[0])
            except ValueError:
                return self._send(400, "bad monitor", "text/plain")
            (select_mon_ui if p == "/api/monitor" else flash_ui)(i)
            return self._json({})
        if p == "/api/settings":
            data = _obj(body)
            if data is None or not _settings_ok(data):
                return self._send(400, "bad settings", "text/plain")
            return self._json(library.save_settings(STORAGE, **data))
        if p == "/api/open-folder":
            os.startfile(STORAGE)
            return self._json({})
        if p == "/api/show":
            show_main()
            return self._json({})
        if p == "/api/trash/empty":
            return self._json({"purged": library.empty_trash(STORAGE, recycle)})
        if p == "/api/pages":
            data = _obj(body)
            if data is None or not isinstance(data.get("title"), str):
                return self._send(400, "bad page", "text/plain")
            return self._json(library.create_page(STORAGE, data["title"].strip()))
        m = _PAGE_RE.fullmatch(p)
        if m and m.group(2) != "doc":
            pid, action = unquote(m.group(1)), m.group(2)
            if library.read_page(STORAGE, pid) is None:
                return self._missing()
            if action == "export":
                fmt = qs.get("format", ["html"])[0]
                if fmt not in EXPORT_TYPES:
                    return self._send(400, "bad format", "text/plain")
                return self._json(export_page(pid, fmt, body))
            if action == "delete":
                return self._json({}) if library.delete_page(STORAGE, pid) else self._missing()
            data = _obj(body)
            if data is None:
                return self._send(400, "bad json", "text/plain")
            if action == "add":
                r = library.add_guide_to_page(STORAGE, pid, str(data.get("guide", "")))
                return self._json({"result": r}) if r else self._missing()
            return self._json({}) if library.save_page(STORAGE, pid, data) else \
                self._send(400, "bad page", "text/plain")
        m = _TRASH_RE.fullmatch(p)
        if m:
            gid, action = unquote(m.group(1)), m.group(2)
            ok = library.restore_guide(STORAGE, gid) if action == "restore" \
                else library.purge_guide(STORAGE, gid, recycle)
            return self._json({}) if ok else self._missing()
        m = _GUIDE_RE.fullmatch(p)
        if not m:
            return self._missing()
        gid, action = unquote(m.group(1)), m.group(2)
        if not library.safe_id(gid) or not (STORAGE / gid).is_dir():
            return self._missing()
        if gid in REDACT_BUSY:  # its auto-redaction pass is still writing it
            return self._send(409, "redacting", "text/plain")
        if action == "delete":
            ok = library.trash_guide(STORAGE, gid)
            return self._json({}) if ok else self._send(409, "conflict",
                                                         "text/plain")
        if action == "duplicate":
            new = library.duplicate_guide(STORAGE, gid)
            return self._json({"id": new}) if new else self._missing()
        if action == "export":
            fmt = qs.get("format", ["html"])[0]
            if fmt not in EXPORT_TYPES:
                return self._send(400, "bad format", "text/plain")
            return self._json(export_guide(gid, fmt, body))
        if action == "redact":
            return self._redact(gid, _obj(body))
        if action == "image":
            name = library.add_image(STORAGE, gid, body)
            return self._json({"image": name}) if name else \
                self._send(400, "bad image", "text/plain")
        if action == "download":
            kind = library.image_kind(body)
            if kind not in ("png", "gif"):
                return self._send(400, "bad image", "text/plain")
            n = qs.get("n", [""])[0]
            return self._json(download_image(gid, n if n.isdigit() else "", kind, body))
        data = _obj(body)
        if data is None:
            return self._send(400, "bad json", "text/plain")
        if action == "meta":
            ok = library.update_meta(
                STORAGE, gid, title=data.get("title"),
                bookmarked=data.get("bookmarked"))
        else:
            ok = library.save_guide(STORAGE, gid, data)
        return self._json({}) if ok else self._send(400, "rejected",
                                                     "text/plain")


def _obj(body: bytes) -> dict | None:
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _settings_ok(d: dict) -> bool:
    """What the pages may change in settings.json; anything else is a 400."""
    strs = lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)
    checks = {"view": lambda v: v in ("grid", "list"),
              "redact_on": lambda v: isinstance(v, bool),
              "redact_rules": lambda v: strs(v) and set(v) <= set(redact.RULES),
              "redact_custom": strs}
    return bool(d) and all(k in checks and checks[k](v) for k, v in d.items())


REC = None
OV = None
WINDOW = None
QUITTING = False
PORT = 0
refresh_state = lambda: None
GUIDE_SEQ = 0          # bumps on every stop that produced a guide
LAST_GUIDE = None      # id of that guide; open pages navigate to it
# Auto-redaction gate: a guide whose pass is running answers 409 on every
# route, so nothing can open, save or export it before its blurs are in.
REDACT_LOCK = threading.Lock()
REDACT_BUSY: dict[str, list[int]] = {}  # gid -> [done, total]
REDACT_NOTES: dict[str, str] = {}       # gid -> what its page says next time it opens
_HWND = None
_MUTEX = None


def main_hwnd():
    global _HWND
    if not _HWND:
        _HWND = recorder.find_main_window()
    return _HWND


def panel_state() -> dict:
    return {"recording": REC.recording, "paused": REC.paused, **REC.live()}


def show_main():
    if WINDOW is None:
        return
    WINDOW.show()
    h = main_hwnd()
    if h and user32.IsIconic(h):
        user32.ShowWindowAsync(h, recorder.SW_RESTORE)
    if h:
        user32.SetForegroundWindow(h)


def start_rec_ui():
    if not REC.start_recording():
        return
    OV.toast(REC.monitor_rect(), "Start Record")
    h = main_hwnd()
    recorder.set_capture_excluded(h, True)
    # Collapse into the panel unless the window sits on another monitor,
    # where it already shows the live list without covering the work.
    # A window hidden in the tray counts as not shown.
    shown = bool(h) and user32.IsWindowVisible(h) and not user32.IsIconic(h)
    if not (shown and not REC.window_on_selected(h)):
        if shown:
            user32.ShowWindowAsync(h, recorder.SW_MINIMIZE)
        m = REC.monitors[REC.selected]
        OV.show_panel(m["work"], panel_state, pause_ui, stop_rec_ui)
    refresh_state()


def stop_rec_ui():
    guide = REC.stop_recording()
    OV.hide_panel()
    h = main_hwnd()
    recorder.set_capture_excluded(h, False)
    if guide:
        if guide.get("redact_pending") and _claim(guide["id"]):
            threading.Thread(target=_redact_then_open, args=(guide,),
                             daemon=True).start()
        else:
            _open_new(guide)
        show_main()
    elif h and user32.IsWindowVisible(h) and user32.IsIconic(h):
        user32.ShowWindowAsync(h, recorder.SW_RESTORE)
    refresh_state()
    return guide


def _claim(gid: str) -> bool:
    with REDACT_LOCK:
        if gid in REDACT_BUSY:
            return False
        REDACT_BUSY[gid] = [0, 0]
        return True


def _redact_pass(guide: dict):
    """Run a claimed guide's pass, leave a note for its page, release it.
    A guide that could not be checked at all stays redact_pending, so the
    next open tries again (and warns again)."""
    gid, note = guide["id"], None
    try:
        err = redact.available()
        if err:
            note = f"ไม่ได้ซ่อนข้อมูลอัตโนมัติ: {err} ตรวจภาพเองก่อนส่ง"
        else:
            cfg = library.load_settings(STORAGE)
            failed = redact.redact_guide(
                STORAGE, guide, cfg["redact_rules"], cfg["redact_custom"],
                lambda done, total: REDACT_BUSY.__setitem__(gid, [done, total]))
            if failed:
                note = (f"ซ่อนข้อมูลไม่สำเร็จ {len(failed)} ภาพ (ขั้นที่ "
                        f"{', '.join(map(str, failed))}) ตรวจเองก่อนส่ง")
    except Exception:
        note = "ซ่อนข้อมูลอัตโนมัติไม่สำเร็จ ตรวจภาพเองก่อนส่ง"
    finally:
        if note:
            REDACT_NOTES[gid] = note
        with REDACT_LOCK:
            REDACT_BUSY.pop(gid, None)


def _redact_then_open(guide: dict):
    _redact_pass(guide)
    _open_new(guide)


def _open_new(guide: dict):
    global GUIDE_SEQ, LAST_GUIDE
    # the page sees guide_seq change and opens the new guide in edit mode
    LAST_GUIDE, GUIDE_SEQ = guide["id"], GUIDE_SEQ + 1
    refresh_state()


def guide_for_page(gid: str) -> dict | int:
    """GET /api/guide/<id>: 409 while its pass runs; a guide left unchecked
    (app quit mid-pass) is checked first. Carries its note once."""
    if not library.safe_id(gid):
        return 404
    if gid in REDACT_BUSY:
        return 409
    g = library.read_guide(STORAGE / gid)
    if g is None:
        return 404
    if g.get("redact_pending"):
        if not _claim(gid):
            return 409
        _redact_pass(g)
        g = library.read_guide(STORAGE / gid)
        if g is None:
            return 404
    note = REDACT_NOTES.pop(gid, None)
    return {**g, "redact_note": note} if note else g


def pause_ui():
    REC.pause()
    refresh_state()


def _valid_monitor(i: int) -> bool:
    return not REC.recording and 0 <= i < len(REC.monitors)


def select_mon_ui(i: int):
    if not _valid_monitor(i):
        return
    REC.set_monitor(i)
    OV.flash(REC.monitor_rect(i))
    library.save_settings(STORAGE, monitor=REC.monitors[i]["name"])


def flash_ui(i: int):
    if _valid_monitor(i):
        OV.flash(REC.monitor_rect(i))


def quit_app():
    global QUITTING
    QUITTING = True
    if REC.recording:
        REC.stop_recording()  # saves the guide
    OV.hide_panel()
    WINDOW.destroy()


def rec_status() -> dict:
    mons = [{"index": m["index"], "w": m["right"] - m["left"],
             "h": m["bottom"] - m["top"], "primary": m["primary"]}
            for m in REC.monitors]
    return {"recording": REC.recording, "paused": REC.paused,
            "selected": REC.selected, "monitors": mons,
            "hooks_ok": REC.hooks_ok, "hook_error": REC.hook_error,
            "guide_seq": GUIDE_SEQ, "last_guide": LAST_GUIDE,
            "redacting": [sum(x) for x in zip(*REDACT_BUSY.values())] or None,
            **REC.live()}


def _file_title(gid: str) -> str | None:
    g = library.read_guide(STORAGE / gid)
    if g is None:
        return None
    return exporters.safe_title(g.get("title") or "")


SAVE_FAILED = {"saved": None, "error": "บันทึกไฟล์ไม่ได้"}


def save_as(filename: str, data: bytes, file_type: str) -> str | None:
    """Native Save As for bytes the page made; None when cancelled, OSError
    when the chosen place can't be written."""
    if WINDOW is None:
        return None
    # file_type stays ASCII: pywebview's filter parser rejects Thai marks
    res = WINDOW.create_file_dialog(webview.FileDialog.SAVE,
                                    save_filename=filename,
                                    file_types=(file_type,))
    path = res[0] if isinstance(res, (list, tuple)) and res else res
    if not path:
        return None
    Path(path).write_bytes(data)
    return str(path)


# format -> (extension, Save As filter; ASCII only)
EXPORT_TYPES = {"html": ("html", "HTML (*.html)"), "pdf": ("pdf", "PDF (*.pdf)"),
                "md": ("zip", "ZIP (*.zip)"), "docx": ("docx", "Word (*.docx)")}


def export_guide(gid: str, fmt: str, body: bytes) -> dict:
    title = _file_title(gid)
    if title is None:
        return {"saved": None, "error": "ไม่พบคู่มือนี้"}
    return _export(title, fmt, body, lambda: library.read_guide(STORAGE / gid), gid)


def export_page(pid: str, fmt: str, body: bytes) -> dict:
    """A page compiled into one document; deleted guides are left out ("skipped")."""
    page = library.read_page(STORAGE, pid)
    doc = page_doc(pid) if page else 404
    if doc == 409:
        return {"saved": None, "error": "คู่มือใน Page นี้กำลังซ่อนข้อมูลอยู่ ลองใหม่อีกครั้ง"}
    if not isinstance(doc, dict):
        return {"saved": None, "error": "ไม่พบ Page นี้"}
    out = _export(exporters.safe_title(page["title"]), fmt, body, lambda: doc, "")
    if doc["missing"] and out.get("saved"):
        out["skipped"] = doc["missing"]
    return out


def page_doc(pid: str) -> dict | int:
    """The page compiled for view/export. Guides go through guide_for_page, so
    one being redacted makes the page wait (409) and a pending one is checked."""
    page = library.read_page(STORAGE, pid)
    if page is None:
        return 404
    guides, notes = {}, []
    for s in page["sections"]:
        if s["type"] == "guide":
            g = guide_for_page(s["guide"])
            if g == 409:
                return 409
            guides[s["guide"]] = g if isinstance(g, dict) else None
            if isinstance(g, dict) and g.get("redact_note"):  # never lose a redaction warning
                notes.append(f"{g.get('title') or s['guide']}: {g['redact_note']}")
    doc, missing = library.compile_page(page, guides)
    return {**doc, "missing": missing, "redact_notes": notes}


def _export(title: str, fmt: str, body: bytes, load, gid: str) -> dict:
    """{"saved": path | None} (None = cancelled), plus "error" when it failed.
    html/pdf: body is the export HTML. md/docx: body is the finished pictures
    (see _export_images); text comes from load() -- the guide or compiled page."""
    ext, filt = EXPORT_TYPES[fmt]
    try:
        if fmt == "html":
            data = body
        elif fmt == "pdf":
            data = print_pdf(body.decode("utf-8"))
        else:
            guide = load()
            images, missing = _export_images(gid, guide, body)
            data = (exporters.build_markdown if fmt == "md" else exporters.build_docx)(guide, images)
    except Exception:
        return {"saved": None, "error": "สร้าง PDF ไม่สำเร็จ" if fmt == "pdf" else "สร้างไฟล์ไม่สำเร็จ"}
    try:
        out = {"saved": save_as(f"{title}.{ext}", data, filt)}
    except OSError:
        return dict(SAVE_FAILED)
    if fmt in ("md", "docx") and missing:
        out["missing"] = missing  # exported without these pictures; the page says so
    return out


def _export_images(gid: str, guide: dict, body: bytes) -> tuple[dict, list[int]]:
    """The page's finished pictures for md/docx -> ({step id: (ext, bytes)},
    step numbers whose picture is unusable). body = one JSON line
    {"images": [{"id", "ext": "png", "size"} | {"id", "ext": "gif"}]} then the
    PNG bytes back to back -- binary, so a big guide never becomes one giant
    base64 string. A GIF is read from the guide folder, never from the request."""
    head, _, rest = body.partition(b"\n")
    try:
        index = json.loads(head)["images"]
        assert isinstance(index, list)
    except Exception:
        index = []
    nums, sec = {}, None  # step id -> its number; on a page "<guide> ขั้นที่ n"
    for n, s in exporters.numbered(guide):
        if s.get("kind") == "section":
            sec = s.get("text") or ""
        elif n:
            nums[s["id"]] = f"{sec} ขั้นที่ {n}" if sec is not None else n
    steps = {s["id"]: s for s in guide["steps"]}
    out, missing, pos = {}, [], 0
    for it in index:
        if not isinstance(it, dict) or it.get("id") not in nums:
            continue
        sid, data = it["id"], None
        if it.get("ext") == "gif":
            image = steps[sid].get("image") or ""
            home = STORAGE / (steps[sid].get("gid") or gid)
            f = home / image
            if image.lower().endswith(".gif") and library.safe_name(image) \
                    and library.safe_id(home.name) and f.parent == home and f.is_file():
                data = f.read_bytes()
            ext = "gif"
        else:
            size = it.get("size") if isinstance(it.get("size"), int) else -1
            data = rest[pos:pos + size] if 0 <= size <= len(rest) - pos else None
            pos += max(size, 0)
            ext = "png"
        if data and library.image_kind(data) == ext and _decodes(data):
            out[sid] = (ext, data)
        else:
            missing.append(nums[sid])
    return out, missing  # in document order


def _decodes(data: bytes) -> bool:
    from PIL import Image
    try:
        with Image.open(BytesIO(data)) as im:
            im.load()
        return True
    except Exception:
        return False


def print_pdf(html: str) -> bytes:
    """The export HTML as an A4 PDF, printed by WebView2 in a hidden window of
    our own (same text engine as the app, so Thai shapes right; no browser)."""
    tmp = STORAGE / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(8)
    src, pdf = tmp / f"print-{key}.html", tmp / f"print-{key}.pdf"
    src.write_text(html, encoding="utf-8")
    win = None
    try:
        # focus=False: never activates, so the hidden window can't take focus
        # or flash a taskbar button while pywebview shows-then-hides it
        win = webview.create_window("StepCap print", url=src.as_uri(), hidden=True, focus=False)
        if not win.events.loaded.wait(30):
            raise RuntimeError("print page did not load")
        end = time.time() + 30
        while not win.evaluate_js("[...document.images].every(i => i.complete)"):
            if time.time() > end:
                raise RuntimeError("print images did not load")
            time.sleep(0.1)
        # an empty title would make WebView2 title the PDF with our temp file name
        win.evaluate_js("document.title.trim() || (document.title = 'StepCap'); 1")
        from System import Action
        from System.Threading.Tasks import Task, TaskStatus
        done, res = threading.Event(), {}

        def finished(t):
            # faulted or cancelled: Result would throw and leave us waiting
            res["ok"] = t.Status == TaskStatus.RanToCompletion and t.Result
            done.set()

        def go():
            try:
                core = win.native.browser.webview.CoreWebView2
                st = core.Environment.CreatePrintSettings()
                st.PageWidth, st.PageHeight = 8.27, 11.69  # A4, inches
                st.ShouldPrintBackgrounds = True
                st.ShouldPrintHeaderAndFooter = False
                core.PrintToPdfAsync(str(pdf), st).ContinueWith(
                    Action[Task[bool]](finished))
            except Exception:
                done.set()
        win.native.Invoke(Action(go))
        if not done.wait(120) or not res.get("ok") or not pdf.is_file():
            raise RuntimeError("PrintToPdf failed")
        return pdf.read_bytes()
    finally:
        if win is not None:
            win.destroy()
        for f in (src, pdf):
            f.unlink(missing_ok=True)


def download_image(gid: str, n: str, kind: str, data: bytes) -> dict:
    """One step's finished image (PNG, or the original GIF)."""
    title = _file_title(gid)
    if title is None:
        return {"saved": None, "error": "ไม่พบคู่มือนี้"}
    name = f"{title} - ขั้นตอน {n}.{kind}" if n else f"{title}.{kind}"
    try:
        return {"saved": save_as(name, data, f"{kind.upper()} (*.{kind})")}
    except OSError:
        return dict(SAVE_FAILED)


# ---------------------------------------------------------------------------
# Main window (pywebview), single instance, icon
# ---------------------------------------------------------------------------
def single_instance() -> bool:
    global _MUTEX
    key = hashlib.sha1(str(STORAGE).lower().encode()).hexdigest()[:12]
    ctypes.set_last_error(0)
    _MUTEX = kernel32.CreateMutexW(None, False, f"Local\\StepCap-{key}")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def poke_running():
    """Second launch: ask the running StepCap to show its window."""
    try:
        run = json.loads(RUN_FILE.read_text(encoding="utf-8"))
        req = urllib.request.Request(
            f"http://127.0.0.1:{run['port']}/api/show?t={run['token']}",
            data=b"{}")
        urllib.request.urlopen(req, timeout=5).close()
    except Exception:
        pass


def ensure_app_icon(path: Path) -> bool:
    """Make the window/shortcut icon once. Never fatal: a locked or
    unwritable file only costs the custom icon, not the app start."""
    if path.is_file():
        return True
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([8, 8, 248, 248], radius=56,
                            fill=(251, 146, 60, 255))
        d.ellipse([64, 64, 192, 192], outline=(255, 255, 255, 255), width=26)
        img.save(path, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
        return True
    except OSError:
        return False


def set_window_icon(hwnd):
    LR_LOADFROMFILE, WM_SETICON = 0x10, 0x80
    for which, metric in ((0, 49), (1, 11)):  # ICON_SMALL/SM_CXSMICON, BIG/CXICON
        size = user32.GetSystemMetrics(metric)
        hicon = user32.LoadImageW(None, str(ICON_FILE), 1, size, size,
                                  LR_LOADFROMFILE)
        if hicon:
            user32.SendMessageW(hwnd, WM_SETICON, which, hicon)


def on_closing():
    if QUITTING:
        return True
    # hide() Invokes onto the UI thread, which is busy running this handler
    threading.Thread(target=WINDOW.hide, daemon=True).start()
    return False


def allow_session_end():
    """X hides to the tray, but Windows shutdown/sign-out must not be vetoed.
    pywebview's FormClosing handler cancels every close (our on_closing); this
    one runs after it and lets a session end through, saving a recording."""
    from System.Windows.Forms import CloseReason
    from webview.platforms.winforms import BrowserView

    def on_form_closing(sender, e):
        if e.CloseReason == CloseReason.WindowsShutDown:
            if REC.recording:
                REC.stop_recording()  # saves the guide before Windows ends
                OV.hide_panel()
                refresh_state()
            e.Cancel = False

    BrowserView.instances[WINDOW.uid].FormClosing += on_form_closing


def on_shown():
    allow_session_end()
    h = main_hwnd()
    if h:
        set_window_icon(h)


# ---------------------------------------------------------------------------
# Tray
# ---------------------------------------------------------------------------
def make_icon_image(color):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, 56, 56], fill=color)
    return img


_COLORS = {"idle": (30, 30, 30, 255), "rec": (220, 40, 40, 255),
           "pause": (230, 190, 40, 255)}


class Tray:
    def __init__(self, rec: Recorder):
        import pystray
        self.pystray = pystray
        self.rec = rec
        self.icon = pystray.Icon("stepcap", make_icon_image(_COLORS["idle"]),
                                 "StepCap", menu=self._menu())

    def _state(self) -> str:
        if not self.rec.recording:
            return "idle"
        return "pause" if self.rec.paused else "rec"

    def _refresh(self):
        self.icon.icon = make_icon_image(_COLORS[self._state()])
        titles = {"idle": "StepCap - ว่าง", "rec": "StepCap - กำลังบันทึก",
                  "pause": "StepCap - พัก"}
        self.icon.title = titles[self._state()]
        self.icon.update_menu()

    def _menu(self):
        p = self.pystray
        mon_items = []
        for m in self.rec.monitors:
            w, h = m["right"] - m["left"], m["bottom"] - m["top"]
            label = f"จอ {m['index'] + 1} ({w}×{h})" + \
                    (" หลัก" if m["primary"] else "")
            mon_items.append(p.MenuItem(
                label, partial(self._pick_monitor, m["index"]),
                checked=partial(self._is_monitor, m["index"]), radio=True))
        return p.Menu(
            p.MenuItem("เปิด StepCap", lambda i: show_main(), default=True),
            p.MenuItem("เลือกจอ", p.Menu(*mon_items)),
            p.MenuItem(lambda i: "หยุดบันทึก" if self.rec.recording
                       else "เริ่มบันทึก", self._toggle),
            p.MenuItem(lambda i: "ทำต่อ" if self.rec.paused else "พักชั่วคราว",
                       self._pause,
                       visible=lambda i: self.rec.recording),
            p.Menu.SEPARATOR,
            p.MenuItem("ออก", lambda i: quit_app()),
        )

    def _is_monitor(self, idx, item=None):
        return self.rec.selected == idx

    def _pick_monitor(self, idx, item=None):
        select_mon_ui(idx)

    def _toggle(self, icon=None, item=None):
        if self.rec.recording:
            stop_rec_ui()
        else:
            start_rec_ui()

    def _pause(self, icon=None, item=None):
        pause_ui()

    def hotkey(self, name: str):
        if name == "toggle":
            self._toggle()
        elif name == "pause" and self.rec.recording:
            self._pause()

    def run(self):
        self.icon.run()


def main():
    global PORT, REC, OV, WINDOW, refresh_state
    if not single_instance():
        poke_running()
        return
    shell32.SetCurrentProcessExplicitAppUserModelID("StepCap")
    for f in (STORAGE / "_tmp").glob("print-*"):  # left by a crash mid-PDF
        f.unlink(missing_ok=True)
    ensure_app_icon(ICON_FILE)

    rec = Recorder(STORAGE)
    rec.set_monitor(recorder.monitor_index(
        rec.monitors, library.load_settings(STORAGE)["monitor"]))
    tray = Tray(rec)
    rec._on_hotkey = tray.hotkey
    REC = rec
    OV = overlay.Overlay()
    refresh_state = tray._refresh
    threading.Thread(target=tray.run, daemon=True).start()
    rec.start_app()

    Handler.protocol_version = "HTTP/1.1"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    PORT = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    library.write_json_atomic(RUN_FILE, {"port": PORT, "token": TOKEN,
                                         "pid": os.getpid()})

    WINDOW = webview.create_window(
        "StepCap", f"http://127.0.0.1:{PORT}/?t={TOKEN}", width=1280,
        height=820, min_size=(900, 600), background_color="#FFFFFF",
        text_select=True)
    WINDOW.events.closing += on_closing
    WINDOW.events.shown += on_shown
    try:
        webview.start(private_mode=True)
    finally:
        tray.icon.stop()
        RUN_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
