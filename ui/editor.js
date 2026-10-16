// Full-window image editor for one step: click targets, arrows, boxes, text,
// blur, black-out, crop, undo, replace and download. It draws with
// drawStepCanvas, so what you see here is what export and download produce.
// Every change goes straight into STATE and autosaves; "เสร็จ" only closes.
"use strict";

const IED_ICON = {
  select: _svg('<path d="M5 3l14 7-6 2-2 6z"/>'),
  marker: _svg('<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2" fill="currentColor"/>'),
  arrow: _svg('<path d="M5 19 19 5"/><path d="M9 5h10v10"/>'),
  box: _svg('<rect x="4" y="5" width="16" height="14" rx="1"/>'),
  text: _svg('<path d="M5 6V4h14v2"/><path d="M12 4v16"/><path d="M9 20h6"/>'),
  blur: _svg('<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>'),
  black: _svg('<rect x="4" y="6" width="16" height="12" rx="1" fill="currentColor"/>'),
  crop: _svg('<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M2 6h14a2 2 0 0 1 2 2v14"/>'),
  undo: _svg('<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>'),
  image: _svg('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>'),
};
const IED_TOOLS = [["select", "เลือก"], ["marker", "จุดคลิก"], ["arrow", "ลูกศร"], ["box", "กรอบ"],
  ["text", "ข้อความ"], ["blur", "เบลอ"], ["black", "ปิดดำ"], ["crop", "ครอป"]];
const LINE_W = [["บาง", 4], ["กลาง", 8], ["หนา", 14]];
const TEXT_SIZES = [["เล็ก", 28], ["กลาง", 40], ["ใหญ่", 56]];
const MIN_DRAG = 10;  // natural px; shorter drags draw nothing

// Editor state; also the hook the page-level tests drive.
const IED = {
  open: false, step: null, tool: "select", sel: null, history: [], img: null,
  ready: Promise.resolve(), canvas: null, color: "#FB923C", width: 8, size: 40,
  draft: null, drag: null, sliding: false,
  toImage(cx, cy) {
    const r = IED.canvas.getBoundingClientRect();
    return {x: (cx - r.left) * IED.canvas.width / r.width, y: (cy - r.top) * IED.canvas.height / r.height};
  },
  undo() { iedUndo(); },
  replaceImage(blob) { return iedReplace(blob); },
};

const iedSnap = () => JSON.stringify({image: IED.step.image, crop: IED.step.crop,
  markers: IED.step.markers, annotations: IED.step.annotations, redactions: IED.step.redactions});
function iedPush() {
  IED.history.push(iedSnap());
  if (IED.history.length > 100) IED.history.shift();
}
function iedChanged() { scheduleSave(); iedDraw(); iedOpts(); }

function openImageEditor(stepId) {
  if (IED.open) closeImageEditor();
  const step = STATE.steps.find(s => s.id === stepId);
  if (!step || !step.image) return;
  for (const k of ["markers", "annotations", "redactions"]) step[k] = step[k] || [];
  Object.assign(IED, {open: true, step, tool: "select", sel: null, history: [], img: null,
    draft: null, drag: null, color: clickStyle().color});
  const el = document.createElement("div");
  el.className = "ied";
  el.innerHTML = `<div class="ied-bar">
      ${IED_TOOLS.map(([t, label]) => `<button type="button" class="tb" data-tool="${t}" data-tip="${label}">${IED_ICON[t]}</button>`).join("")}
      <span class="sp"></span>
      <button type="button" class="tb" data-act="undo" data-tip="ย้อนกลับ (Ctrl+Z)">${IED_ICON.undo}</button>
      <button type="button" class="tb" data-act="replace" data-tip="เปลี่ยนภาพ">${IED_ICON.image}</button>
      <input type="file" accept="image/png,image/jpeg,image/gif" hidden>
      <button type="button" class="tb" data-act="download" data-tip="ดาวน์โหลดภาพ">${ICON.export}</button>
      <button type="button" class="btn dark" data-act="done">${ICON.done} เสร็จ</button>
    </div><div class="ied-opts"></div><div class="ied-stage"><canvas></canvas></div>`;
  document.body.appendChild(el);
  IED.canvas = el.querySelector("canvas");
  el.querySelectorAll("[data-tool]").forEach(b => b.onclick = () => {
    if (b.getAttribute("aria-disabled") !== "true") iedSetTool(b.dataset.tool);
  });
  const file = el.querySelector("input[type=file]");
  el.querySelector('[data-act="undo"]').onclick = iedUndo;
  el.querySelector('[data-act="replace"]').onclick = () => file.click();
  file.onchange = () => { if (file.files[0]) iedReplace(file.files[0]); file.value = ""; };
  el.querySelector('[data-act="download"]').onclick = () => downloadStepImage(IED.step);
  el.querySelector('[data-act="done"]').onclick = closeImageEditor;
  IED.canvas.onpointerdown = iedDown;
  IED.canvas.ondblclick = iedDblClick;
  document.addEventListener("pointermove", iedMove);
  document.addEventListener("pointerup", iedUp);
  document.addEventListener("keydown", iedKey);
  document.addEventListener("paste", iedPaste);
  window.addEventListener("resize", iedLayout);
  IED.ready = iedLoad();
}

function closeImageEditor() {
  if (!IED.open) return;
  document.removeEventListener("pointermove", iedMove);
  document.removeEventListener("pointerup", iedUp);
  document.removeEventListener("keydown", iedKey);
  document.removeEventListener("paste", iedPaste);
  window.removeEventListener("resize", iedLayout);
  document.querySelector(".ied")?.remove();
  Object.assign(IED, {open: false, history: [], sel: null, img: null, canvas: null});
  renderSteps();
}

function iedLoad() {
  return new Promise(resolve => {
    const img = new Image();
    img.onload = () => {
      IED.img = img;
      if (iedGif()) { IED.tool = "select"; IED.draft = null; }  // GIFs stay unedited
      iedLayout(); iedTools(); iedOpts(); resolve();
    };
    img.onerror = () => {
      IED.img = null;
      document.querySelector(".ied-stage").innerHTML = '<div class="imgfail">เปิดภาพนี้ไม่ได้</div>';
      resolve();
    };
    img.src = imgUrl(GID, IED.step.image);
  });
}

// Fit the whole (uncropped) image into the stage; small images stay 1:1.
function iedLayout() {
  if (!IED.img || !IED.canvas) return;
  const box = document.querySelector(".ied-stage").getBoundingClientRect();
  const W = IED.img.naturalWidth, H = IED.img.naturalHeight;
  const s = Math.min(1, (box.width - 48) / W, (box.height - 48) / H);
  IED.canvas.style.width = Math.max(1, Math.round(W * s)) + "px";
  IED.canvas.style.height = Math.max(1, Math.round(H * s)) + "px";
  iedDraw();
}

const iedUnit = () => IED.canvas.width / IED.canvas.getBoundingClientRect().width;  // natural px per screen px
const iedGif = () => isGif(IED.step);

function iedTools() {
  const gif = iedGif();
  document.querySelectorAll(".ied [data-tool]").forEach(b => {
    const off = gif && b.dataset.tool !== "select";
    b.classList.toggle("off", off);
    b.setAttribute("aria-disabled", off ? "true" : "false");
    b.dataset.tip = off ? "ใช้กับ GIF ไม่ได้" : IED_TOOLS.find(t => t[0] === b.dataset.tool)[1];
    b.classList.toggle("on", b.dataset.tool === IED.tool);
  });
  IED.canvas?.classList.toggle("crosshair", IED.tool !== "select");
}

function iedSetTool(t) {
  IED.tool = t; IED.sel = null; IED.draft = null;
  iedTools(); iedOpts(); iedDraw();
}

// ---- drawing: the step's own render plus editor-only overlays
function iedDraw() {
  if (!IED.img || !IED.canvas) return;
  const st = IED.step, c = IED.canvas;
  drawStepCanvas(c, IED.img, {...st, crop: null});
  const g = c.getContext("2d"), u = iedUnit(), W = c.width, H = c.height;
  if (st.crop) {
    const r = st.crop;
    g.save();
    g.fillStyle = "rgba(0,0,0,.45)";
    g.beginPath(); g.rect(0, 0, W, H); g.rect(r.x, r.y, r.w, r.h); g.fill("evenodd");
    g.setLineDash([10 * u, 6 * u]); g.lineWidth = 2 * u; g.strokeStyle = "#fff";
    g.strokeRect(r.x, r.y, r.w, r.h);
    g.restore();
  }
  const d = IED.draft;
  if (d) {
    g.save();
    g.setLineDash([8 * u, 5 * u]); g.lineWidth = 2 * u;
    g.strokeStyle = IED.tool === "crop" ? "#fff" : (IED.tool === "black" || IED.tool === "blur") ? "#111827" : IED.color;
    if (IED.tool === "arrow") { g.beginPath(); g.moveTo(d.a.x, d.a.y); g.lineTo(d.b.x, d.b.y); g.stroke(); }
    else { const r = iedRect(d.a, d.b); g.strokeRect(r.x, r.y, r.w, r.h); }
    g.restore();
  }
  if (IED.sel) {
    const it = IED.sel.item, b = iedBounds(it);
    g.save();
    g.lineWidth = 2 * u; g.strokeStyle = "#2563eb";
    if (iedResizable(it)) {
      g.strokeRect(b.x, b.y, b.w, b.h);
      g.fillStyle = "#fff";
      for (const c of iedCorners(it)) {  // handles, 10 screen px
        g.fillRect(c.x - 5 * u, c.y - 5 * u, 10 * u, 10 * u);
        g.strokeRect(c.x - 5 * u, c.y - 5 * u, 10 * u, 10 * u);
      }
    } else {
      g.strokeRect(b.x - 4 * u, b.y - 4 * u, b.w + 8 * u, b.h + 8 * u);
    }
    g.restore();
  }
}

function iedRect(a, b) {
  const W = IED.canvas.width, H = IED.canvas.height;
  const cl = (v, m) => Math.max(0, Math.min(m, v));
  const x1 = cl(Math.min(a.x, b.x), W), y1 = cl(Math.min(a.y, b.y), H);
  const x2 = cl(Math.max(a.x, b.x), W), y2 = cl(Math.max(a.y, b.y), H);
  return {x: x1, y: y1, w: x2 - x1, h: y2 - y1};
}

function iedBounds(it) {
  if (it.size && !it.type) return {x: it.x - it.size / 2, y: it.y - it.size / 2, w: it.size, h: it.size};  // marker
  if (it.type === "arrow") return iedRect({x: it.x1, y: it.y1}, {x: it.x2, y: it.y2});
  if (it.type === "text") {
    const g = IED.canvas.getContext("2d");
    g.font = "bold " + (it.size || 40) + 'px "Leelawadee UI","Segoe UI",sans-serif';
    return {x: it.x, y: it.y, w: g.measureText(it.text || "").width, h: (it.size || 40) * 1.25};
  }
  return {x: it.x, y: it.y, w: it.w, h: it.h};
}

function iedSegDist(p, a) {
  const vx = a.x2 - a.x1, vy = a.y2 - a.y1, L = vx * vx + vy * vy || 1;
  const t = Math.max(0, Math.min(1, ((p.x - a.x1) * vx + (p.y - a.y1) * vy) / L));
  return Math.hypot(p.x - (a.x1 + t * vx), p.y - (a.y1 + t * vy));
}

// Topmost first: markers, then annotations, then redactions.
function iedHit(p) {
  const st = IED.step, tol = 8 * iedUnit();
  const inside = (b, t) => p.x >= b.x - t && p.x <= b.x + b.w + t && p.y >= b.y - t && p.y <= b.y + b.h + t;
  for (const m of [...st.markers].reverse())
    if (inside(iedBounds(m), tol)) return {list: "markers", item: m};
  for (const a of [...st.annotations].reverse()) {
    if (a.type === "arrow" ? iedSegDist(p, a) <= (a.width || 8) / 2 + tol : inside(iedBounds(a), tol))
      return {list: "annotations", item: a};
  }
  for (const d of [...st.redactions].reverse())
    if (inside(d, tol)) return {list: "redactions", item: d};
  return null;
}

// Boxes, blurs and black-outs resize from their corners once selected.
const iedResizable = it => it && (it.type === "box" || it.type === "blur" || it.type === "black");
const iedCorners = it => [{x: it.x, y: it.y}, {x: it.x + it.w, y: it.y},
  {x: it.x + it.w, y: it.y + it.h}, {x: it.x, y: it.y + it.h}];  // tl, tr, br, bl
function iedHandleAt(p) {
  const it = IED.sel?.item;
  if (!iedResizable(it)) return -1;
  const tol = 8 * iedUnit();
  return iedCorners(it).findIndex(c => Math.abs(p.x - c.x) <= tol && Math.abs(p.y - c.y) <= tol);
}

function iedMoveItem(it, orig, dx, dy) {
  if (it.type === "arrow") Object.assign(it, {x1: orig.x1 + dx, y1: orig.y1 + dy, x2: orig.x2 + dx, y2: orig.y2 + dy});
  else Object.assign(it, {x: orig.x + dx, y: orig.y + dy});
}

// ---- pointer
async function iedDown(e) {
  if (!IED.img || (iedGif() && IED.tool !== "select")) return;
  const p = IED.toImage(e.clientX, e.clientY), st = IED.step;
  if (IED.tool === "select") {
    const h = iedHandleAt(p);
    if (h >= 0) {  // resize: the opposite corner stays put
      IED.drag = {handle: h, fixed: iedCorners(IED.sel.item)[(h + 2) % 4], moved: false};
      return;
    }
    IED.sel = iedHit(p);
    if (IED.sel) IED.drag = {start: p, orig: JSON.parse(JSON.stringify(IED.sel.item)), moved: false};
    iedDraw(); iedOpts();
  } else if (IED.tool === "marker") {
    iedPush();
    const m = {x: p.x, y: p.y, ...clickStyle()};
    st.markers.push(m);
    IED.sel = {list: "markers", item: m};
    iedChanged();
  } else if (IED.tool === "text") {
    const text = await uiPrompt("พิมพ์ข้อความ");
    if (text === null || !text.trim()) return;
    iedPush();
    const a = {type: "text", x: p.x, y: p.y, text: text.trim(), color: IED.color, size: IED.size};
    st.annotations.push(a);
    IED.sel = {list: "annotations", item: a};
    iedChanged();
  } else {
    IED.draft = {a: p, b: p};
  }
}

function iedMove(e) {
  if (!IED.open || !IED.img) return;
  const p = IED.toImage(e.clientX, e.clientY);
  if (IED.draft) { IED.draft.b = p; iedDraw(); return; }
  const d = IED.drag;
  if (d && IED.sel) {
    if (!d.moved) { iedPush(); d.moved = true; }
    if (d.handle !== undefined) {
      const r = iedRect(d.fixed, p);
      if (r.w >= MIN_DRAG && r.h >= MIN_DRAG) Object.assign(IED.sel.item, r);
    } else {
      iedMoveItem(IED.sel.item, d.orig, p.x - d.start.x, p.y - d.start.y);
    }
    iedDraw();
    return;
  }
  if (IED.tool === "select" && e.target === IED.canvas) {  // hover cursor
    const h = iedHandleAt(p);
    IED.canvas.style.cursor = h === 0 || h === 2 ? "nwse-resize" : h === 1 || h === 3 ? "nesw-resize"
      : iedHit(p) ? "move" : "";
  }
}

function iedUp(e) {
  if (!IED.open) return;
  if (IED.drag) {
    if (IED.drag.moved) scheduleSave();
    IED.drag = null;
    return;
  }
  const d = IED.draft;
  if (!d) return;
  IED.draft = null;
  if (iedGif()) return iedDraw();
  d.b = IED.toImage(e.clientX, e.clientY);
  const st = IED.step, t = IED.tool;
  if (t === "arrow") {
    if (Math.hypot(d.b.x - d.a.x, d.b.y - d.a.y) < MIN_DRAG) return iedDraw();
    iedPush();
    const a = {type: "arrow", x1: d.a.x, y1: d.a.y, x2: d.b.x, y2: d.b.y, color: IED.color, width: IED.width};
    st.annotations.push(a);
    IED.sel = {list: "annotations", item: a};
    return iedChanged();
  }
  const r = iedRect(d.a, d.b);
  if (r.w < MIN_DRAG || r.h < MIN_DRAG) return iedDraw();
  iedPush();
  if (t === "crop") {
    st.crop = r;
  } else if (t === "box") {
    const a = {type: "box", ...r, color: IED.color, width: IED.width};
    st.annotations.push(a);
    IED.sel = {list: "annotations", item: a};
  } else {
    const red = {type: t, ...r};  // "blur" | "black"
    st.redactions.push(red);
    IED.sel = {list: "redactions", item: red};
  }
  iedChanged();
}

async function iedDblClick(e) {
  if (IED.tool !== "select") return;
  const hit = iedHit(IED.toImage(e.clientX, e.clientY));
  if (!hit || hit.item.type !== "text") return;
  const text = await uiPrompt("แก้ข้อความ", hit.item.text);
  if (text === null || !text.trim() || text.trim() === hit.item.text) return;
  iedPush();
  hit.item.text = text.trim();
  iedChanged();
}

function iedDelete() {
  if (!IED.sel) return;
  iedPush();
  const list = IED.step[IED.sel.list];
  list.splice(list.indexOf(IED.sel.item), 1);
  IED.sel = null;
  iedChanged();
}

function iedKey(e) {
  if (!IED.open || document.querySelector("dialog[open]")) return;
  if (e.target instanceof Element && e.target.closest("input[type=text], textarea")) return;
  // e.code is the physical key: on a Thai layout Ctrl+Z arrives with e.key "ผ"
  if ((e.ctrlKey || e.metaKey) && (e.code === "KeyZ" || e.key.toLowerCase() === "z")) {
    e.preventDefault(); iedUndo();
  }
  else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); iedDelete(); }
  else if (e.key === "Escape") {
    if (IED.tool !== "select") iedSetTool("select");
    else { IED.sel = null; iedDraw(); iedOpts(); }
  }
}

function iedPaste(e) {
  if (!IED.open) return;
  const item = [...(e.clipboardData?.items || [])]
    .find(i => i.kind === "file" && i.type.startsWith("image/"));
  if (!item) return;
  e.preventDefault();
  iedReplace(item.getAsFile());
}

function iedUndo() {
  const snap = IED.history.pop();
  if (!snap) return;
  const prevImage = IED.step.image;
  Object.assign(IED.step, JSON.parse(snap));
  IED.sel = null; IED.drag = null; IED.draft = null;
  scheduleSave();
  if (IED.step.image !== prevImage) IED.ready = iedLoad();
  else { iedDraw(); iedOpts(); }
}

// A new picture for this step: overlays belong to the old one, so they go
// (undo brings both back; the old file stays on disk).
async function iedReplace(blob) {
  const name = await uploadImage(blob);
  if (!name) return false;
  iedPush();
  Object.assign(IED.step, {image: name, crop: null, markers: [], annotations: [], redactions: []});
  IED.sel = null;
  if (iedGif()) IED.tool = "select";
  scheduleSave();
  IED.ready = iedLoad();
  await IED.ready;
  return true;
}

// ---- options row: for the active tool or the selection
function iedOpts() {
  const row = document.querySelector(".ied-opts");
  if (!row) return;
  if (iedGif()) { row.innerHTML = '<span class="muted">ภาพ GIF แก้ได้แค่เปลี่ยนภาพหรือดาวน์โหลด</span>'; return; }
  const it = IED.sel?.item, t = IED.tool;
  const kind = it ? (it.type || "marker") : t;
  const seg = (label, items, cur, key) => `<span class="muted">${label}</span><div class="seg">${
    items.map(([l, v]) => `<button type="button" data-${key}="${v}" class="${v === cur ? "on" : ""}">${l}</button>`).join("")}</div>`;
  let h = "";
  if (["marker", "arrow", "box", "text"].includes(kind)) {
    const cur = (it ? it.color : IED.color).toUpperCase();
    h += `<span class="muted">สี</span><div class="sw">${SWATCHES.map(c =>
      `<button type="button" class="swatch${c === cur ? " on" : ""}" data-c="${c}" style="background:${c}" title="${c}"></button>`).join("")}</div>
      <input type="color" class="icol" value="${cur.toLowerCase()}" title="เลือกสีเอง">`;
  }
  if (kind === "arrow" || kind === "box") h += seg("เส้น", LINE_W, it ? it.width : IED.width, "w");
  if (kind === "text") h += seg("ขนาดตัวอักษร", TEXT_SIZES, it ? it.size : IED.size, "ts");
  if (it && kind === "marker")
    h += seg("รูปทรง", [["วงกลม", "circle"], ["สี่เหลี่ยม", "rect"]], it.shape || "circle", "shape") +
      `<span class="muted">ขนาด</span><input type="range" class="msz" min="24" max="96" value="${it.size}">`;
  if (t === "crop" && IED.step.crop) h += `<button type="button" class="btn" data-op="uncrop">ล้างครอป</button>`;
  if (it) h += `<button type="button" class="btn danger" data-op="del">ลบ</button>`;
  if (!h) h = `<span class="muted">${t === "select" ? "คลิกเลือกสิ่งที่วาดไว้เพื่อย้าย แก้ หรือลบ"
    : t === "crop" ? "ลากเพื่อเลือกส่วนที่จะเก็บไว้" : "ลากบนภาพเพื่อวาด"}</span>`;
  row.innerHTML = h;
  const edit = fn => { if (it) { iedPush(); fn(it); iedChanged(); } else { iedOpts(); } };
  row.querySelectorAll("[data-c]").forEach(b => b.onclick = () => {
    IED.color = b.dataset.c; edit(x => { x.color = b.dataset.c; });
  });
  const icol = row.querySelector(".icol");
  if (icol) icol.onchange = () => {
    const c = icol.value.toUpperCase();
    IED.color = c; edit(x => { x.color = c; });
  };
  row.querySelectorAll("[data-w]").forEach(b => b.onclick = () => {
    IED.width = +b.dataset.w; edit(x => { x.width = +b.dataset.w; });
  });
  row.querySelectorAll("[data-ts]").forEach(b => b.onclick = () => {
    IED.size = +b.dataset.ts; edit(x => { x.size = +b.dataset.ts; });
  });
  row.querySelectorAll("[data-shape]").forEach(b => b.onclick = () => edit(x => { x.shape = b.dataset.shape; }));
  const msz = row.querySelector(".msz");
  if (msz) {
    msz.oninput = () => {
      if (!IED.sliding) { iedPush(); IED.sliding = true; }
      it.size = +msz.value; iedDraw();
    };
    msz.onchange = () => { IED.sliding = false; scheduleSave(); };
  }
  row.querySelector('[data-op="uncrop"]')?.addEventListener("click", () => {
    iedPush(); IED.step.crop = null; iedChanged();
  });
  row.querySelector('[data-op="del"]')?.addEventListener("click", iedDelete);
}
