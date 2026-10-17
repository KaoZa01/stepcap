"""StepCap set to English, walked screen by screen: nothing the app writes
itself may show Thai. Seeded with English guides, so any Thai on screen is
a string that missed tr(). The language card on Settings is the one place
Thai belongs ("ไทย", "ภาษา / Language"), so it is left out of the scan.
Only DOM events inside StepCap's own page; nothing touches the desktop.
Run: python test_english.py"""
import json
import sys
import traceback
from pathlib import Path

import webview

import test_render as R
from test_render import CTX, js, page

SCAN = r"""
const sl = document.getElementById('setlang'); if (sl) sl.style.display = 'none';
const bits = [document.body.innerText];
for (const e of document.querySelectorAll('[title],[aria-label],[placeholder],[data-tip],[alt]'))
  for (const a of ['title', 'aria-label', 'placeholder', 'data-tip', 'alt'])
    if (e.hasAttribute(a)) bits.push(e.getAttribute(a));
for (const b of document.querySelectorAll('button, input[type=button]')) if (b.value) bits.push(b.value);
if (sl) sl.style.display = '';
return bits.flatMap(s => s.split('\n')).filter(s => /[฀-๿]/.test(s)).slice(0, 20);
"""
WAIT = "await new Promise(r => setTimeout(r, 500));"


def scan(where: str, before: str = ""):
    leaks = js(before + WAIT + SCAN)
    assert not leaks, f"{where}: {leaks}"


def _guide(st: Path, gid: str, title: str, steps: list, **extra):
    (st / gid).mkdir()
    (st / gid / "n.png").write_bytes(R.NOISE_PNG)
    g = {"id": gid, "title": title, "app": "Outlook", "created": "2026-10-15T10:00:00",
         "updated": "2026-10-15T11:00:00", "steps": steps, **extra}
    (st / gid / "guide.json").write_text(json.dumps(g), encoding="utf-8")


def seed_en(st: Path):
    _guide(st, "g1", "Set up email", [
        {"id": "a1", "kind": "click", "text": 'Click the "New" button in Outlook', "image": "n.png",
         "crop": None, "markers": [{"x": 160, "y": 100, "color": "#FB923C", "size": 44}]},
        {"id": "a2", "kind": "note", "text": "Ask IT for the server name first"},
        {"id": "a3", "kind": "type", "text": 'Type "me@example.com" in the "Email" field', "image": "n.png",
         "crop": None, "markers": []},
    ], settings={"toc": True, "step_count": True, "created": True, "updated": True})
    _guide(st, "g2", "Book a meeting room", [
        {"id": "b1", "kind": "click", "text": "Open the calendar", "image": None, "crop": None, "markers": []}])
    _guide(st, "g3", "Old guide", [
        {"id": "c1", "kind": "click", "text": "Something", "image": None, "crop": None, "markers": []}])
    (st / "settings.json").write_text(json.dumps({"lang": "en", "tours_seen": [], "sample_added": True}),
                                      encoding="utf-8")
    (st / "_pages").mkdir()
    (st / "_pages" / "pgA.json").write_text(json.dumps(
        {"id": "pgA", "title": "New starters", "description": "Everything for week one",
         "created": "2026-10-16T10:00:00", "updated": "2026-10-16T10:00:00",
         "settings": {"toc": True, "step_count": True, "created": True},
         "sections": [{"type": "guide", "guide": "g1"}, {"type": "text", "title": "Then", "text": "Meet the team"},
                      {"type": "guide", "guide": "g2"}, {"type": "guide", "guide": "ghost"}]}),
        encoding="utf-8")


def _click(sel: str) -> str:
    return f"document.querySelector({json.dumps(sel)}).click();"


def _walk_tour(where: str, stops: int):
    """Every stop of the tour on screen (stops: how many it should have)."""
    js(R._until("document.querySelector('.tour-box')"))
    assert js("return document.querySelector('.tour-count').textContent;") == f"1/{stops}"
    for i in range(stops):
        scan(f"{where} tour stop {i + 1}")
        js(_click(".tour-box [data-t=next]"))
    assert js(WAIT + "return !document.querySelector('.tour-box');"), f"{where}: tour still open"


def test_home_and_tour():
    page("page=home")
    _walk_tour("home", 2)  # no sample guide in this library: its stop is left out
    scan("home")
    scan("record menu", _click("#recbtn"))
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));")


def test_library_views_and_menus():
    page("page=all")
    scan("all (grid)")
    scan("guide card menu", _click(".card .more"))
    scan("all (list)", "document.body.click();" + _click("[data-view=list]"))
    js(_click("[data-view=grid]") + WAIT)
    scan("error toast", "const real = window.fetch; window.fetch = async () => new Response('', {status: 500});"
                        + _click(".card .bm") + WAIT + "window.fetch = real;")


def test_pages():
    page("page=pages")
    scan("pages list")
    scan("new page prompt", _click("#newpage"))
    js(_click(".ui-dlg .cancel"))
    page("pg=pgA&mode=view")
    scan("page view")
    page("pg=pgA&mode=edit")
    scan("page edit")
    scan("add guides dialog", _click("#addguide"))


def test_trash_and_settings():
    js("await post('/api/guide/g3/delete');")
    page("page=trash")
    scan("trash")
    page("page=settings")
    scan("settings")


def test_guide_view_and_export_menu():
    page("guide=g1&mode=view")
    scan("guide view")
    scan("export menu", _click("#exp"))


def test_guideme_panel():
    page("guideme=g1", width=360)
    scan("guide me panel", R._until("document.querySelector('.gm-card.on')"))


def test_guide_edit_tour_pops_and_dialogs():
    page("guide=g1&mode=edit")
    _walk_tour("edit", 5)
    scan("guide edit")
    scan("click marks pop", _click("[data-pop=click]"))
    scan("document pop", "document.body.click();" + _click("[data-pop=doc]"))
    js("document.body.click();")
    scan("delete step confirm", _click(".step [data-act=del]"))
    js(_click(".ui-dlg .cancel"))


def test_image_editor_tools():
    page("guide=g1&mode=edit")
    js(R._until("document.querySelector('.step .etools:not([hidden]) .ed')") +
       _click(".step .etools:not([hidden]) .ed"))
    js(R._until("document.querySelector('[data-tool]')"))
    for tool in ("select", "marker", "arrow", "box", "text", "blur", "black", "crop"):
        scan(f"image editor: {tool}", _click(f"[data-tool={tool}]"))


TESTS = [test_guideme_panel, test_home_and_tour, test_library_views_and_menus, test_pages, test_trash_and_settings,
         test_guide_view_and_export_menu, test_guide_edit_tour_pops_and_dialogs, test_image_editor_tools]


def run_all(holder):
    try:
        for fn in TESTS:
            try:
                fn()
                CTX.setdefault("ok", []).append(fn.__name__)
                print(f"ok   {fn.__name__}", flush=True)
            except Exception:
                print(f"FAIL {fn.__name__}", flush=True)
                traceback.print_exc()
    finally:
        if CTX.get("win"):
            CTX["win"].destroy()
        holder.destroy()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        R.launch(seed_en)
        holder = webview.create_window("holder", html="<p>.</p>", hidden=True)
        webview.start(run_all, (holder,), private_mode=True)
    finally:
        R.teardown()
    passed = len(CTX.get("ok", []))
    print(f"\n{passed}/{len(TESTS)} passed")
    raise SystemExit(0 if passed == len(TESTS) else 1)
