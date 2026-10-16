"""Guides on disk: one owner for reading, writing, listing and trashing them.

Pure Python (no Windows or UI imports) so it is testable on temp folders.
Layout: <storage>/<id>/guide.json + images; <storage>/_trash/<id>/ for deleted
guides; folders starting with "_" are system folders, never guides.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import redact

DEFAULT_SETTINGS = {"toc": False, "step_count": False, "created": False,
                    "updated": False, "layout": "linear",
                    "click_color": "#FB923C", "click_shape": "circle",
                    "click_size": 44}
DEFAULT_APP_SETTINGS = {"monitor": None, "view": "grid", "redact_on": True,
                        "redact_rules": list(redact.RULES), "redact_custom": []}

MAX_IMAGE = 25 * 1024 * 1024  # bytes per uploaded image
IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif"}
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"),
          (b"GIF87a", "gif"), (b"GIF89a", "gif"))
_LAYERS = ("markers", "annotations", "redactions")

TRASH = "_trash"
COPY_SUFFIX = " (สำเนา)"


def safe_name(name: str) -> bool:
    # ":" too: pathlib joins "C:x" onto another drive
    return name != "" and ".." not in name \
        and not any(c in "/\\:" or ord(c) < 32 for c in name)


def safe_id(gid: str) -> bool:
    return safe_name(gid) and not gid.startswith("_")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_id(storage: Path, now: float | None = None) -> str:
    """Timestamp id, suffixed -2, -3 ... until free among live and trashed."""
    base = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    cand, n = base, 1
    while (storage / cand).exists() or (storage / TRASH / cand).exists():
        n += 1
        cand = f"{base}-{n}"
    return cand


def write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


def _is_guide(g) -> bool:
    """Shape every reader relies on; anything else is treated as not a guide."""
    if not isinstance(g, dict) or not isinstance(g.get("steps"), list):
        return False
    if any(g.get(k) is not None and not isinstance(g[k], str)
           for k in ("title", "created", "updated", "app", "app_icon")):
        return False
    if g.get("settings") is not None and not isinstance(g["settings"], dict):
        return False
    return all(isinstance(s, dict)
               and isinstance(s.get("text", ""), (str, type(None)))
               and all(_dict_list(s.get(k, [])) for k in _LAYERS)
               for s in g["steps"])


def _dict_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, dict) for x in v)


def _load_raw(folder: Path) -> dict | None:
    """guide.json as stored, or None when missing or not a guide."""
    try:
        g = json.loads((folder / "guide.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return g if _is_guide(g) else None


def normalize(g: dict) -> dict:
    """A guide with every field the UI reads; old guides get defaults."""
    out = dict(g)
    title = out.get("title") or ""
    out["created"] = out.get("created") or ""
    out["updated"] = out.get("updated") or out["created"]
    out["bookmarked"] = bool(out.get("bookmarked", False))
    out["app"] = out.get("app") or (title.split(" - ", 1)[0]
                                    if " - " in title else "")
    out["app_icon"] = out.get("app_icon") or None
    out["settings"] = {**DEFAULT_SETTINGS, **(out.get("settings") or {})}
    steps = []
    for s in out.get("steps") or []:
        s = {"image": None, "crop": None, "markers": [], "annotations": [],
             "redactions": [], **s}
        s["markers"] = [{"shape": "circle", **m} for m in s["markers"]]
        steps.append(s)
    out["steps"] = steps
    return out


def image_kind(data: bytes) -> str | None:
    """png / jpg / gif by the file's first bytes; the name is never trusted."""
    return next((kind for magic, kind in _MAGIC if data.startswith(magic)), None)


def add_image(storage: Path, gid: str, data: bytes) -> str | None:
    """Save an uploaded image into the guide folder under a new name."""
    folder = storage / gid
    kind = image_kind(data)
    if not safe_id(gid) or not folder.is_dir() or kind is None \
            or len(data) > MAX_IMAGE:
        return None
    while True:
        name = f"i{secrets.token_hex(4)}.{kind}"
        if not (folder / name).exists():
            break
    try:
        (folder / name).write_bytes(data)
    except OSError:
        return None
    return name


def step_count(g: dict) -> int:
    return sum(1 for s in g.get("steps", []) if s.get("kind") != "note")


def read_guide(folder: Path) -> dict | None:
    g = _load_raw(folder)
    return normalize(g) if g is not None else None


def rel_time(iso: str, now: datetime) -> str:
    try:
        secs = (now - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return ""
    if secs < 60:
        return "เมื่อสักครู่"
    if secs < 3600:
        return f"{int(secs // 60)} นาทีที่แล้ว"
    if secs < 86400:
        return f"{int(secs // 3600)} ชั่วโมงที่แล้ว"
    days = int(secs // 86400)
    if days < 30:
        return f"{days} วันที่แล้ว"
    if days < 365:
        return f"{days // 30} เดือนที่แล้ว"
    return f"{days // 365} ปีที่แล้ว"


def _matches(g: dict, q: str) -> bool:
    if q in (g.get("title") or "").casefold():
        return True
    return any(q in (s.get("text") or "").casefold() for s in g["steps"])


def list_guides(storage: Path, q: str = "", bookmarked_only: bool = False,
                now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    q = q.strip().casefold()
    out = []
    for folder in storage.iterdir():
        if not folder.is_dir() or not safe_id(folder.name):
            continue
        g = read_guide(folder)
        if g is None:
            # a guide.json that can't be read is listed, not hidden: the user
            # must see their guide is there but damaged (a folder being
            # recorded has no guide.json yet and stays out)
            if not q and not bookmarked_only and (folder / "guide.json").is_file():
                out.append({"id": folder.name, "title": folder.name, "created": "",
                            "updated": "", "count": 0, "app": "", "icon": False,
                            "bookmarked": False, "ago": "", "broken": True})
            continue
        if bookmarked_only and not g["bookmarked"]:
            continue
        if q and not _matches(g, q):
            continue
        icon = bool(g["app_icon"]) and (folder / g["app_icon"]).is_file()
        out.append({"id": folder.name, "title": g.get("title") or folder.name,
                    "created": g["created"], "updated": g["updated"],
                    "count": step_count(g), "app": g["app"], "icon": icon,
                    "bookmarked": g["bookmarked"],
                    "ago": rel_time(g["updated"], now)})
    out.sort(key=lambda s: (s["created"], s["id"]), reverse=True)
    return out


def save_guide(storage: Path, gid: str, data: dict) -> bool:
    folder = storage / gid
    if not safe_id(gid) or not folder.is_dir():
        return False
    if not _is_guide(data):
        return False
    data = {**data, "id": gid, "updated": now_iso()}
    try:
        write_json_atomic(folder / "guide.json", data)
    except OSError:  # e.g. the file is held open; the page keeps the edits and retries
        return False
    return True


def update_meta(storage: Path, gid: str, title: str | None = None,
                bookmarked: bool | None = None) -> bool:
    folder = storage / gid
    if not safe_id(gid):
        return False
    g = _load_raw(folder)
    if g is None:
        return False
    if title is not None:
        if not title.strip():
            return False
        # old guides derive "app" from the title; keep it before the title goes
        g["app"] = normalize(g)["app"]
        g["title"] = title.strip()
        g["updated"] = now_iso()
    if bookmarked is not None:
        g["bookmarked"] = bool(bookmarked)
    try:
        write_json_atomic(folder / "guide.json", g)
    except OSError:  # read-only, held open, disk full: the page says it failed
        return False
    return True


def duplicate_guide(storage: Path, gid: str) -> str | None:
    src = storage / gid
    if not safe_id(gid) or _load_raw(src) is None:
        return None
    new = new_id(storage)
    shutil.copytree(src, storage / new)
    g = _load_raw(storage / new)
    stamp = now_iso()
    g.update(id=new, title=(g.get("title") or gid) + COPY_SUFFIX,
             created=stamp, updated=stamp, bookmarked=False)
    write_json_atomic(storage / new / "guide.json", g)
    return new


# -- trash ---------------------------------------------------------------------
def trash_guide(storage: Path, gid: str) -> bool:
    src, dst = storage / gid, storage / TRASH / gid
    if not safe_id(gid) or not src.is_dir() or dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    g = _load_raw(dst)
    if g is not None:  # unreadable guides still move; they just lack a date
        g["deleted"] = now_iso()
        write_json_atomic(dst / "guide.json", g)
    return True


def list_trash(storage: Path, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    root = storage / TRASH
    if not root.is_dir():
        return []
    out = []
    for folder in root.iterdir():
        if not folder.is_dir() or not safe_id(folder.name):
            continue
        g = _load_raw(folder) or {"steps": []}
        deleted = g.get("deleted") or ""
        out.append({"id": folder.name, "title": g.get("title") or folder.name,
                    "deleted": deleted, "ago": rel_time(deleted, now),
                    "count": step_count(g)})
    out.sort(key=lambda t: (t["deleted"], t["id"]), reverse=True)
    return out


def restore_guide(storage: Path, gid: str) -> bool:
    src, dst = storage / TRASH / gid, storage / gid
    if not safe_id(gid) or not src.is_dir() or dst.exists():
        return False
    shutil.move(str(src), str(dst))
    g = _load_raw(dst)
    if g is not None and "deleted" in g:
        del g["deleted"]
        write_json_atomic(dst / "guide.json", g)
    return True


def purge_guide(storage: Path, gid: str,
                recycle: Callable[[Path], None]) -> bool:
    folder = storage / TRASH / gid
    if not safe_id(gid) or not folder.is_dir():
        return False
    recycle(folder)
    return True


def empty_trash(storage: Path, recycle: Callable[[Path], None]) -> int:
    return sum(purge_guide(storage, t["id"], recycle)
               for t in list_trash(storage))


# -- app settings (settings.json) --------------------------------------------
def load_settings(storage: Path) -> dict:
    try:
        raw = json.loads((storage / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {**DEFAULT_APP_SETTINGS, **_clean_settings(raw)}


def _clean_settings(d: dict) -> dict:
    """Known keys only; redact_* of the wrong shape are dropped (-> defaults)."""
    out = {k: v for k, v in d.items() if k in DEFAULT_APP_SETTINGS}
    if not isinstance(out.get("redact_on", True), bool):
        del out["redact_on"]
    for k in ("redact_rules", "redact_custom"):
        if k in out and not (isinstance(out[k], list)
                             and all(isinstance(x, str) for x in out[k])):
            del out[k]
    if "redact_rules" in out:
        out["redact_rules"] = [r for r in redact.RULES if r in out["redact_rules"]]
    if "redact_custom" in out:
        out["redact_custom"] = [w.strip() for w in out["redact_custom"] if w.strip()]
    return out


def save_settings(storage: Path, **changes) -> dict:
    s = {**load_settings(storage), **_clean_settings(changes)}
    storage.mkdir(parents=True, exist_ok=True)
    write_json_atomic(storage / "settings.json", s)
    return s


# -- pages: <storage>/_pages/<id>.json, documents that reference guides ---------
PAGES_DIR = "_pages"
DEFAULT_PAGE_SETTINGS = {"toc": True, "step_count": False, "created": False,
                         "updated": False}


def _is_page(d) -> bool:
    if not isinstance(d, dict) or not isinstance(d.get("sections"), list):
        return False
    if not all(isinstance(d.get(k, ""), str) for k in ("title", "description", "created", "updated")):
        return False
    if not isinstance(d.get("settings", {}), dict):
        return False
    for s in d["sections"]:
        if not isinstance(s, dict):
            return False
        if s.get("type") == "guide":
            if not (isinstance(s.get("guide"), str) and safe_id(s["guide"])):
                return False
        elif s.get("type") == "text":
            if not all(isinstance(s.get(k, ""), str) for k in ("title", "text")):
                return False
        else:
            return False
    return True


def _page_file(storage: Path, pid: str) -> Path | None:
    return storage / PAGES_DIR / f"{pid}.json" if safe_name(pid) else None


def read_page(storage: Path, pid: str) -> dict | None:
    f = _page_file(storage, pid)
    try:
        d = json.loads(f.read_text(encoding="utf-8")) if f else None
    except (OSError, ValueError):
        return None
    if not _is_page(d):
        return None
    return {"title": "", "description": "", "created": "", **d, "id": pid,
            "updated": d.get("updated") or d.get("created", ""),
            "settings": {**DEFAULT_PAGE_SETTINGS, **(d.get("settings") or {})}}


def save_page(storage: Path, pid: str, data: dict) -> bool:
    f = _page_file(storage, pid)
    if f is None or not f.is_file() or not _is_page(data):
        return False
    keep = {k: data[k] for k in ("title", "description", "created", "settings", "sections")
            if k in data}  # not what the page screen adds for itself (guide titles)
    seen = set()  # a guide appears once per page
    keep["sections"] = [s for s in data["sections"] if s["type"] != "guide"
                        or not (s["guide"] in seen or seen.add(s["guide"]))]
    try:
        write_json_atomic(f, {**keep, "id": pid, "updated": now_iso()})
    except OSError:
        return False
    return True


def create_page(storage: Path, title: str) -> dict:
    root = storage / PAGES_DIR
    root.mkdir(parents=True, exist_ok=True)
    base = "p" + time.strftime("%Y%m%d-%H%M%S")
    pid, n = base, 1
    while (root / f"{pid}.json").exists():
        n += 1
        pid = f"{base}-{n}"
    now = now_iso()
    page = {"id": pid, "title": title, "description": "", "created": now,
            "updated": now, "settings": dict(DEFAULT_PAGE_SETTINGS), "sections": []}
    write_json_atomic(root / f"{pid}.json", page)
    return page


def delete_page(storage: Path, pid: str) -> bool:
    """A page is only a list of references: its guides stay untouched."""
    f = _page_file(storage, pid)
    if f is None or not f.is_file():
        return False
    f.unlink()
    return True


def list_pages(storage: Path, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    root = storage / PAGES_DIR
    out = []
    for f in root.glob("*.json") if root.is_dir() else []:
        p = read_page(storage, f.stem)
        if p is None:
            continue
        out.append({"id": p["id"], "title": p["title"] or p["id"],
                    "count": sum(1 for s in p["sections"] if s["type"] == "guide"
                                 and (storage / s["guide"] / "guide.json").is_file()),
                    "updated": p["updated"], "ago": rel_time(p["updated"], now)})
    out.sort(key=lambda p: (p["updated"], p["id"]), reverse=True)
    return out


def add_guide_to_page(storage: Path, pid: str, gid: str) -> str | None:
    """'added', 'exists' (a guide appears once per page), None if either is gone."""
    page = read_page(storage, pid)
    if page is None or not safe_id(gid) or read_guide(storage / gid) is None:
        return None
    if any(s["type"] == "guide" and s["guide"] == gid for s in page["sections"]):
        return "exists"
    page["sections"].append({"type": "guide", "guide": gid})
    return "added" if save_page(storage, pid, page) else None


def compile_page(page: dict, guides: dict[str, dict | None]) -> tuple[dict, int]:
    """The page as one guide-shaped document: a 'section' entry opens each
    guide or text block (numbering restarts after it), guide steps get ids
    '<gid>/<sid>' and carry 'gid' so pictures load from the right folder.
    guides maps id -> guide, or None when it was deleted."""
    settings = {**DEFAULT_PAGE_SETTINGS, **(page.get("settings") or {})}
    steps, missing, count = [], 0, 0
    for i, s in enumerate(page.get("sections") or []):
        sec = {"id": f"sec{i}", "kind": "section"}
        if s["type"] == "text":
            steps.append({**sec, "text": s.get("title", ""), "body": s.get("text", "")})
            continue
        gid, g = s["guide"], guides.get(s["guide"])
        if g is None:
            missing += 1
            steps.append({**sec, "text": "คู่มือนี้ถูกลบแล้ว", "missing": True, "gid": gid})
            continue
        count += 1
        steps.append({**sec, "text": g.get("title", ""), "gid": gid})
        steps += [{**st, "id": f"{gid}/{st.get('id')}", "gid": gid} for st in g.get("steps") or []]
    doc = {"id": page.get("id"), "title": page.get("title", ""),
           "description": page.get("description", ""),
           "created": page.get("created", ""), "updated": page.get("updated", ""),
           "settings": {**settings, "step_count": False}, "steps": steps}
    if settings.get("step_count"):
        doc["meta_count"] = f"{count} คู่มือ"
    return doc, missing
