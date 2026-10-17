"""Guide Me: walk a person through a guide on the real screen.

The top half is pure (where is this step's target, did that click hit it,
which step is next); the Windows glue below it finds windows and elements,
draws the highlight and docks the side panel.
"""
from __future__ import annotations

import ctypes
import os
import queue
import threading
from ctypes import wintypes
from pathlib import Path

import recorder

CLICKS = {"click", "rightclick", "doubleclick"}
MARKER = 44  # a circle the size of a recorded click marker


def pick_window(wins: list[dict], exe: str, title: str, cls: str = "") -> dict | None:
    """The window of that exe (top-most first): the one titled title, else the
    one of the recorded window class (titles change: folder, tab, document)."""
    same = [w for w in wins if w["exe"].lower() == exe.lower()]
    return next((w for w in same if w["title"] == title),
                next((w for w in same if cls and w.get("cls") == cls),
                     same[0] if same else None))


def nearest(rects: list[tuple], pt: tuple[int, int]) -> tuple | None:
    """The non-empty rect whose centre is closest to pt."""
    ok = [r for r in rects if r[2] > r[0] and r[3] > r[1]]
    return min(ok, key=lambda r: ((r[0] + r[2]) / 2 - pt[0]) ** 2
               + ((r[1] + r[3]) / 2 - pt[1]) ** 2, default=None)


def _circle(cx: int, cy: int, size: int) -> tuple:
    h = size // 2
    return (cx - h, cy - h, cx + h, cy + h)


def resolve(step: dict, find_window, find_elements, origin: tuple[int, int],
            element_at=None) -> dict:
    """Where this step's target is on screen now.
    state: element (box on the found element), approx (where it was: the
    button now at that spot if element_at(pt, hwnd) knows one, else a circle),
    missing (its window isn't open), none (nothing to point at)."""
    res = {"state": "none", "shape": None, "rect": None, "app": ""}
    if step.get("kind") not in CLICKS:
        return res
    t = step.get("target")
    if not t:  # recorded before Guide Me: only the marker, relative to the monitor
        m = (step.get("markers") or [None])[0]
        if not m:
            return res
        return {**res, "state": "approx", "shape": "circle",
                "rect": _circle(origin[0] + m["x"], origin[1] + m["y"], m.get("size", MARKER))}
    w = find_window(t["exe"], t.get("window", ""), t.get("cls", ""))
    if w is None:
        return {**res, "state": "missing", "app": Path(t["exe"]).stem}
    pt = (w["rect"][0] + t["dx"], w["rect"][1] + t["dy"])
    r = nearest(find_elements(w["hwnd"], t.get("aid", ""), t.get("name", ""),
                              t.get("type", 0)), pt)
    if r:
        return {**res, "state": "element", "shape": "box", "rect": r}
    r = element_at(pt, w["hwnd"]) if element_at else None
    if r:  # the whole button counts, not just a marker-sized spot of it
        return {**res, "state": "approx", "shape": "box", "rect": r}
    return {**res, "state": "approx", "shape": "circle", "rect": _circle(*pt, MARKER)}


def hit(res: dict, x: int, y: int, pad: int = 6) -> bool:
    r = res.get("rect")
    if not r or res.get("state") not in ("element", "approx"):
        return False
    if res["shape"] == "box":
        return r[0] - pad <= x <= r[2] + pad and r[1] - pad <= y <= r[3] + pad
    cx, cy, rad = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2, (r[2] - r[0]) / 2 + pad
    return (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad


def button_ok(kind: str, button: str) -> bool:
    return button == ("right" if kind == "rightclick" else "left")


class Session:
    """Which step is current. index == len(steps) means done."""

    def __init__(self, steps: list[dict]):
        self.steps = steps
        self.index = 0

    @property
    def done(self) -> bool:
        return self.index >= len(self.steps)

    def go(self, i: int):
        self.index = max(0, min(i, len(self.steps)))

    def next(self):
        self.go(self.index + 1)

    def back(self):
        self.go(self.index - 1)

    def on_click(self, button: str, x: int, y: int, res: dict) -> bool:
        """A click anywhere: moves on when it hit this step's target."""
        if self.done or not button_ok(self.steps[self.index].get("kind", ""), button) \
                or not hit(res, x, y):
            return False
        self.next()
        return True


PANEL_W = 360
PANEL_TITLE = "StepCap Guide Me"  # also how the app finds the panel's window


def panel_width(dpi: int) -> int:
    """PANEL_W at 100% scale, in the monitor's physical pixels."""
    return round(PANEL_W * dpi / 96)


def panel_rect(work: tuple, width: int, side: str = "right") -> tuple:
    """The side panel's strip at one edge of a monitor's work area."""
    if side == "left":
        return (work[0], work[1], work[0] + width, work[3])
    return (work[2] - width, work[1], work[2], work[3])


def panel_side(work: tuple, width: int, target: tuple | None, side: str) -> str:
    """The panel floats over other windows (it reserves no space, so desktop
    icons never move): it changes sides when it would cover the target."""
    def covers(s):
        p = panel_rect(work, width, s)
        return target[0] < p[2] and p[0] < target[2] and target[1] < p[3] and p[1] < target[3]
    other = "left" if side == "right" else "right"
    return other if target and covers(side) and not covers(other) else side


# -- Windows glue -------------------------------------------------------------
recorder.user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         wintypes.UINT]


def place(hwnd, r: tuple):
    """Topmost at r, without taking focus or waiting on the panel's thread."""
    HWND_TOPMOST, SWP_NOACTIVATE, SWP_ASYNCWINDOWPOS = -1, 0x10, 0x4000
    if hwnd:
        recorder.user32.SetWindowPos(hwnd, HWND_TOPMOST, r[0], r[1], r[2] - r[0],
                                     r[3] - r[1], SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS)


def monitor_dpi(pt: tuple[int, int]) -> int:
    """The DPI of the monitor at pt (96 = 100%)."""
    MONITOR_DEFAULTTOPRIMARY, MDT_EFFECTIVE_DPI = 1, 0
    recorder.user32.MonitorFromPoint.restype = wintypes.HMONITOR
    recorder.user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    hmon = recorder.user32.MonitorFromPoint(wintypes.POINT(*pt), MONITOR_DEFAULTTOPRIMARY)
    x, y = wintypes.UINT(), wintypes.UINT()
    try:
        if ctypes.windll.shcore.GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI,
                                                 ctypes.byref(x), ctypes.byref(y)) == 0:
            return x.value
    except Exception:
        pass
    return 96


def monitor_of(mons: list[dict], pt: tuple[int, int]) -> dict:
    """The monitor holding pt, else the primary."""
    return next((m for m in mons if m["left"] <= pt[0] < m["right"]
                 and m["top"] <= pt[1] < m["bottom"]),
                next((m for m in mons if m["primary"]), mons[0]))


_EXE: dict[tuple, str] = {}  # (hwnd, pid) -> exe name
_dwm = ctypes.windll.dwmapi
window_class = recorder.window_class
recorder.user32.FindWindowExW.restype = wintypes.HWND
recorder.user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                          wintypes.LPCWSTR, wintypes.LPCWSTR]


def _cloaked(h) -> bool:
    v = wintypes.DWORD()
    return _dwm.DwmGetWindowAttribute(wintypes.HWND(h), 14, ctypes.byref(v),  # DWMWA_CLOAKED
                                      ctypes.sizeof(v)) == 0 and v.value != 0


def top_windows(skip_own: bool = True) -> list[dict]:
    """Visible, not minimised top-level windows, top-most first."""
    wins, me = [], os.getpid()
    u = recorder.user32

    def _cb(h, _):
        if u.IsWindowVisible(h) and not u.IsIconic(h) and not _cloaked(h) \
                and not (skip_own and recorder.window_pid(h) == me):
            # (skipped: windows on other virtual desktops or suspended, which
            # are "cloaked"; the taskbar stays: guides often click it, and the
            # recorded window class keeps it from standing in for Explorer)
            r = recorder.window_rect(h)
            if r and r[2] > r[0] and r[3] > r[1]:
                key = (h, recorder.window_pid(h))  # hwnds get reused
                if key not in _EXE:
                    _EXE[key] = Path(recorder.window_info(h)[2]).name
                wins.append({"hwnd": h, "exe": _EXE[key], "cls": window_class(h),
                             "title": recorder.window_title(h), "rect": r})
        return True

    for h in top_level_windows():
        _cb(h, 0)
    return wins


def top_level_windows() -> list:
    """Every top-level window, top-most first. FindWindowEx, not EnumWindows:
    EnumWindows leaves out the shell's own band (Start, Search), which guides
    click often."""
    out, h = [], None
    while h := recorder.user32.FindWindowExW(None, h, None, None):
        out.append(h)
    return out


class UIAFind:
    """Element search; create and use it on one thread (its COM apartment)."""
    _AID, _NAME, _TYPE = 30011, 30005, 30003
    _DESCENDANTS = 4

    def __init__(self):
        self._u = recorder._UIA()._uia

    def _all(self, root, cond) -> list[tuple]:
        found = root.FindAll(self._DESCENDANTS, cond)
        out = []
        for i in range(found.Length if found else 0):
            try:
                el = found.GetElement(i)
                if el.CurrentIsOffscreen:
                    continue
                r = el.CurrentBoundingRectangle
            except Exception:
                continue  # gone between the search and the read (a closed dialog)
            out.append((r.left, r.top, r.right, r.bottom))
        return out

    def element_at(self, pt: tuple[int, int], hwnd) -> tuple | None:
        """The rect of the clickable element (button, list item, ...) at pt,
        if it belongs to hwnd's program; None otherwise."""
        try:
            el = self._u.ElementFromPoint(wintypes.POINT(*pt))
            if not el or el.CurrentProcessId != recorder.window_pid(hwnd):
                return None
            walker = self._u.ControlViewWalker
            for _ in range(8):
                if not el:
                    return None
                if el.CurrentControlType in recorder.CLICKABLE_TYPES:
                    r = el.CurrentBoundingRectangle
                    return (r.left, r.top, r.right, r.bottom) if r.right > r.left \
                        and r.bottom > r.top else None
                el = walker.GetParentElement(el)
        except Exception:
            pass
        return None

    def elements(self, hwnd, aid: str, name: str, ctype: int) -> list[tuple]:
        """Rects of the elements in that window matching aid, else name+type."""
        u = self._u
        root = u.ElementFromHandle(wintypes.HWND(hwnd))
        if aid:
            got = self._all(root, u.CreatePropertyCondition(self._AID, aid))
            if got:
                return got
        if not name:
            return []
        return self._all(root, u.CreateAndCondition(
            u.CreatePropertyCondition(self._NAME, name),
            u.CreatePropertyCondition(self._TYPE, ctype)))


class Runner:
    """The live walk-through: a thread that finds the current step's target
    every half second, keeps the highlight on it, and moves on when the
    person clicks it. state() is what the side panel shows."""

    TICK = 0.5

    def __init__(self, steps: list[dict], origin: tuple[int, int], highlight):
        self.session = Session(steps)
        self._origin = origin
        self._highlight = highlight
        self._q: queue.Queue = queue.Queue()
        self._res = {"state": "none", "shape": None, "rect": None, "app": ""}
        threading.Thread(target=self._run, daemon=True).start()

    # thread-safe API
    def click(self, button: str, x: int, y: int):
        self._q.put(("click", button, x, y))  # called from the mouse hook: never block

    def go(self, i: int):
        self._q.put(("go", i))

    def next(self):
        self._q.put(("step", 1))

    def back(self):
        self._q.put(("step", -1))

    def stop(self):
        self._q.put(("stop",))

    def state(self) -> dict:
        s = self.session
        return {"index": s.index, "done": s.done, "state": self._res["state"],
                "app": self._res["app"]}

    # worker thread
    def _run(self):
        try:
            uia = UIAFind()
        except Exception:
            uia = None
        while True:
            try:
                item = self._q.get(timeout=self.TICK)
            except queue.Empty:
                item = None
            if item and item[0] == "stop":
                self._highlight(None)
                return
            s = self.session
            if item and item[0] == "click":
                s.on_click(item[1], item[2], item[3], self._res)
            elif item and item[0] == "go":
                s.go(item[1])
            elif item and item[0] == "step":
                s.go(s.index + item[1])
            try:
                self._tick(uia)
            except Exception:
                # a window closing mid-search: never leave the last step's
                # outline up (a click there would skip this step); retry next tick
                self._res = {"state": "none", "shape": None, "rect": None, "app": ""}
                self._highlight(self._res)

    def _tick(self, uia):
        s = self.session
        if s.done:
            self._res = {"state": "none", "shape": None, "rect": None, "app": ""}
        else:
            wins = None

            def find_window(exe, title, cls):
                nonlocal wins
                wins = top_windows() if wins is None else wins
                return pick_window(wins, exe, title, cls)

            find = uia.elements if uia else (lambda *a: [])
            self._res = resolve(s.steps[s.index], find_window, find, self._origin,
                                uia.element_at if uia else None)
        self._highlight(self._res)
