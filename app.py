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
import threading
import urllib.request
from ctypes import wintypes
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import webview

import library
import overlay
import recorder
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
_GUIDE_RE = re.compile(r"/api/guide/([^/]+)(?:/(delete|meta|duplicate|export))?")
_TRASH_RE = re.compile(r"/api/trash/([^/]+)/(restore|purge)")


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
        if p == "/api/trash":
            return self._json(library.list_trash(STORAGE))
        if p == "/api/status":
            return self._json(rec_status())
        if p == "/api/settings":
            return self._json({**library.load_settings(STORAGE),
                               "storage": str(STORAGE)})
        m = _GUIDE_RE.fullmatch(p)
        if m and not m.group(2):
            gid = unquote(m.group(1))
            g = library.read_guide(STORAGE / gid) if library.safe_id(gid) \
                else None
            return self._json(g) if g is not None else self._missing()
        if p.startswith("/img/"):
            parts = [unquote(x) for x in p[len("/img/"):].split("/", 1)]
            if len(parts) == 2 and library.safe_id(parts[0]) \
                    and library.safe_name(parts[1]):
                f = STORAGE / parts[0] / parts[1]
                if f.is_file():
                    return self._send(200, f.read_bytes(), "image/png")
            return self._send(404, "no image", "text/plain")
        return self._missing()

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._auth(qs):
            return self._send(403, "forbidden", "text/plain")
        p = u.path
        length = int(self.headers.get("Content-Length", 0))
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
            if data is None or data.get("view") not in ("grid", "list"):
                return self._send(400, "bad settings", "text/plain")
            return self._json(library.save_settings(STORAGE, view=data["view"]))
        if p == "/api/open-folder":
            os.startfile(STORAGE)
            return self._json({})
        if p == "/api/show":
            show_main()
            return self._json({})
        if p == "/api/trash/empty":
            return self._json({"purged": library.empty_trash(STORAGE, recycle)})
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
        if action == "delete":
            ok = library.trash_guide(STORAGE, gid)
            return self._json({}) if ok else self._send(409, "conflict",
                                                         "text/plain")
        if action == "duplicate":
            new = library.duplicate_guide(STORAGE, gid)
            return self._json({"id": new}) if new else self._missing()
        if action == "export":
            return self._json({"saved": export_guide(gid, body)})
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


REC = None
OV = None
WINDOW = None
QUITTING = False
PORT = 0
refresh_state = lambda: None
GUIDE_SEQ = 0          # bumps on every stop that produced a guide
LAST_GUIDE = None      # id of that guide; open pages navigate to it
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
    global GUIDE_SEQ, LAST_GUIDE
    guide = REC.stop_recording()
    OV.hide_panel()
    h = main_hwnd()
    recorder.set_capture_excluded(h, False)
    if guide:
        # the page sees guide_seq change and opens the new guide in edit mode
        LAST_GUIDE, GUIDE_SEQ = guide["id"], GUIDE_SEQ + 1
        show_main()
    elif h and user32.IsWindowVisible(h) and user32.IsIconic(h):
        user32.ShowWindowAsync(h, recorder.SW_RESTORE)
    refresh_state()
    return guide


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
            **REC.live()}


def export_guide(gid: str, html: bytes) -> str | None:
    """Ask where to save the page's export file; None when cancelled."""
    g = library.read_guide(STORAGE / gid)
    if g is None or WINDOW is None:
        return None
    name = re.sub(r'[\\/:*?"<>|]', "_", g.get("title") or "").strip() or "guide"
    # file_types stays ASCII: pywebview's filter parser rejects Thai marks
    res = WINDOW.create_file_dialog(webview.FileDialog.SAVE,
                                    save_filename=name + ".html",
                                    file_types=("HTML (*.html)",))
    path = res[0] if isinstance(res, (list, tuple)) and res else res
    if not path:
        return None
    Path(path).write_bytes(html)
    return str(path)


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
