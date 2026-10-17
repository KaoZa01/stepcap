"""On-screen overlays: blinking monitor border, fading toast, recording panel.

Runs tkinter on its own thread; other threads enqueue requests that a polling
callback drains on the tk thread (tkinter is single-thread-owned). Every
overlay is excluded from screen capture so it never lands in a guide image.
"""
from __future__ import annotations

import ctypes
import queue
import threading
import tkinter as tk

from i18n import tr

_KEY = "#010203"  # transparent-color key (unlikely to clash with content)
_FONT = "Leelawadee UI"  # Windows UI font with Thai glyphs
WDA_EXCLUDEFROMCAPTURE = 0x11

_user32 = ctypes.windll.user32
_user32.GetParent.restype = ctypes.c_void_p
_user32.GetParent.argtypes = [ctypes.c_void_p]
_user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
_user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]


def _style(win: tk.Toplevel, clickthrough: bool) -> bool:
    """No taskbar entry, never takes focus, hidden from capture.
    Returns whether the capture exclusion was applied."""
    win.update_idletasks()
    hwnd = _user32.GetParent(win.winfo_id()) or win.winfo_id()
    GWL_EXSTYLE = -20
    ex = 0x80 | 0x8000000  # TOOLWINDOW | NOACTIVATE
    if clickthrough:
        ex |= 0x80000 | 0x20  # LAYERED | TRANSPARENT
    cur = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cur | ex)
    return bool(_user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))


class Overlay:
    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._panel: tk.Toplevel | None = None
        self.capture_excluded = None  # last result of the capture exclusion
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(3)

    def _run(self):
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.after(50, self._poll)
        self._ready.set()
        self._root.mainloop()

    def _poll(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        self._root.after(50, self._poll)

    # public API (thread-safe) --------------------------------------------
    def flash(self, rect, color="#fb923c"):
        self._q.put(lambda: self._flash(rect, color))

    def toast(self, rect, text: str):
        self._q.put(lambda: self._toast(rect, text))

    def show_panel(self, work_rect, get_state, on_pause, on_stop):
        """get_state() -> {"recording","paused","steps":[{text}],"pending"}"""
        self._q.put(lambda: self._show_panel(work_rect, get_state,
                                             on_pause, on_stop))

    def hide_panel(self):
        self._q.put(self._hide_panel)

    def highlight(self, res: dict | None):
        """Guide Me's outline on the target: a box on a found element, a circle
        where it should be; None (or nothing to show) hides it."""
        self._q.put(lambda: self._highlight(res))

    # tk-thread implementations -------------------------------------------
    def _flash(self, rect, color):
        l, t, r, b = rect
        w, h = r - l, b - t
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{w}x{h}+{l}+{t}")
        win.configure(bg=_KEY)
        win.attributes("-transparentcolor", _KEY)
        bw = 12
        cv = tk.Canvas(win, bg=_KEY, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.create_rectangle(bw // 2, bw // 2, w - bw // 2, h - bw // 2,
                            outline=color, width=bw)
        self.capture_excluded = _style(win, clickthrough=True)
        state = {"n": 0}

        def blink():
            state["n"] += 1
            if state["n"] > 6:
                win.destroy()
                return
            (win.withdraw if state["n"] % 2 else win.deiconify)()
            self._root.after(220, blink)

        self._root.after(220, blink)

    def _toast(self, rect, text):
        l, t, r, b = rect
        w, h = r - l, b - t
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=_KEY)
        win.attributes("-transparentcolor", _KEY)
        tk.Label(win, text=text, fg="#ffffff", bg="#dc2626",
                 font=(_FONT, 30, "bold"), padx=44, pady=22).pack()
        win.update_idletasks()
        lw = win.winfo_width()
        win.geometry(f"+{l + (w - lw) // 2}+{t + int(h * 0.12)}")
        self.capture_excluded = _style(win, clickthrough=True)
        a = {"v": 1.0}
        win.attributes("-alpha", 1.0)

        def fade():
            a["v"] -= 0.06
            if a["v"] <= 0:
                win.destroy()
                return
            win.attributes("-alpha", a["v"])
            self._root.after(40, fade)

        self._root.after(900, fade)  # hold ~0.9s, then fade out

    _HL_PAD, _HL_W = 4, 3  # outline sits 4px outside the element, 3px thick

    def _highlight(self, res):
        win = getattr(self, "_hl", None)
        key = (res or {}).get("rect") and (res["shape"], res["rect"])
        if not key or res.get("state") not in ("element", "approx"):
            if win is not None:
                win.withdraw()
            self._hl_key = None
            return
        if key == getattr(self, "_hl_key", None):
            return  # unchanged: no redraw, no flicker
        self._hl_key = key
        if win is None:
            win = self._hl = tk.Toplevel(self._root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg=_KEY)
            win.attributes("-transparentcolor", _KEY)
            self._hl_cv = tk.Canvas(win, bg=_KEY, highlightthickness=0)
            self._hl_cv.pack(fill="both", expand=True)
            self.capture_excluded = _style(win, clickthrough=True)
        p = self._HL_PAD + self._HL_W
        l, t, r, b = res["rect"]
        w, h = r - l + 2 * p, b - t + 2 * p
        win.geometry(f"{w}x{h}+{l - p}+{t - p}")
        cv, s = self._hl_cv, self._HL_W
        cv.delete("all")
        o = (s / 2 + 1, s / 2 + 1, w - s / 2 - 1, h - s / 2 - 1)
        if res["shape"] == "circle":
            cv.create_oval(*o, outline="#fb923c", width=s)
        else:  # rounded rect: a smoothed polygon with doubled corner points
            x0, y0, x1, y1 = o
            k = 6
            pts = [x0 + k, y0, x1 - k, y0, x1, y0, x1, y0 + k, x1, y1 - k, x1, y1,
                   x1 - k, y1, x0 + k, y1, x0, y1, x0, y1 - k, x0, y0 + k, x0, y0]
            cv.create_polygon(pts, smooth=True, outline="#fb923c", fill="", width=s)
        win.deiconify()
        win.attributes("-topmost", True)

    def _hide_panel(self):
        if self._panel is not None:
            self._panel.destroy()
            self._panel = None

    def _show_panel(self, work_rect, get_state, on_pause, on_stop):
        self._hide_panel()
        # text red #f87171 and button red #b91c1c both clear 4.5:1 on their backgrounds
        BG, FG, MUTED, RED, YEL = "#1f2228", "#e8eaed", "#9aa2ad", "#f87171", "#eab308"
        W = 340
        win = tk.Toplevel(self._root, bg=BG)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.95)
        self._panel = win

        head = tk.Frame(win, bg=BG, cursor="fleur")
        head.pack(fill="x", padx=12, pady=(10, 4))
        status = tk.Label(head, bg=BG, fg=RED, font=(_FONT, 11, "bold"))
        status.pack(side="left")
        count = tk.Label(head, bg=BG, fg=MUTED, font=(_FONT, 10))
        count.pack(side="right")

        body = tk.Frame(win, bg=BG)
        body.pack(fill="x", padx=12)
        lines = [tk.Label(body, bg=BG, fg=FG, font=(_FONT, 10), anchor="w",
                          justify="left", wraplength=W - 24) for _ in range(5)]
        pend = tk.Label(body, bg=BG, fg=MUTED, font=(_FONT, 10, "italic"),
                        anchor="w", justify="left", wraplength=W - 24)

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=12, pady=(6, 12))

        def run(fn):
            threading.Thread(target=fn, daemon=True).start()

        pause_btn = tk.Button(btns, font=(_FONT, 10), relief="flat", bg="#31353c",
                              fg=FG, activebackground="#3b4048", padx=10,
                              command=lambda: run(on_pause))
        pause_btn.pack(side="left")
        tk.Button(btns, text=tr("หยุดบันทึก"), font=(_FONT, 10, "bold"), relief="flat",
                  bg="#b91c1c", fg="#ffffff", activebackground="#991b1b", padx=10,
                  command=lambda: run(on_stop)).pack(side="right")

        # drag by the header; once moved, stop re-anchoring to the corner
        drag = {"moved": False, "dx": 0, "dy": 0}

        def press(e):
            drag["dx"], drag["dy"] = e.x_root - win.winfo_x(), e.y_root - win.winfo_y()

        def motion(e):
            drag["moved"] = True
            win.geometry(f"+{e.x_root - drag['dx']}+{e.y_root - drag['dy']}")

        for w in (head, status, count):
            w.bind("<ButtonPress-1>", press)
            w.bind("<B1-Motion>", motion)

        wl, wt, wr, wb = work_rect

        def refresh():
            if self._panel is not win:
                return
            st = get_state()
            if not st.get("recording"):
                self._hide_panel()
                return
            paused = st.get("paused")
            status.config(text="⏸ " + tr("พักอยู่") if paused else "● " + tr("กำลังบันทึก"),
                          fg=YEL if paused else RED)
            pause_btn.config(text=tr("ทำต่อ") if paused else tr("พัก"))
            steps = st.get("steps", [])
            count.config(text=tr("{n} ขั้นตอน", n=len(steps)))
            tail = steps[-5:]
            first = len(steps) - len(tail) + 1
            for i, lab in enumerate(lines):
                if i < len(tail):
                    lab.config(text=f"{first + i}. {tail[i]['text']}", fg=FG)
                    lab.grid(row=i, column=0, sticky="w")
                else:
                    lab.grid_remove()
            if not steps and not st.get("pending"):
                lines[0].config(text=tr("ยังไม่มีขั้นตอน เริ่มคลิกได้เลย"), fg=MUTED)
                lines[0].grid(row=0, column=0, sticky="w")
            if st.get("pending"):
                pend.config(text="… " + st["pending"])
                pend.grid(row=5, column=0, sticky="w")
            else:
                pend.grid_remove()
            if not drag["moved"]:
                win.update_idletasks()
                h = win.winfo_reqheight()
                win.geometry(f"{W}x{h}+{wr - W - 16}+{wb - h - 16}")
            win.after(300, refresh)

        refresh()
        self.capture_excluded = _style(win, clickthrough=False)
