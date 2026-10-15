"""Windows-only check: the global hooks install and receive real OS input.
Uses harmless input only (1px mouse move and back, F24). Run: python test_windows.py"""
import ctypes
import time
from ctypes import wintypes

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


if __name__ == "__main__":
    test_hooks_install_and_fire()
    print("ok   test_hooks_install_and_fire")
