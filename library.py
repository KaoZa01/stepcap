"""Guides on disk: one owner for reading, writing, listing and trashing them.

Pure Python (no Windows or UI imports) so it is testable on temp folders.
Layout: <storage>/<id>/guide.json + images; <storage>/_trash/<id>/ for deleted
guides; folders starting with "_" are system folders, never guides.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

DEFAULT_SETTINGS = {"toc": False, "step_count": False, "created": False,
                    "updated": False, "layout": "linear",
                    "click_color": "#FB923C"}
DEFAULT_APP_SETTINGS = {"monitor": None, "view": "grid"}

TRASH = "_trash"
COPY_SUFFIX = " (สำเนา)"


def safe_name(name: str) -> bool:
    return name != "" and "/" not in name and "\\" not in name \
        and ".." not in name


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


def _load_raw(folder: Path) -> dict | None:
    """guide.json as stored, or None when missing or not a guide."""
    try:
        g = json.loads((folder / "guide.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(g, dict) or not isinstance(g.get("steps"), list):
        return None
    return g


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
    out["steps"] = [{"image": None, "crop": None, "markers": [], **s}
                    for s in out.get("steps") or []]
    return out


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
        if g is None or (bookmarked_only and not g["bookmarked"]):
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
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        return False
    data = {**data, "id": gid, "updated": now_iso()}
    write_json_atomic(folder / "guide.json", data)
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
        g["title"] = title.strip()
        g["updated"] = now_iso()
    if bookmarked is not None:
        g["bookmarked"] = bool(bookmarked)
    write_json_atomic(folder / "guide.json", g)
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
    return {**DEFAULT_APP_SETTINGS,
            **{k: v for k, v in raw.items() if k in DEFAULT_APP_SETTINGS}}


def save_settings(storage: Path, **changes) -> dict:
    s = {**load_settings(storage),
         **{k: v for k, v in changes.items() if k in DEFAULT_APP_SETTINGS}}
    storage.mkdir(parents=True, exist_ok=True)
    write_json_atomic(storage / "settings.json", s)
    return s
