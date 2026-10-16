// Shared helpers for every StepCap page: server calls, icons, navigation,
// dialogs, toast, and the status poll that follows a just-finished recording.
"use strict";

const Q = new URLSearchParams(location.search);
const T = Q.get("t");

// Thai text in the current language (LANG and EN come with the page, from
// ui/en.json); {name} filled from v; a key + "#1" entry is the singular.
function tr(th, v) {
  const s = (v?.n === 1 && EN[th + "#1"]) || EN[th] || th;
  return v ? s.replace(/\{(\w+)\}/g, (m, k) => k in v ? String(v[k]) : m) : s;
}

const api = (path, opts) =>
  fetch(path + (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(T), opts);
const post = (path, body) => api(path, {
  method: "POST", headers: {"Content-Type": "application/json"},
  body: body === undefined ? "{}" : (typeof body === "string" ? body : JSON.stringify(body)),
});
const getJSON = async path => {
  const r = await api(path);
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
};
// true when the server took it; a dropped connection or an error status is false
const postOk = async (path, body) => { try { return (await post(path, body)).ok; } catch { return false; } };
// Runs fn with the button disabled, so a second click can't start it twice.
async function busy(btn, fn) {
  if (btn.disabled) return;
  btn.disabled = true;
  try { return await fn(); } finally { if (btn.isConnected) btn.disabled = false; }
}
// A div that opens something on click also opens with Enter / Space from the keyboard.
function activatable(el, run, label) {
  el.tabIndex = 0;
  el.setAttribute("role", "button");
  if (label) el.setAttribute("aria-label", label);
  el.addEventListener("click", e => { if (!e.target.closest("button, a, input")) run(); });
  el.addEventListener("keydown", e => {
    if (e.target === el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); run(); }
  });
}
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const imgUrl = (gid, file) => "/img/" + encodeURIComponent(gid) + "/" +
  encodeURIComponent(file) + "?t=" + encodeURIComponent(T);

// ---------------------------------------------------------------- icons
const _svg = (d, fill) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="${fill || "none"}" ` +
  `stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICON = {
  home: _svg('<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>'),
  docs: _svg('<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path d="M8 13h8M8 17h5"/>'),
  trash: _svg('<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/><path d="M10 11v6M14 11v6"/>'),
  settings: _svg('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>'),
  search: _svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
  plus: _svg('<path d="M12 5v14M5 12h14"/>'),
  bookmark: _svg('<path d="M6 3h12v18l-6-4-6 4z"/>'),
  bookmarkFill: _svg('<path d="M6 3h12v18l-6-4-6 4z"/>', "currentColor"),
  more: _svg('<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>', "currentColor"),
  grid: _svg('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'),
  list: _svg('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
  app: _svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'),
  back: _svg('<path d="M15 18l-6-6 6-6"/>'),
  edit: _svg('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
  done: _svg('<path d="M20 6 9 17l-5-5"/>'),
  export: _svg('<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>'),
  page: _svg('<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path d="M12 12v6M9 15h6"/>'),
  brush: _svg('<path d="M9.06 11.9 17 4a2.1 2.1 0 0 1 3 3l-7.9 7.94"/><path d="M7 14c-1.66 0-3 1.34-3 3 0 1.3-1 2-2 2 1 1.5 3 2 4 2a4 4 0 0 0 4-4c0-1.66-1.34-3-3-3z"/>'),
  sliders: _svg('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
  folder: _svg('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  monitor: _svg('<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>'),
  check: _svg('<path d="M20 6 9 17l-5-5"/>'),
  restore: _svg('<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/>'),
  rec: _svg('<circle cx="12" cy="12" r="5" fill="currentColor"/>'),
  stop: _svg('<rect x="7" y="7" width="10" height="10" rx="1" fill="currentColor"/>'),
  up: _svg('<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>'),
  down: _svg('<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>'),
  x: _svg('<path d="M18 6 6 18M6 6l12 12"/>'),
  fwd: _svg('<path d="m9 18 6-6-6-6"/>'),
  play: _svg('<path d="M7 4v16l13-8z"/>'),
};
const LOGO = `<svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><rect x="1" y="1" width="30" height="30" rx="8" fill="#fb923c"/>` +
  `<circle cx="16" cy="16" r="7.5" fill="none" stroke="#fff" stroke-width="3.2"/></svg>`;

// ---------------------------------------------------------------- navigation
// msg: a toast for the next page (a page that couldn't open says why, there)
const NAV_MSG = {guide: [tr("เปิดคู่มือนี้ไม่ได้ ไฟล์อาจเสียหายหรือถูกลบไปแล้ว"), "err"],
                 page: [tr("เปิด Page นี้ไม่ได้ ไฟล์อาจเสียหายหรือถูกลบไปแล้ว"), "err"],
                 sample: [tr("เพิ่มคู่มือตัวอย่างแล้ว"), "ok"]};
function nav(params) {
  location.search = "?" + new URLSearchParams({t: T, ...params}).toString();
}
function goGuide(id, mode) { nav({guide: id, mode: mode || "view"}); }

// ---------------------------------------------------------------- dialogs
function _dialog(inner, okLabel, okClass, onOpen, cancelLabel) {
  return new Promise(resolve => {
    const d = document.createElement("dialog");
    d.className = "ui-dlg";
    d.innerHTML = inner + `<div class="dlg-b"><button type="button" class="btn cancel">${esc(cancelLabel || tr("ยกเลิก"))}</button>` +
      `<button type="button" class="btn ${okClass || "dark"} ok">${esc(okLabel || tr("ตกลง"))}</button></div>`;
    document.body.appendChild(d);
    d.querySelector(".cancel").onclick = () => d.close("");
    d.querySelector(".ok").onclick = () => d.close("ok");
    d.addEventListener("close", () => { resolve(d.returnValue === "ok" ? d : null); d.remove(); });
    d.showModal();
    if (onOpen) onOpen(d);
  });
}

// A name that can't be blank: OK stays off, and says why, until there is text.
async function uiPrompt(label, value) {
  const d = await _dialog(`<p class="dlg-t">${esc(label)}</p>` +
    `<input class="dlg-in" type="text" value="${esc(value || "")}" aria-describedby="dlghint">` +
    `<div class="dlg-hint" id="dlghint" hidden>${tr("ต้องพิมพ์อย่างน้อย 1 ตัวอักษร")}</div>`, tr("ตกลง"), "dark", dlg => {
    const input = dlg.querySelector("input"), ok = dlg.querySelector(".ok"), hint = dlg.querySelector(".dlg-hint");
    const check = () => { ok.disabled = !input.value.trim(); return !ok.disabled; };
    input.oninput = () => { if (check()) hint.hidden = true; };
    check();
    input.focus(); input.select();
    input.addEventListener("keydown", e => {
      if (e.key !== "Enter") return;
      if (check()) dlg.close("ok"); else hint.hidden = false;
    });
  });
  return d ? d.querySelector("input").value : null;
}

async function uiConfirm(message, okLabel, cancelLabel) {
  return !!(await _dialog(`<p class="dlg-t">${esc(message)}</p>`, okLabel || tr("ตกลง"),
    okLabel ? "red" : "dark", null, cancelLabel));
}

// Leaving an edit page. When the latest edits can't be saved, say why and let
// the user stay (saving keeps retrying) or leave without them.
async function leaveEdit(flushFn, dropPending, to) {
  if (await flushFn()) return to();
  if (await uiConfirm(tr("บันทึกการแก้ไขล่าสุดไม่ได้\nไฟล์อาจถูกโปรแกรมอื่นเปิดค้างอยู่ หรือดิสก์เต็ม\nถ้าอยู่หน้านี้ต่อ ระบบจะลองบันทึกใหม่ให้เรื่อย ๆ"),
      tr("ออกโดยไม่บันทึก"), tr("อยู่หน้านี้ต่อ"))) {
    dropPending();
    to();
  }
}

// Toasts stack instead of covering each other; screen readers hear them.
function toast(text, ms = 2500, kind) {
  let box = document.getElementById("toasts");
  if (!box) {
    box = document.createElement("div");
    box.id = "toasts";
    box.setAttribute("role", "status");
    box.setAttribute("aria-live", "polite");
    document.body.appendChild(box);
  }
  const t = document.createElement("div");
  t.className = "toast" + (kind === "err" ? " err" : ""); t.textContent = text;
  box.appendChild(t);
  setTimeout(() => t.remove(), ms);
}
// A failure looks different from a success.
const toastErr = (text, ms = 6000) => toast(text, ms, "err");

// Popovers that close each other: only one is open at a time.
function closeOtherPops() {
  const rm = document.getElementById("recmenu"), tb = document.getElementById("tbpop");
  if (rm) rm.hidden = true;
  if (tb) tb.hidden = true;
}

// Small menu anchored under a button; closes on outside click or Esc, which
// gives focus back to the button. Arrow keys move between its items.
function popMenu(anchor, items) {
  closePopMenu();
  closeOtherPops();
  const m = document.createElement("div");
  m.className = "menu-pop";
  m.setAttribute("role", "menu");
  for (const it of items) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = it.label;
    b.setAttribute("role", "menuitem");
    if (it.danger) b.className = "danger";
    b.onclick = e => { e.stopPropagation(); closePopMenu(); it.run(); };
    m.appendChild(b);
  }
  m.addEventListener("keydown", e => {
    const bs = [...m.querySelectorAll("button")], i = bs.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      bs[(i + (e.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length].focus();
    } else if (e.key === "Tab") {
      closePopMenu(true);
    }
  });
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  m.style.top = (r.bottom + 4) + "px";
  m.style.left = Math.max(8, Math.min(r.right - m.offsetWidth, innerWidth - m.offsetWidth - 8)) + "px";
  anchor.closest(".ctools")?.classList.add("open");
  anchor.setAttribute("aria-expanded", "true");
  m._anchor = anchor;
  m.querySelector("button")?.focus();
}
function closePopMenu(refocus) {
  document.querySelectorAll(".menu-pop").forEach(m => {
    m._anchor?.closest(".ctools")?.classList.remove("open");
    m._anchor?.setAttribute("aria-expanded", "false");
    if (refocus && m.contains(document.activeElement)) m._anchor?.focus();
    m.remove();
  });
}
document.addEventListener("click", e => { if (!e.target.closest(".menu-pop")) closePopMenu(); });
// A file or link dropped anywhere must not navigate the window away (there is
// no address bar to come back); step cards handle their own reorder drops.
document.addEventListener("dragover", e => e.preventDefault());
document.addEventListener("drop", e => e.preventDefault());
document.addEventListener("keydown", e => { if (e.key === "Escape") closePopMenu(true); });

// ---------------------------------------------------------------- status poll
// Every page follows a recording that just finished (stopped from the panel, a
// hotkey or the tray) to its new guide, in edit mode. beforeLeave flushes edits.
let SEQ = null, POLL = null, TICK = null;
function startStatusPoll(onStatus, ms, beforeLeave) {
  TICK = async () => {
    let st;
    try { st = await getJSON("/api/status"); } catch { return; }
    if (st.recording && typeof TOUR_ABORT === "function") TOUR_ABORT();  // ui/tour.js
    onStatus(st);
    if (!COVER_HOLD) redactCover(st.redacting);
    if (SEQ === null) { SEQ = st.guide_seq; return; }
    if (st.guide_seq !== SEQ && st.last_guide) {
      SEQ = st.guide_seq;
      clearInterval(POLL);
      if (beforeLeave && (await beforeLeave()) === false) return;  // keep unsaved edits
      goGuide(st.last_guide, "edit");
    }
  };
  clearInterval(POLL);
  TICK();
  POLL = setInterval(TICK, ms);
}
// While a recording is auto-redacted the window is covered and inert (the
// server also refuses that guide until its blurs are in).
let COVER_HOLD = false;  // a guide page waiting on its pass owns the cover
function redactCover(r) {
  let c = document.getElementById("redcover");
  // the image editor keeps the page under it inert after the cover goes
  const inert = on => { for (const el of document.body.children)
    if (el !== c && el.id !== "toasts")
      el.inert = on || (el.id === "app" && typeof IED !== "undefined" && IED.open); };
  if (!r) { if (c) { c.remove(); c = null; inert(false); } return; }
  if (typeof TOUR_ABORT === "function") TOUR_ABORT();  // the cover owns the window
  if (!c) {
    document.activeElement?.blur?.();
    c = document.createElement("div");
    c.id = "redcover";
    document.body.appendChild(c);
    inert(true);
  }
  c.textContent = r[1] ? tr("กำลังซ่อนข้อมูล… {a}/{b}", {a: r[0], b: r[1]}) : tr("กำลังซ่อนข้อมูล…");
}
// timers in a minimized or hidden window are throttled; catch up when shown
document.addEventListener("visibilitychange", () => { if (!document.hidden && TICK) TICK(); });

function boot() {
  const gid = Q.get("guide"), pid = Q.get("pg");
  const msg = NAV_MSG[Q.get("msg")];
  if (msg) (msg[1] === "err" ? toastErr : toast)(msg[0], 8000);
  if (Q.get("guideme")) guideMePage(Q.get("guideme"));
  else if (gid) guidePage(gid, Q.get("mode") === "edit" ? "edit" : "view");
  else if (pid) pageDocPage(pid, Q.get("mode") === "edit" ? "edit" : "view");
  else shellPage(Q.get("page") || "home");
}
