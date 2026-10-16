"""StepCap recorder: global input capture -> guide steps (Windows only).

Pure step logic lives at the top (importable without Windows), the ctypes/UIA
glue below it. test_steps.py imports only the pure part.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from pathlib import Path

import i18n
from i18n import tr

# ---------------------------------------------------------------------------
# Pure logic (no Windows calls) -- safe to import anywhere
# ---------------------------------------------------------------------------

# Step text is written in the language set when it is recorded. Thai and
# English put the words in different orders, so each has its own tables and
# composing code here instead of going through tr().
_MONTHS = {"th": ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",  # i18n-ok
                  "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."],  # i18n-ok
           "en": ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}

# UIA control type id -> noun for "Click the "name" <noun>" ('' = no noun)
_CONTROL_NOUN = {
    50000: ("ปุ่ม", "button"),             # i18n-ok Button
    50002: ("ช่องเลือก", "checkbox"),      # i18n-ok CheckBox
    50003: ("กล่องเลือก", "dropdown"),     # i18n-ok ComboBox
    50004: ("ช่อง", "field"),              # i18n-ok Edit
    50005: ("ลิงก์", "link"),              # i18n-ok Hyperlink
    50007: ("รายการ", "item"),             # i18n-ok ListItem
    50011: ("เมนู", "menu"),               # i18n-ok MenuItem
    50013: ("ปุ่มตัวเลือก", "option"),     # i18n-ok RadioButton
    50018: ("แท็บ", "tab"),                # i18n-ok Tab
    50019: ("แท็บ", "tab"),                # i18n-ok TabItem
    50024: ("รายการ", "item"),             # i18n-ok TreeItem
    50031: ("ปุ่ม", "button"),             # i18n-ok SplitButton
}

# vk -> display name for special (non-character) keys; the arrows are named
# in Thai here and put into English by key_label
VK_SPECIAL = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
    0x2E: "Delete", 0x24: "Home", 0x23: "End", 0x21: "PageUp",
    0x22: "PageDown", 0x2D: "Insert",
    0x25: "ลูกศรซ้าย", 0x26: "ลูกศรขึ้น", 0x27: "ลูกศรขวา", 0x28: "ลูกศรลง",  # i18n-ok
}
for _i in range(12):  # F1..F12
    VK_SPECIAL[0x70 + _i] = f"F{_i + 1}"
_KEY_EN = {"ลูกศรซ้าย": "Left arrow", "ลูกศรขึ้น": "Up arrow",  # i18n-ok
           "ลูกศรขวา": "Right arrow", "ลูกศรลง": "Down arrow"}  # i18n-ok

_CLICK_VERB = {"click": ("คลิก", "Click"), "rightclick": ("คลิกขวา", "Right-click"),  # i18n-ok
               "doubleclick": ("ดับเบิลคลิก", "Double-click")}  # i18n-ok


def _en() -> bool:
    return i18n.LANG == "en"


def title_stamp(t: float | None = None) -> str:
    """'16 Oct 2026 10:05' (Thai: short Thai month, Buddhist year) for a new
    guide's title."""
    lt = time.localtime(t)
    year = lt.tm_year if _en() else lt.tm_year + 543
    return (f"{lt.tm_mday} {_MONTHS[i18n.LANG][lt.tm_mon]} {year} "
            f"{lt.tm_hour:02d}:{lt.tm_min:02d}")


def control_noun(control_type: int) -> str:
    return _CONTROL_NOUN.get(control_type, ("", ""))[_en()]


def key_label(key: str) -> str:
    """A key or combo ("Ctrl + ลูกศรซ้าย") as shown in the step text."""  # i18n-ok
    if not _en():
        return key
    return " + ".join(_KEY_EN.get(k, k) for k in key.split(" + "))


def compose_click_text(kind: str, name: str, control_type: int, app: str) -> str:
    verb, noun = _CLICK_VERB[kind][_en()], control_noun(control_type)
    name = (name or "").strip()
    where = (f" in {app}" if _en() else f" ใน {app}") if app else ""  # i18n-ok
    if not name:
        return verb + where if _en() else (f"{verb}ใน {app}" if app else verb)  # i18n-ok
    if _en():
        target = f'the "{name}" {noun}' if noun else f'"{name}"'
        return f"{verb} {target}{where}"
    return f'{verb}{noun} "{name}"{where}' if noun else f'{verb}"{name}"{where}'


def monitor_index(monitors: list[dict], name: str | None) -> int:
    """Index of the monitor with that device name; else the primary; else 0."""
    for m in monitors:
        if name and m["name"] == name:
            return m["index"]
    return next((m["index"] for m in monitors if m["primary"]), 0)


def _new_id() -> str:
    return "s" + uuid.uuid4().hex[:8]


class _Typing:
    def __init__(self, field: str, is_password: bool, mask=None):
        self.field = field
        self.is_password = is_password
        self.mask = mask or (lambda t: t)
        self.chars: list[str] = []
        self.ending: str | None = None

    def text(self) -> str:
        en = _en()
        if self.is_password:
            body = "Type a password" if en else "พิมพ์รหัสผ่าน"  # i18n-ok
            if self.field:
                body += f' in the "{self.field}" field' if en else f'ในช่อง "{self.field}"'  # i18n-ok
        else:
            # the field name too: some apps name an edit box after its value
            field = self.mask(self.field)
            where = (f' in the "{field}" field' if en else f' ในช่อง "{field}"') if self.field else ""  # i18n-ok
            typed = self.mask("".join(self.chars))
            body = (f'Type "{typed}"' if en else f'พิมพ์ "{typed}"') + where  # i18n-ok
        if self.ending:
            body += f" then press {self.ending}" if en else f" แล้วกด {self.ending}"  # i18n-ok
        return body

    def finish(self) -> dict:
        kind = "password" if self.is_password else "type"
        return {"id": _new_id(), "kind": kind, "text": self.text()}


class StepBuilder:
    """Turns an ordered input stream into guide steps. Pure + deterministic."""

    def __init__(self, mask=None):
        """mask(typed text) -> text to keep; hides auto-redacted values."""
        self.steps: list[dict] = []
        self._typing: _Typing | None = None
        self._mask = mask

    def _flush(self):
        if self._typing is not None:
            self.steps.append(self._typing.finish())
            self._typing = None

    def add_click(self, kind: str, name: str, control_type: int, app: str,
                  image: str | None = None, marker: dict | None = None,
                  exe: str = "", target: dict | None = None) -> dict:
        self._flush()
        step = {
            "id": _new_id(),
            "kind": kind,
            "text": compose_click_text(kind, name, control_type, app),
            "app": app,
            "exe": exe,
            "image": image,
            "crop": None,
            "markers": [marker] if marker else [],
        }
        if target:
            step["target"] = target
        self.steps.append(step)
        return step

    def add_key(self, char: str | None, special: str | None,
                field: str, is_password: bool):
        if self._typing is not None and (
                self._typing.field != field
                or self._typing.is_password != is_password):
            self._flush()

        if special == "Backspace":
            if self._typing and self._typing.chars:
                self._typing.chars.pop()
            return
        if special in ("Enter", "Tab"):
            if self._typing is None:
                self.steps.append(
                    {"id": _new_id(), "kind": "type", "text": tr("กด {k}", k=key_label(special))})
                return
            self._typing.ending = special
            self._flush()
            return
        if special is not None:  # arrows / Delete / F-keys etc. pressed alone
            self._flush()
            self.steps.append(
                {"id": _new_id(), "kind": "type", "text": tr("กด {k}", k=key_label(special))})
            return

        # normal character
        if self._typing is None:
            self._typing = _Typing(field, is_password, self._mask)
        if char is not None and not self._typing.is_password:
            self._typing.chars.append(char)

    def add_shortcut(self, mods: list[str], keyname: str):
        self._flush()
        combo = " + ".join(mods + [keyname])
        self.steps.append(
            {"id": _new_id(), "kind": "shortcut", "text": tr("กด {k}", k=key_label(combo))})

    def add_note(self, text: str):
        self._flush()
        self.steps.append({"id": _new_id(), "kind": "note", "text": text})

    def pending_text(self) -> str | None:
        """Text of the typing step still in progress (not yet a step)."""
        return self._typing.text() if self._typing is not None else None

    def finish(self) -> list[dict]:
        self._flush()
        return self.steps


# ---------------------------------------------------------------------------
# Windows glue (ctypes hooks + UIA + screenshots)
# ---------------------------------------------------------------------------
import ctypes
import os
from ctypes import wintypes

import library

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t

APP_TITLE = "StepCap"  # the main window's title
WDA_EXCLUDEFROMCAPTURE = 0x11
# apps that only host other apps: their own icon would mislead on a card
HOST_APPS = {"ApplicationFrameHost", "StartMenuExperienceHost"}

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
LLKHF_UP = 0x80
GA_ROOT = 2
SW_MINIMIZE = 6
SW_RESTORE = 9

# modifier virtual-key codes
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_CAPITAL = 0x14
_MOD_VKS = {VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN,
            0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


HOOKPROC = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM,
                            wintypes.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Every call that takes or returns a handle is typed: untyped ctypes calls use
# c_int, which truncates 64-bit handles (that silently broke SetWindowsHookExW).
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE,
                                     wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.WindowFromPoint.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.GetKeyboardLayout.restype = wintypes.HKL
user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
user32.ToUnicodeEx.restype = ctypes.c_int
user32.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT,
                               ctypes.POINTER(ctypes.c_ubyte),
                               ctypes.POINTER(ctypes.c_wchar), ctypes.c_int,
                               wintypes.UINT, wintypes.HKL]
user32.GetDoubleClickTime.restype = wintypes.UINT
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]


def set_dpi_aware():
    # PER_MONITOR_AWARE_V2 so GetMonitorInfo / screenshots use physical pixels.
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except Exception:
            user32.SetProcessDPIAware()


def enum_monitors() -> list[dict]:
    """Physical-pixel rects (full + work area) for each monitor."""
    MONITORINFOF_PRIMARY = 1

    class MONITORINFOEX(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    results: list[dict] = []
    MONENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR,
                                     wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                     wintypes.LPARAM)
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR,
                                       ctypes.POINTER(MONITORINFOEX)]

    def _cb(hmon, hdc, lprc, lparam):
        mi = MONITORINFOEX()
        mi.cbSize = ctypes.sizeof(MONITORINFOEX)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        r, w = mi.rcMonitor, mi.rcWork
        results.append({
            "index": len(results),
            "name": mi.szDevice,
            "left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom,
            "work": (w.left, w.top, w.right, w.bottom),
            "primary": bool(mi.dwFlags & MONITORINFOF_PRIMARY),
        })
        return True

    user32.EnumDisplayMonitors(None, None, MONENUMPROC(_cb), 0)
    return results


def window_title(hwnd) -> str:
    if not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_pid(hwnd) -> int:
    pid = wintypes.DWORD()
    if hwnd:
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    if hwnd:
        user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_rect(hwnd) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) in physical pixels."""
    r = wintypes.RECT()
    if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


# UIA control types a person clicks on as a whole: Button, CheckBox, ComboBox,
# Edit, Hyperlink, ListItem, MenuItem, RadioButton, TabItem, TreeItem,
# DataItem, SplitButton.
CLICKABLE_TYPES = {50000, 50002, 50003, 50004, 50005, 50007, 50011, 50013,
                   50019, 50024, 50029, 50031}


def clickable_ancestor(chain: list[dict]) -> dict:
    """From the hit element up to the window: the first a person would call
    the thing they clicked (so the text inside a button gives the button)."""
    return next((e for e in chain if e["type"] in CLICKABLE_TYPES or e["aid"]),
                chain[0])


def window_center(hwnd) -> tuple[int, int] | None:
    r = wintypes.RECT()
    if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return ((r.left + r.right) // 2, (r.top + r.bottom) // 2)


def is_own_window(hwnd) -> bool:
    """StepCap's own windows: everything in this process. The main window is a
    pywebview form here, and a WebView2 child's GA_ROOT is that form."""
    return bool(hwnd) and window_pid(hwnd) == os.getpid()


def find_main_window(title: str = APP_TITLE):
    """This process's top-level window with exactly that title (visible or
    hidden), e.g. the pywebview main window."""
    found = []
    me = os.getpid()

    def _cb(hwnd, _):
        if window_pid(hwnd) == me and window_title(hwnd) == title:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found[0] if found else None


def set_capture_excluded(hwnd, on: bool) -> bool:
    """Hide (or unhide) one of our windows from screenshots."""
    if not hwnd:
        return False
    return bool(user32.SetWindowDisplayAffinity(
        hwnd, WDA_EXCLUDEFROMCAPTURE if on else 0))


def window_info(hwnd) -> tuple[str, str, str]:
    """(window title, app name without .exe, exe full path) for a window."""
    title = window_title(hwnd)
    exe = ""
    h = kernel32.OpenProcess(0x1000, False, window_pid(hwnd))  # QUERY_LIMITED
    if h:
        try:
            size = wintypes.DWORD(260)
            pbuf = ctypes.create_unicode_buffer(260)
            if kernel32.QueryFullProcessImageNameW(h, 0, pbuf,
                                                   ctypes.byref(size)):
                exe = pbuf.value
        finally:
            kernel32.CloseHandle(h)
    return title, (Path(exe).stem if exe else ""), exe


def extract_icon(exe: str, out: Path) -> bool:
    """Save the exe's icon as a PNG (pythonnet, already present for pywebview)."""
    try:
        import clr
        clr.AddReference("System.Drawing")
        from System.Drawing import Icon
        from System.Drawing.Imaging import ImageFormat
        Icon.ExtractAssociatedIcon(exe).ToBitmap().Save(str(out), ImageFormat.Png)
        return out.is_file()
    except Exception:
        return False


def _discard(path: str | None):
    if path:
        Path(path).unlink(missing_ok=True)


class _UIA:
    """Lazy UI Automation wrapper; each instance is bound to its own thread."""

    def __init__(self):
        import comtypes
        import comtypes.client
        comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
        self._uia = comtypes.client.CreateObject(CUIAutomation,
                                                 interface=IUIAutomation)

    def at_point(self, x: int, y: int) -> tuple[str, int]:
        try:
            el = self._uia.ElementFromPoint(wintypes.POINT(x, y))
            return (el.CurrentName or "", el.CurrentControlType)
        except Exception:
            return ("", 0)

    def target_at(self, x: int, y: int) -> dict:
        """{"name", "type", "aid"} of the clickable element under the point,
        walking up from the hit element to (not including) the window."""
        try:
            el = self._uia.ElementFromPoint(wintypes.POINT(x, y))
            walker = self._uia.ControlViewWalker
            root = self._uia.GetRootElement()
            chain = []
            while el and len(chain) < 12:
                parent = walker.GetParentElement(el)
                if not parent or self._uia.CompareElements(parent, root):
                    break  # el is the top-level window itself
                chain.append({"name": el.CurrentName or "",
                              "type": el.CurrentControlType,
                              "aid": el.CurrentAutomationId or ""})
                el = parent
            return clickable_ancestor(chain) if chain else {}
        except Exception:
            return {}

    # only these control types contribute a "ในช่อง ..." label; others (e.g.
    # a top-level window) would otherwise dump the window title into the step.
    _EDITABLE = {50003, 50004, 50030}  # ComboBox, Edit, Document

    def focused_field(self) -> tuple[str, bool]:
        try:
            el = self._uia.GetFocusedElement()
            is_pw = bool(el.CurrentIsPassword)
            name = (el.CurrentName or "") if el.CurrentControlType in \
                self._EDITABLE else ""
            return (name, is_pw)
        except Exception:
            return ("", False)


class Recorder:
    """Installs global hooks, builds a guide, writes it to disk on stop."""

    DRAG_PX = 10

    def __init__(self, storage_dir: Path, on_hotkey=None):
        self.storage = storage_dir
        self.monitors = enum_monitors()
        self.selected = next((m["index"] for m in self.monitors
                              if m["primary"]), 0)
        self.recording = False
        self.paused = False
        self.hooks_ok = False
        self.hook_error = 0
        self._on_hotkey = on_hotkey  # callback(name): "toggle" | "pause"
        self.on_guide_click = None  # Guide Me: callback(button, x, y) while not recording

        self._lock = threading.Lock()
        self._hooks_ready = threading.Event()
        self._builder: StepBuilder | None = None
        self._queue: queue.Queue = queue.Queue()
        self._kbstate = (ctypes.c_ubyte * 256)()
        self._down_pt: tuple[int, int] | None = None
        self._down_button: str | None = None
        self._is_drag = False
        self._pending = None  # worker-owned: capture waiting for its mouse-up
        self._last_click: dict | None = None  # for double-click merge
        self._last_click_t = 0.0

        self._kb_proc = HOOKPROC(self._kb_cb)
        self._ms_proc = HOOKPROC(self._ms_cb)
        self._hook_thread = threading.Thread(target=self._run_hooks,
                                             daemon=True)
        self._worker_thread = threading.Thread(target=self._run_worker,
                                               daemon=True)

    # -- lifecycle -----------------------------------------------------------
    def start_app(self):
        self._worker_thread.start()
        self._hook_thread.start()
        self._hooks_ready.wait(3)

    def set_monitor(self, index: int):
        self.selected = index

    def monitor_rect(self, index: int | None = None) -> tuple[int, int, int, int]:
        m = self.monitors[self.selected if index is None else index]
        return (m["left"], m["top"], m["right"], m["bottom"])

    def start_recording(self) -> bool:
        with self._lock:
            if self.recording:
                return False
            for f in (self.storage / "_tmp").glob("*.png"):
                _discard(str(f))
            cfg = library.load_settings(self.storage)
            mask = None
            self._redact_on = cfg["redact_on"]
            if cfg["redact_on"]:
                import redact
                rules, custom = cfg["redact_rules"], cfg["redact_custom"]
                mask = lambda t: redact.mask_text(t, rules, custom)
            self._builder = StepBuilder(mask)
            self.paused = False
            self._last_click = None
            self.recording = True
            return True

    def pause(self):
        if self.recording:
            self.paused = not self.paused

    def stop_recording(self) -> dict | None:
        with self._lock:
            if not self.recording:
                return None
            self.recording = False
            self.paused = False
            self._queue.join()
            builder, self._builder = self._builder, None
            if self._pending:
                _discard(self._pending[6])
                self._pending = None
        steps = builder.finish() if builder else []
        if not steps:
            return None
        return self._write_guide(steps)

    def live(self) -> dict:
        """Snapshot of the steps captured so far, for the live list."""
        b = self._builder
        if b is None:
            return {"steps": [], "pending": None}
        return {"steps": [{"kind": s["kind"], "text": s["text"]}
                          for s in list(b.steps)],
                "pending": b.pending_text()}

    def window_on_selected(self, hwnd) -> bool:
        c = window_center(hwnd)
        return c is not None and self._in_selected(*c)

    def _write_guide(self, steps: list[dict]) -> dict:
        import shutil
        gid = library.new_id(self.storage)
        first = next((s for s in steps if s.get("app")), None)
        app = first["app"] if first else "StepCap"
        exe = first.get("exe", "") if first else ""
        folder = self.storage / gid
        folder.mkdir(parents=True, exist_ok=True)
        for s in steps:
            src = s.get("image")
            if src and Path(src).exists():
                dst = folder / f"{s['id']}.png"
                try:
                    shutil.move(src, dst)
                    s["image"] = dst.name
                except Exception:
                    s["image"] = None
            else:
                s["image"] = None
            s.pop("app", None)
            s.pop("exe", None)
        icon = None
        if exe and app not in HOST_APPS and                 extract_icon(exe, folder / "app_icon.png"):
            icon = "app_icon.png"
        now = library.now_iso()
        guide = {
            "id": gid,
            "title": f"{app} - {title_stamp()}",
            "created": now,
            "updated": now,
            "bookmarked": False,
            "app": app,
            "app_icon": icon,
            "settings": dict(library.DEFAULT_SETTINGS),
            "steps": steps,
        }
        if getattr(self, "_redact_on", False):
            # cleared by redact.redact_guide; until then the app won't show it
            guide["redact_pending"] = True
        library.write_json_atomic(folder / "guide.json", guide)
        return guide

    # -- hook thread ---------------------------------------------------------
    def _run_hooks(self):
        hmod = kernel32.GetModuleHandleW(None)
        self._kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc,
                                                 hmod, 0)
        self._ms_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_proc,
                                                 hmod, 0)
        self.hooks_ok = bool(self._kb_hook and self._ms_hook)
        if not self.hooks_ok:
            self.hook_error = ctypes.get_last_error()
        self._hooks_ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _held_mods(self) -> list[str]:
        mods = []
        if self._kbstate[VK_CONTROL] & 0x80:
            mods.append("Ctrl")
        if self._kbstate[VK_MENU] & 0x80:
            mods.append("Alt")
        if self._kbstate[VK_SHIFT] & 0x80:
            mods.append("Shift")
        if (self._kbstate[VK_LWIN] & 0x80) or (self._kbstate[VK_RWIN] & 0x80):
            mods.append("Win")
        return mods

    def _kb_cb(self, nCode, wParam, lParam):
        if nCode == 0:
            kb = ctypes.cast(lParam,
                             ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            is_up = bool(kb.flags & LLKHF_UP)
            vk = kb.vkCode
            repeat = not is_up and bool(self._kbstate[vk] & 0x80)
            self._update_kbstate(vk, is_up)
            if not is_up:
                self._handle_keydown(vk, kb.scanCode, repeat)
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _update_kbstate(self, vk: int, is_up: bool):
        if vk == VK_CAPITAL and not is_up:
            self._kbstate[VK_CAPITAL] ^= 0x01  # toggle
        bit = 0x00 if is_up else 0x80
        self._kbstate[vk] = (self._kbstate[vk] & 0x01) | bit
        # mirror specific L/R modifiers onto the generic vk ToUnicodeEx reads
        if vk in (0xA0, 0xA1):
            self._kbstate[VK_SHIFT] = bit
        elif vk in (0xA2, 0xA3):
            self._kbstate[VK_CONTROL] = bit
        elif vk in (0xA4, 0xA5):
            self._kbstate[VK_MENU] = bit

    def _handle_keydown(self, vk: int, scan: int, repeat: bool = False):
        # hotkeys work even when not recording
        ctrl = self._kbstate[VK_CONTROL] & 0x80
        alt = self._kbstate[VK_MENU] & 0x80
        if ctrl and alt and vk in (ord("R"), ord("P")):
            if self._on_hotkey and not repeat:
                # off the hook thread: Windows drops a hook that answers slowly
                name = "toggle" if vk == ord("R") else "pause"
                threading.Thread(target=self._on_hotkey, args=(name,),
                                 daemon=True).start()
            return
        if not self.recording or self.paused or vk in _MOD_VKS:
            return
        fg = user32.GetForegroundWindow()
        if is_own_window(fg) or not self.window_on_selected(fg):
            return

        mods = self._held_mods()
        special = VK_SPECIAL.get(vk)
        if ("Ctrl" in mods) or ("Alt" in mods) or ("Win" in mods):
            keyname = special or (chr(vk) if 0x30 <= vk <= 0x5A else f"VK{vk}")
            use_mods = [m for m in mods if m != "Shift"] or mods
            self._queue.put(("shortcut", use_mods, keyname))
            return
        if special:
            self._queue.put(("key", None, special))
            return
        char = self._translate(vk, scan)
        if char:
            self._queue.put(("key", char, None))

    def _translate(self, vk: int, scan: int) -> str | None:
        tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),
                                              None)
        hkl = user32.GetKeyboardLayout(tid)
        buf = (ctypes.c_wchar * 8)()
        n = user32.ToUnicodeEx(vk, scan, self._kbstate, buf, 8, 0, hkl)
        if n >= 1:
            ch = buf[0]
            return ch if ch >= " " else None
        return None  # ponytail: dead keys dropped; combine path not handled

    # -- mouse hook ----------------------------------------------------------
    def _ms_cb(self, nCode, wParam, lParam):
        if nCode == 0 and (self.on_guide_click or self.recording and not self.paused):
            ms = ctypes.cast(lParam,
                             ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if self.recording:
                if not self.paused:
                    self._handle_mouse(wParam, ms.pt.x, ms.pt.y)
            else:
                self._guide_hook(wParam, ms.pt.x, ms.pt.y)
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _guide_hook(self, wParam, x, y):
        """Guide Me watches presses outside StepCap; the callback only queues."""
        cb = self.on_guide_click
        if cb is None or self.recording or wParam not in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
            return
        if is_own_window(user32.GetAncestor(
                user32.WindowFromPoint(wintypes.POINT(x, y)), GA_ROOT)):
            return
        cb("right" if wParam == WM_RBUTTONDOWN else "left", x, y)

    def _in_selected(self, x: int, y: int) -> bool:
        m = self.monitors[self.selected]
        return m["left"] <= x < m["right"] and m["top"] <= y < m["bottom"]

    def _handle_mouse(self, wParam, x, y):
        if wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
            self._down_pt = None
            if not self._in_selected(x, y):
                return
            root = user32.GetAncestor(
                user32.WindowFromPoint(wintypes.POINT(x, y)), GA_ROOT)
            if is_own_window(root):
                return
            self._down_pt = (x, y)
            self._down_button = ("rightclick" if wParam == WM_RBUTTONDOWN
                                 else "click")
            self._is_drag = False
            self._queue.put(("capture", x, y, root))
        elif wParam == WM_MOUSEMOVE and self._down_pt:
            dx = x - self._down_pt[0]
            dy = y - self._down_pt[1]
            if dx * dx + dy * dy > self.DRAG_PX * self.DRAG_PX:
                self._is_drag = True
        elif wParam in (WM_LBUTTONUP, WM_RBUTTONUP):
            if self._down_pt is None:
                return
            self._queue.put(("commit", self._down_button, self._is_drag,
                             time.monotonic()))
            self._down_pt = None

    # -- worker thread -------------------------------------------------------
    def _run_worker(self):
        try:
            uia = _UIA()
        except Exception:
            uia = None
        while True:
            item = self._queue.get()
            try:
                if self._builder is not None:
                    self._process(item, uia)
            except Exception:
                pass
            finally:
                self._queue.task_done()

    def _process(self, item, uia):
        kind = item[0]
        if kind == "key":
            _, char, special = item
            field, is_pw = uia.focused_field() if uia else ("", False)
            self._builder.add_key(char, special, field, is_pw)
        elif kind == "shortcut":
            _, mods, keyname = item
            self._builder.add_shortcut(mods, keyname)
        elif kind == "capture":
            _, x, y, hwnd = item
            name, ct = uia.at_point(x, y) if uia else ("", 0)
            title, app, exe = window_info(hwnd)
            el = uia.target_at(x, y) if uia else {}
            if self._pending:
                _discard(self._pending[6])
            self._pending = (x, y, name, ct, title, app, self._grab(), exe,
                             el, window_rect(hwnd), window_class(hwnd))
        elif kind == "commit":
            _, button, is_drag, t = item
            pend, self._pending = self._pending, None
            if pend is None:
                return
            if is_drag:
                _discard(pend[6])
                return
            self._commit_click(button, pend, t)

    def _grab(self) -> str | None:
        from PIL import ImageGrab
        try:
            img = ImageGrab.grab(bbox=self.monitor_rect(), all_screens=True)
        except Exception:
            return None
        tmp = self.storage / "_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        path = tmp / f"{uuid.uuid4().hex}.png"
        img.save(path, "PNG")
        return str(path)

    def _commit_click(self, button, pend, t: float):
        x, y, name, ct, title, app, img, exe, el, wr, cls = pend
        m = self.monitors[self.selected]
        marker = {"x": x - m["left"], "y": y - m["top"],
                  "color": "#FB923C", "size": 44}
        app_label = app or title

        # double-click merge: second click near the last within dbl-click time
        last = self._last_click
        if (button == "click" and last is not None and last["markers"]
                and t - self._last_click_t
                <= user32.GetDoubleClickTime() / 1000.0):
            lm = last["markers"][0]
            if abs(lm["x"] - marker["x"]) < 8 and abs(lm["y"] - marker["y"]) < 8:
                last["kind"] = "doubleclick"
                last["text"] = compose_click_text(
                    "doubleclick", name, ct, app_label)
                self._last_click_t = t
                _discard(img)
                return

        target = None
        if exe and wr:  # where Guide Me looks for it later; the exe's name only, never its path
            target = {"exe": Path(exe).name, "window": title, "cls": cls,
                      "dx": x - wr[0], "dy": y - wr[1],
                      "name": el.get("name", ""), "type": el.get("type", 0)}
            if el.get("aid"):
                target["aid"] = el["aid"]
        step = self._builder.add_click(button, name, ct,
                                       app_label, image=img, marker=marker,
                                       exe=exe, target=target)
        self._last_click = step
        self._last_click_t = t


def default_storage() -> Path:
    override = os.environ.get("STEPCAP_STORAGE")  # tests only
    return Path(override) if override else Path.home() / "Documents" / "StepCap"
