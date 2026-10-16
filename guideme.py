"""Guide Me: walk a person through a guide on the real screen.

The top half is pure (where is this step's target, did that click hit it,
which step is next); the Windows glue below it finds windows and elements,
draws the highlight and docks the side panel.
"""
from __future__ import annotations

from pathlib import Path

CLICKS = {"click", "rightclick", "doubleclick"}
MARKER = 44  # a circle the size of a recorded click marker


def pick_window(wins: list[dict], exe: str, title: str) -> dict | None:
    """The window of that exe (top-most first), the one titled title if any."""
    same = [w for w in wins if w["exe"].lower() == exe.lower()]
    return next((w for w in same if w["title"] == title), same[0] if same else None)


def nearest(rects: list[tuple], pt: tuple[int, int]) -> tuple | None:
    """The non-empty rect whose centre is closest to pt."""
    ok = [r for r in rects if r[2] > r[0] and r[3] > r[1]]
    return min(ok, key=lambda r: ((r[0] + r[2]) / 2 - pt[0]) ** 2
               + ((r[1] + r[3]) / 2 - pt[1]) ** 2, default=None)


def _circle(cx: int, cy: int, size: int) -> tuple:
    h = size // 2
    return (cx - h, cy - h, cx + h, cy + h)


def resolve(step: dict, find_window, find_elements, origin: tuple[int, int]) -> dict:
    """Where this step's target is on screen now.
    state: element (box on the found element), approx (circle where it was),
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
    w = find_window(t["exe"], t.get("window", ""))
    if w is None:
        return {**res, "state": "missing", "app": Path(t["exe"]).stem}
    pt = (w["rect"][0] + t["dx"], w["rect"][1] + t["dy"])
    r = nearest(find_elements(w["hwnd"], t.get("aid", ""), t.get("name", ""),
                              t.get("type", 0)), pt)
    if r:
        return {**res, "state": "element", "shape": "box", "rect": r}
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
