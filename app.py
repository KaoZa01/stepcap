"""StepCap tray app: global recorder + local editor server.

Run with: pythonw app.py   (or: python app.py for a console)
"""
from __future__ import annotations

import ctypes
import json
import os
import secrets
import shutil
import subprocess
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import overlay
import recorder
from recorder import Recorder, default_storage

recorder.set_dpi_aware()

HERE = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(16)
STORAGE = default_storage()
STORAGE.mkdir(parents=True, exist_ok=True)


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

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._auth(qs):
            return self._send(403, "forbidden", "text/plain")
        p = u.path
        if p == "/":
            html = (HERE / "editor.html").read_text(encoding="utf-8")
            return self._send(200, html, "text/html; charset=utf-8")
        if p == "/api/guides":
            return self._send(200, json.dumps(list_guides(),
                                              ensure_ascii=False))
        if p == "/api/status":
            return self._send(200, json.dumps(rec_status(),
                                              ensure_ascii=False))
        if p.startswith("/api/guide/"):
            gid = p[len("/api/guide/"):]
            f = STORAGE / gid / "guide.json"
            if not _safe(gid) or not f.exists():
                return self._send(404, "not found", "text/plain")
            return self._send(200, f.read_text(encoding="utf-8"))
        if p.startswith("/img/"):
            parts = p[len("/img/"):].split("/", 1)
            if len(parts) == 2 and _safe(parts[0]) and _safe(parts[1]):
                f = STORAGE / parts[0] / parts[1]
                if f.exists():
                    return self._send(200, f.read_bytes(), "image/png")
            return self._send(404, "no image", "text/plain")
        return self._send(404, "not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._auth(qs):
            return self._send(403, "forbidden", "text/plain")
        p = u.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        if p == "/api/start":
            start_rec_ui()
            return self._send(200, "{}")
        if p == "/api/pause":
            pause_ui()
            return self._send(200, json.dumps({"paused": REC.paused}))
        if p == "/api/stop":
            guide = stop_rec_ui(from_page=True)
            return self._send(200, json.dumps(
                {"guide": guide["id"] if guide else None}))
        if p == "/api/monitor":
            i = qs.get("i", [None])[0]
            if i is not None:
                select_mon_ui(int(i))
            return self._send(200, "{}")
        if p.startswith("/api/guide/") and p.endswith("/delete"):
            gid = p[len("/api/guide/"):-len("/delete")]
            folder = STORAGE / gid
            if _safe(gid) and folder.exists():
                recycle(folder)
                return self._send(200, "{}")
            return self._send(404, "not found", "text/plain")
        if p.startswith("/api/guide/"):
            gid = p[len("/api/guide/"):]
            folder = STORAGE / gid
            if not _safe(gid) or not folder.exists():
                return self._send(404, "not found", "text/plain")
            try:
                data = json.loads(body)
            except ValueError:
                return self._send(400, "bad json", "text/plain")
            (folder / "guide.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8")
            return self._send(200, "{}")
        return self._send(404, "not found", "text/plain")


REC = None
OV = None
refresh_state = lambda: None
GUIDE_SEQ = 0          # bumps on every stop that produced a guide
LAST_GUIDE = None      # id of that guide; open pages navigate to it


def panel_state() -> dict:
    return {"recording": REC.recording, "paused": REC.paused, **REC.live()}


def start_rec_ui():
    if not REC.start_recording():
        return
    if OV:
        OV.toast(REC.monitor_rect(), "Start Record")
    # Collapse into the panel unless the editor sits on another monitor,
    # where it already shows the live list without covering the work.
    win = recorder.find_app_window()
    visible_elsewhere = (win and not recorder.user32.IsIconic(win)
                         and not REC.window_on_selected(win))
    if not visible_elsewhere:
        if win and not recorder.user32.IsIconic(win):
            recorder.user32.ShowWindowAsync(win, recorder.SW_MINIMIZE)
        if OV:
            m = REC.monitors[REC.selected]
            OV.show_panel(m["work"], panel_state, pause_ui,
                          lambda: stop_rec_ui())
    refresh_state()


def stop_rec_ui(from_page: bool = False):
    global GUIDE_SEQ, LAST_GUIDE
    guide = REC.stop_recording()
    if OV:
        OV.hide_panel()
    if guide:
        LAST_GUIDE, GUIDE_SEQ = guide["id"], GUIDE_SEQ + 1
    win = recorder.find_app_window()
    if win:
        # open pages see guide_seq change and navigate to the new guide
        if recorder.user32.IsIconic(win):
            recorder.user32.ShowWindowAsync(win, recorder.SW_RESTORE)
    elif guide and not from_page:
        open_editor(guide["id"])
    refresh_state()
    return guide


def pause_ui():
    REC.pause()
    refresh_state()


def select_mon_ui(i):
    if REC.recording:
        return
    REC.set_monitor(i)
    if OV:
        OV.flash(REC.monitor_rect(i))


def rec_status() -> dict:
    mons = [{"index": m["index"], "w": m["right"] - m["left"],
             "h": m["bottom"] - m["top"], "primary": m["primary"]}
            for m in REC.monitors]
    return {"recording": REC.recording, "paused": REC.paused,
            "selected": REC.selected, "monitors": mons,
            "hooks_ok": REC.hooks_ok, "hook_error": REC.hook_error,
            "guide_seq": GUIDE_SEQ, "last_guide": LAST_GUIDE,
            **REC.live()}


def _safe(name: str) -> bool:
    return name != "" and "/" not in name and "\\" not in name \
        and ".." not in name


def list_guides() -> list[dict]:
    out = []
    for folder in STORAGE.iterdir():
        f = folder / "guide.json"
        if folder.is_dir() and f.exists():
            try:
                g = json.loads(f.read_text(encoding="utf-8"))
                out.append({"id": g["id"], "title": g.get("title", g["id"]),
                            "created": g.get("created", ""),
                            "count": len(g.get("steps", []))})
            except Exception:
                pass
    out.sort(key=lambda x: x["created"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Browser launch (Edge app window, fallback default browser)
# ---------------------------------------------------------------------------
def open_editor(gid: str | None = None):
    url = f"http://127.0.0.1:{PORT}/?t={TOKEN}"
    if gid:
        url += f"&guide={gid}"
    for base in (os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("ProgramFiles", "")):
        edge = Path(base) / "Microsoft/Edge/Application/msedge.exe"
        if edge.exists():
            profile = STORAGE / "_browser"
            subprocess.Popen([str(edge), f"--app={url}",
                              f"--user-data-dir={profile}"])
            return
    import webbrowser
    webbrowser.open(url)


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
            p.MenuItem("เลือกจอ", p.Menu(*mon_items)),
            p.MenuItem(lambda i: "หยุดบันทึก" if self.rec.recording
                       else "เริ่มบันทึก", self._toggle),
            p.MenuItem(lambda i: "ทำต่อ" if self.rec.paused else "พักชั่วคราว",
                       self._pause,
                       visible=lambda i: self.rec.recording),
            p.MenuItem("คู่มือทั้งหมด", lambda i: open_editor()),
            p.Menu.SEPARATOR,
            p.MenuItem("ออก", self._quit),
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

    def _quit(self, icon=None, item=None):
        if self.rec.recording:
            self.rec.stop_recording()
        self.icon.stop()

    def hotkey(self, name: str):
        if name == "toggle":
            self._toggle()
        elif name == "pause" and self.rec.recording:
            self._pause()

    def run(self):
        self.icon.run()


def main():
    global PORT, REC, OV, refresh_state
    rec = Recorder(STORAGE)
    tray = Tray(rec)
    rec._on_hotkey = tray.hotkey
    REC = rec
    OV = overlay.Overlay()
    refresh_state = tray._refresh
    rec.start_app()

    Handler.protocol_version = "HTTP/1.1"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    PORT = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    open_editor()  # show the home page on launch
    tray.run()


if __name__ == "__main__":
    main()
