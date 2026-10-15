"""Windows-only check: the global hooks install and receive real OS input.
Uses harmless input only (1px mouse move and back, F24). Run: python test_windows.py"""
import ctypes
import json
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

import library
import recorder


class _MI(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KI(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", _MI), ("ki", _KI), ("pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(*specs):
    arr = (_INPUT * len(specs))()
    for i, (kind, val) in enumerate(specs):
        arr[i].type = kind
        if kind == 0:
            arr[i].u.mi = val
        else:
            arr[i].u.ki = val
    return ctypes.windll.user32.SendInput(len(specs), arr,
                                          ctypes.sizeof(_INPUT))


def test_hooks_install_and_fire():
    recorder.set_dpi_aware()
    rec = recorder.Recorder(recorder.default_storage())
    rec.start_app()
    assert rec.hooks_ok, f"hooks failed to install (error {rec.hook_error})"
    mouse, keys = [], []
    rec._handle_mouse = lambda w, x, y: mouse.append(w)
    rec._handle_keydown = lambda vk, scan, rep=False: keys.append(vk)
    rec.recording = True
    _send((0, _MI(1, 0, 0, 0x1, 0, 0)), (0, _MI(-1, 0, 0, 0x1, 0, 0)),
          (1, _KI(0x87, 0, 0, 0, 0)), (1, _KI(0x87, 0, 0x2, 0, 0)))
    time.sleep(0.5)
    assert recorder.WM_MOUSEMOVE in mouse, "mouse hook did not fire"
    assert 0x87 in keys, "keyboard hook did not fire"


def test_write_guide_fields_and_icon():
    with tempfile.TemporaryDirectory() as d:
        rec = recorder.Recorder(Path(d))
        g = rec._write_guide([{"id": "s1", "kind": "click", "text": "t",
                               "app": "python", "exe": sys.executable,
                               "image": None, "crop": None, "markers": []}])
        disk = json.loads((Path(d) / g["id"] / "guide.json")
                          .read_text(encoding="utf-8"))
        assert disk["app"] == "python" and disk["app_icon"] == "app_icon.png"
        assert (Path(d) / g["id"] / "app_icon.png").stat().st_size > 0
        assert disk["updated"] == disk["created"] and disk["bookmarked"] is False
        assert disk["settings"] == library.DEFAULT_SETTINGS
        assert "app" not in disk["steps"][0] and "exe" not in disk["steps"][0]
        g2 = rec._write_guide([{"id": "s2", "kind": "click", "text": "t",
                                "app": "ApplicationFrameHost",
                                "exe": r"C:\Windows\System32\ApplicationFrameHost.exe",
                                "image": None, "crop": None, "markers": []}])
        assert g2["id"] != g["id"] and g2["app_icon"] is None


def _green_share(rect) -> float:
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=rect, all_screens=True).convert("RGB")
    w, h = img.size
    px = [img.getpixel((x, y)) for x in range(0, w, 4) for y in range(0, h, 4)]
    return sum(1 for r, g, b in px if g > 200 and r < 60 and b < 60) / len(px)


def test_app_icon_never_blocks_startup():
    """_app.ico is made once; an unwritable path must not crash startup."""
    import os
    with tempfile.TemporaryDirectory() as d:
        os.environ["STEPCAP_STORAGE"] = d  # keep app's import off the real storage
        import app
        ico = Path(d) / "_app.ico"
        assert app.ensure_app_icon(ico) is True and ico.stat().st_size > 0
        mtime = ico.stat().st_mtime_ns
        assert app.ensure_app_icon(ico) is True
        assert ico.stat().st_mtime_ns == mtime  # not rewritten on every launch
        blocked = Path(d) / "blocked.ico"
        blocked.mkdir()  # stands in for a file another process holds open
        assert app.ensure_app_icon(blocked) is False


def test_webview_excluded_from_capture():
    """A pywebview window (WebView2 content included) vanishes from
    screenshots once set_capture_excluded is on. Owns the main thread."""
    import webview
    res = {}

    def check(win):
        try:
            hwnd = None
            end = time.time() + 15
            while not hwnd and time.time() < end:
                hwnd = recorder.find_main_window("cap-test")
                time.sleep(0.2)
            time.sleep(1.5)  # let WebView2 paint
            r = wintypes.RECT()
            recorder.user32.GetWindowRect(hwnd, ctypes.byref(r))
            inner = (r.left + 40, r.top + 60, r.right - 40, r.bottom - 40)
            res["before"] = _green_share(inner)
            res["set"] = recorder.set_capture_excluded(hwnd, True)
            time.sleep(0.5)
            res["after"] = _green_share(inner)
        finally:
            win.destroy()

    win = webview.create_window(
        "cap-test", html="<body style='margin:0;background:#00ff00'></body>",
        x=100, y=100, width=400, height=300, on_top=True)
    webview.start(check, (win,))
    assert res.get("set"), res
    assert res["before"] >= 0.9, res
    assert res["after"] <= 0.05, res


if __name__ == "__main__":
    import traceback
    sys.stdout.reconfigure(encoding="utf-8")
    # the webview test owns the main thread until it returns, so it runs last
    last = test_webview_excluded_from_capture
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and v is not last] + [last]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
