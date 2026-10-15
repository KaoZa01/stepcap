// Guide page: view mode (full screenshots, TOC/meta switches), edit mode, and
// export. renderGuide + drawStepCanvas are self-contained so the exported file
// runs exactly the same rendering code as view mode.
"use strict";
let GID = null, STATE = null;
const app = document.getElementById("app");

// One step's screenshot: the crop (or the whole image), never zoomed; markers on
// top. maxW (optional) caps the canvas width, e.g. for grid thumbnails.
function drawStepCanvas(canvas, img, step, maxW) {
  const W = img.naturalWidth, H = img.naturalHeight;
  const c0 = step.crop || {x: 0, y: 0, w: W, h: H};
  const x = Math.min(Math.max(0, c0.x), W - 1), y = Math.min(Math.max(0, c0.y), H - 1);
  const r = {x, y, w: Math.min(c0.w, W - x), h: Math.min(c0.h, H - y)};  // crop kept inside the image
  const s = Math.min(1, (maxW || r.w) / r.w);
  canvas.width = Math.max(1, Math.round(r.w * s));
  canvas.height = Math.max(1, Math.round(r.h * s));
  const c = canvas.getContext("2d");
  c.drawImage(img, r.x, r.y, r.w, r.h, 0, 0, canvas.width, canvas.height);
  const k = Math.max(1, r.w / 960);  // keep rings visible once scaled down
  for (const m of step.markers || []) {
    const rad = m.size / 2;
    c.beginPath(); c.arc((m.x - r.x) * s, (m.y - r.y) * s, rad * s, 0, 2 * Math.PI);
    c.fillStyle = m.color + "26"; c.fill();
    c.lineWidth = Math.max(3 * k, rad * 0.14) * s; c.strokeStyle = m.color; c.stroke();
  }
}

// Read-only render of a whole guide into root. Each step's image comes from
// step._src. Notes: no number, not counted, not in the TOC.
async function renderGuide(guide, root) {
  const E = s => (s == null ? "" : String(s)).replace(/[&<>"']/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const S = guide.settings || {};
  const fmt = iso => {
    const d = new Date(iso);
    return iso && !isNaN(d) ? d.toLocaleDateString("th-TH", {year: "numeric", month: "short", day: "numeric"}) : "";
  };
  const numbered = guide.steps.filter(s => s.kind !== "note");
  const meta = [];
  if (S.step_count) meta.push(numbered.length + " ขั้นตอน");
  if (S.created && fmt(guide.created)) meta.push("สร้างเมื่อ " + fmt(guide.created));
  if (S.updated && fmt(guide.updated)) meta.push("แก้ไขล่าสุด " + fmt(guide.updated));
  let html = '<div class="rg-wrap"><h1>' + E(guide.title) + "</h1>";
  if (meta.length) html += '<div class="rg-meta">' + meta.map(E).join(" · ") + "</div>";
  if (S.toc && numbered.length)
    html += '<nav class="rg-toc"><b>สารบัญ</b><ol>' + numbered.map(s =>
      '<li><a href="#step-' + E(s.id) + '">' + E(s.text) + "</a></li>").join("") + "</ol></nav>";
  root.innerHTML = html + "</div>";
  const wrap = root.querySelector(".rg-wrap");
  let n = 0;
  for (const step of guide.steps) {
    const div = document.createElement("div");
    div.className = "rg-step";
    div.id = "step-" + step.id;
    if (step.kind === "note") {
      div.innerHTML = '<div class="rg-note">' + E(step.text) + "</div>";
    } else {
      div.innerHTML = '<div class="rg-head"><div class="rg-num">' + (++n) + "</div><div>" + E(step.text) + "</div></div>";
      if (step._src) {
        const cv = document.createElement("canvas");
        div.appendChild(cv);
        const img = new Image();
        img.onload = () => drawStepCanvas(cv, img, step);
        img.src = step._src;
      }
    }
    wrap.appendChild(div);
  }
}

async function guidePage(id, mode) {
  GID = id;
  try {
    const r = await api("/api/guide/" + encodeURIComponent(id));
    if (!r.ok) throw new Error(r.status);
    STATE = await r.json();
  } catch {
    return nav({page: "home"});
  }
  document.title = "StepCap - " + STATE.title;
  if (mode === "edit") editPage(); else viewPage();
}

function viewPage() {
  app.innerHTML = `<header class="gtop">
      <button class="icon-btn" id="back" title="กลับหน้าหลัก">${ICON.back}</button>
      <div class="gtitle">${esc(STATE.title)}</div>
      <button class="btn" id="edit">${ICON.edit} แก้ไข</button>
      <button class="btn dark" id="exp">${ICON.export} ส่งออก</button>
    </header><div class="gbody"><div id="rg"></div></div>`;
  document.getElementById("back").onclick = () => nav({page: "home"});
  document.getElementById("edit").onclick = () => goGuide(GID, "edit");
  document.getElementById("exp").onclick = () => exportGuide(GID);
  const g = {...STATE, steps: STATE.steps.map(s => s.image ? {...s, _src: imgUrl(GID, s.image)} : s)};
  renderGuide(g, document.getElementById("rg"));
  startStatusPoll(() => {}, 1000);
}

const asDataUrl = blob => new Promise(res => {
  const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob);
});

// One self-contained HTML file that looks like view mode; saved via Save As.
async function exportGuide(gid) {
  const g = await getJSON("/api/guide/" + encodeURIComponent(gid));
  const steps = [];
  for (const s of g.steps) {
    const c = {...s};
    if (s.image) c._src = await asDataUrl(await (await api("/img/" + encodeURIComponent(gid) +
      "/" + encodeURIComponent(s.image))).blob());
    delete c.image;
    steps.push(c);
  }
  // "<" escaped so step text such as "</script>" cannot end the script early
  const json = JSON.stringify({...g, steps}).replace(/</g, "\\u003c");
  const css = document.getElementById("rg-css").textContent;
  const html = `<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(g.title)}</title>
<style>body{margin:0;padding:32px 24px;background:#fff}${css}</style></head>
<body><div id="root"></div><script>const guide=${json};
${drawStepCanvas}
(${renderGuide})(guide, document.getElementById("root"));<\/script></body></html>`;
  const r = await (await api("/api/guide/" + encodeURIComponent(gid) + "/export",
    {method: "POST", headers: {"Content-Type": "text/html; charset=utf-8"}, body: html})).json();
  if (r.saved) toast("บันทึกไฟล์แล้ว");
}

// ---------------------------------------------------------------- edit mode
const KIND_TH = {click: "คลิก", rightclick: "คลิกขวา", doubleclick: "ดับเบิลคลิก", type: "พิมพ์",
  password: "รหัสผ่าน", shortcut: "ปุ่มลัด", note: "หมายเหตุ"};
const SWATCHES = ["#FB923C", "#EF4444", "#EAB308", "#22C55E", "#3B82F6", "#A855F7"];
const DOC_SWITCHES = [["toc", "สารบัญ"], ["step_count", "จำนวนขั้นตอน"],
  ["created", "วันที่สร้าง"], ["updated", "วันที่แก้ไขล่าสุด"]];
let SAVET = null, lastSize = 44, sel = null;
const clickColor = () => (STATE.settings.click_color || "#FB923C").toUpperCase();
const newStepId = () => "s" + Math.random().toString(16).slice(2, 10);

function saveNow() {
  clearTimeout(SAVET); SAVET = null;
  return post("/api/guide/" + encodeURIComponent(GID), STATE);
}
function scheduleSave() { clearTimeout(SAVET); SAVET = setTimeout(saveNow, 500); }
const flush = async () => { if (SAVET) await saveNow(); };

function editPage() {
  app.innerHTML = `<header class="gtop">
      <button class="icon-btn" id="back" title="กลับหน้าหลัก">${ICON.back}</button>
      <input id="title" class="gtitle" type="text" value="${esc(STATE.title)}">
      <button class="btn dark" id="done">${ICON.done} เสร็จสิ้น</button>
      <button class="btn" id="exp">${ICON.export} ส่งออก</button>
    </header><div class="gbody edit"><div class="ewrap" id="ewrap"></div></div>
    <div class="etb">
      <button type="button" class="tb off" aria-disabled="true" data-tip="เพิ่มลงหน้า · เร็วๆ นี้">${ICON.page}</button>
      <button type="button" class="tb" data-pop="color" data-tip="สีวงจุดคลิก">${ICON.brush}</button>
      <button type="button" class="tb" data-pop="doc" data-tip="ตั้งค่าเอกสาร">${ICON.sliders}</button>
      <div class="tbpop" id="tbpop" hidden></div>
    </div>`;
  document.getElementById("title").oninput = e => { STATE.title = e.target.value; scheduleSave(); };
  document.getElementById("back").onclick = async () => { await flush(); nav({page: "home"}); };
  document.getElementById("done").onclick = async () => { await flush(); goGuide(GID, "view"); };
  document.getElementById("exp").onclick = async () => { await flush(); exportGuide(GID); };
  document.querySelectorAll(".tb[data-pop]").forEach(b => b.onclick = e => {
    e.stopPropagation(); toggleToolPop(b.dataset.pop, b);
  });
  document.addEventListener("click", e => {
    if (!e.target.closest(".etb")) document.getElementById("tbpop").hidden = true;
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") document.getElementById("tbpop").hidden = true;
  });
  renderSteps();
  startStatusPoll(() => {}, 1000, flush);
}

// ---- toolbar popovers
function toggleToolPop(kind, btn) {
  const pop = document.getElementById("tbpop");
  if (!pop.hidden && pop.dataset.kind === kind) { pop.hidden = true; return; }
  pop.dataset.kind = kind;
  pop.style.top = btn.offsetTop + "px";
  (kind === "color" ? renderColorPop : renderDocPop)(pop);
  pop.hidden = false;
}

function renderColorPop(pop) {
  const cur = clickColor();
  pop.innerHTML = `<div class="pop-h">สีวงจุดคลิก</div>
    <div class="sw">${SWATCHES.map(c =>
      `<button type="button" class="swatch${c === cur ? " on" : ""}" data-c="${c}" style="background:${c}" title="${c}"></button>`).join("")}</div>
    <div class="custom"><input type="color" id="cc" value="${cur.toLowerCase()}" title="เลือกสีเอง">
      <input type="text" id="hex" class="dlg-in" value="${cur}" maxlength="7" spellcheck="false"></div>
    <div class="muted small">เปลี่ยนทุกวงในคู่มือนี้ และวงที่เพิ่มใหม่</div>`;
  pop.querySelectorAll(".swatch").forEach(b => b.onclick = () => setClickColor(b.dataset.c));
  pop.querySelector("#cc").onchange = e => setClickColor(e.target.value);
  pop.querySelector("#hex").oninput = e => {
    if (/^#[0-9a-f]{6}$/i.test(e.target.value)) setClickColor(e.target.value);
  };
}

// One color for every click marker of the guide; new markers use it too.
function setClickColor(hex) {
  const c = hex.toUpperCase();
  STATE.settings.click_color = c;
  for (const s of STATE.steps) for (const m of s.markers || []) m.color = c;
  renderSteps(); scheduleSave();
  const pop = document.getElementById("tbpop");
  if (pop.hidden || pop.dataset.kind !== "color") return;
  pop.querySelectorAll(".swatch").forEach(b => b.classList.toggle("on", b.dataset.c === c));
  const cc = pop.querySelector("#cc"), hx = pop.querySelector("#hex");
  if (document.activeElement !== cc) cc.value = c.toLowerCase();
  if (document.activeElement !== hx) hx.value = c;
}

function renderDocPop(pop) {
  const S = STATE.settings, grid = S.layout === "grid";
  pop.innerHTML = `<div class="pop-h">ตั้งค่าเอกสาร</div>
    ${DOC_SWITCHES.map(([k, label]) => `<label class="srow"><span>${label}</span>
      <span class="switch"><input type="checkbox" data-k="${k}" ${S[k] ? "checked" : ""}><span></span></span></label>`).join("")}
    <div class="pop-h" style="margin-top:12px">มุมมอง</div>
    <div class="seg wide"><button type="button" data-l="linear" class="${grid ? "" : "on"}">${ICON.list} เรียงต่อกัน</button>
      <button type="button" data-l="grid" class="${grid ? "on" : ""}">${ICON.grid} ตาราง</button></div>`;
  pop.querySelectorAll("input[data-k]").forEach(i => i.onchange = () => {
    S[i.dataset.k] = i.checked; scheduleSave();
  });
  pop.querySelectorAll("[data-l]").forEach(b => b.onclick = () => {
    S.layout = b.dataset.l; scheduleSave(); renderSteps(); renderDocPop(pop);
  });
}

// ---- steps (linear cards or grid thumbnails)
function renderSteps() {
  const host = document.getElementById("ewrap");
  let n = 0;
  const nums = STATE.steps.map(s => s.kind === "note" ? null : ++n);
  host.replaceChildren();
  if (STATE.settings.layout === "grid") {
    const g = document.createElement("div");
    g.className = "egrid";
    STATE.steps.forEach((s, i) => g.appendChild(gridCard(s, i, nums[i])));
    host.appendChild(g);
  } else {
    STATE.steps.forEach((s, i) => host.appendChild(stepCard(s, i, nums[i])));
  }
  const add = document.createElement("button");
  add.type = "button"; add.className = "btn"; add.textContent = "+ เพิ่มหมายเหตุ";
  add.onclick = () => {
    STATE.steps.push({id: newStepId(), kind: "note", text: "หมายเหตุ...", image: null, crop: null, markers: []});
    renderSteps(); scheduleSave();
  };
  host.appendChild(add);
}

function dropTarget(el, i) {
  el.addEventListener("dragover", e => e.preventDefault());
  el.addEventListener("drop", e => {
    e.preventDefault();
    const from = +e.dataTransfer.getData("text/plain");
    if (Number.isNaN(from) || from === i) return;
    const [m] = STATE.steps.splice(from, 1);
    STATE.steps.splice(i, 0, m);
    renderSteps(); scheduleSave();
  });
}
function dragSource(el, i) {
  el.addEventListener("dragstart", e => { e.dataTransfer.setData("text/plain", String(i)); el.classList.add("dragging"); });
  el.addEventListener("dragend", () => { el.classList.remove("dragging"); });
}

const stepBadge = num => num
  ? `<div class="num drag" title="ลากเพื่อสลับลำดับ">${num}</div>`
  : `<div class="notetag drag" title="ลากเพื่อสลับลำดับ">หมายเหตุ</div>`;

function stepCard(step, i, num) {
  const el = document.createElement("div");
  el.className = "step";
  el.id = "edit-" + step.id;
  el.innerHTML = `<div class="row1">${stepBadge(num)}
      <div class="txt">${num ? `<div class="kindtag">${esc(KIND_TH[step.kind] || step.kind)}</div>` : ""}
        <input type="text" class="stext" value="${esc(step.text)}"></div>
      <button type="button" class="btn danger del">ลบ</button></div>`;
  el.querySelector(".stext").oninput = e => { step.text = e.target.value; scheduleSave(); };
  el.querySelector(".del").onclick = async () => {
    if (!await uiConfirm("ลบขั้นตอนนี้?", "ลบ")) return;
    STATE.steps.splice(STATE.steps.indexOf(step), 1);
    renderSteps(); scheduleSave();
  };
  // drag only from the badge, so marker drags and text selection stay free
  const handle = el.querySelector(".drag");
  handle.onpointerdown = () => { el.draggable = true; };
  el.addEventListener("dragend", () => { el.draggable = false; });
  dragSource(el, i); dropTarget(el, i);
  if (step.image) el.appendChild(imageEditor(step));
  return el;
}

function gridCard(step, i, num) {
  const el = document.createElement("div");
  el.className = "gcard";
  el.draggable = true;
  el.title = "คลิกเพื่อแก้ไขขั้นตอนนี้";
  el.innerHTML = `<div class="gthumb">${step.image ? "<canvas></canvas>" : `<div class="gtext">${esc(step.text)}</div>`}</div>
    <div class="gcap">${num ? `<span class="num">${num}</span>` : `<span class="notetag">หมายเหตุ</span>`}
      <span class="gt">${esc(step.text)}</span></div>`;
  if (step.image) {
    const img = new Image();
    img.onload = () => drawStepCanvas(el.querySelector("canvas"), img, step, 480);
    img.src = imgUrl(GID, step.image);
  }
  dragSource(el, i); dropTarget(el, i);
  el.onclick = () => {
    STATE.settings.layout = "linear";
    scheduleSave(); renderSteps();
    const pop = document.getElementById("tbpop");
    if (!pop.hidden && pop.dataset.kind === "doc") renderDocPop(pop);
    document.getElementById("edit-" + step.id)?.scrollIntoView({block: "start"});
  };
  return el;
}

// ---- image editor: markers (add / drag / color / size / delete) and crop
function imageEditor(step) {
  const box = document.createElement("div");
  const tools = document.createElement("div");
  tools.className = "etools";
  tools.innerHTML = `<button type="button" class="btn addmk">+ เพิ่มวง</button>
    <button type="button" class="btn crop">ครอปภาพ</button>
    ${step.crop ? '<button type="button" class="btn uncrop">ล้างครอป</button>' : ""}`;
  box.appendChild(tools);
  const stage = document.createElement("div");
  stage.className = "stage";
  const img = document.createElement("img");
  img.src = imgUrl(GID, step.image);
  stage.appendChild(img);
  box.appendChild(stage);
  const ctrl = document.createElement("div");
  ctrl.className = "mk-ctrl";
  box.appendChild(ctrl);

  img.onload = () => {
    const natW = img.naturalWidth, natH = img.naturalHeight;
    const scale = () => stage.clientWidth / natW;
    step.markers = step.markers || [];

    function drawMarkers() {
      if (!stage.isConnected) { window.removeEventListener("resize", drawMarkers); return; }
      stage.querySelectorAll(".marker,.croprect").forEach(n => n.remove());
      const sc = scale();
      if (step.crop) {
        const cr = document.createElement("div");
        cr.className = "croprect";
        cr.style.left = step.crop.x * sc + "px"; cr.style.top = step.crop.y * sc + "px";
        cr.style.width = step.crop.w * sc + "px"; cr.style.height = step.crop.h * sc + "px";
        stage.appendChild(cr);
      }
      for (const m of step.markers) {
        const d = document.createElement("div");
        d.className = "marker" + (sel === m ? " sel" : "");
        d.style.left = m.x * sc + "px"; d.style.top = m.y * sc + "px";
        d.style.width = m.size * sc + "px"; d.style.height = m.size * sc + "px";
        d.style.borderColor = m.color; d.style.background = m.color + "26";
        d.onpointerdown = ev => startDrag(ev, m, sc);
        stage.appendChild(d);
      }
      renderCtrl();
    }
    function renderCtrl() {
      if (!sel || !step.markers.includes(sel)) { ctrl.innerHTML = ""; return; }
      ctrl.innerHTML = `สีวงนี้ <input type="color" class="mcol" value="${sel.color.toLowerCase()}">
        ขนาด <input type="range" class="msize" min="24" max="96" value="${sel.size}">
        <button type="button" class="btn danger mdel">ลบวง</button>`;
      ctrl.querySelector(".mcol").oninput = e => { sel.color = e.target.value.toUpperCase(); drawMarkers(); scheduleSave(); };
      ctrl.querySelector(".msize").oninput = e => { sel.size = lastSize = +e.target.value; drawMarkers(); scheduleSave(); };
      ctrl.querySelector(".mdel").onclick = () => {
        step.markers.splice(step.markers.indexOf(sel), 1); sel = null; drawMarkers(); scheduleSave();
      };
    }
    function startDrag(ev, m, sc) {
      ev.preventDefault(); sel = m; drawMarkers();
      const move = e => {
        const rect = stage.getBoundingClientRect();
        m.x = Math.max(0, Math.min(natW, (e.clientX - rect.left) / sc));
        m.y = Math.max(0, Math.min(natH, (e.clientY - rect.top) / sc));
        drawMarkers();
      };
      const up = () => {
        document.removeEventListener("pointermove", move);
        document.removeEventListener("pointerup", up);
        scheduleSave();
      };
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
    }

    tools.querySelector(".addmk").onclick = () => {
      stage.style.cursor = "crosshair";
      stage.onpointerdown = ev => {
        const rect = stage.getBoundingClientRect(), sc = scale();
        const m = {x: (ev.clientX - rect.left) / sc, y: (ev.clientY - rect.top) / sc, color: clickColor(), size: lastSize};
        step.markers.push(m); sel = m; stage.style.cursor = ""; stage.onpointerdown = null;
        drawMarkers(); scheduleSave();
      };
    };
    tools.querySelector(".crop").onclick = () => {
      stage.style.cursor = "crosshair";
      stage.onpointerdown = ev => {
        const r = stage.getBoundingClientRect();
        // pointer positions clamped to the stage, so a crop never leaves the image
        const at = e => ({x: Math.max(0, Math.min(r.width, e.clientX - r.left)),
                          y: Math.max(0, Math.min(r.height, e.clientY - r.top))});
        const start = at(ev);
        const rectEl = document.createElement("div");
        rectEl.className = "croprect"; stage.appendChild(rectEl);
        const box = e => { const p = at(e);
          return {x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y)}; };
        const move = e => { const b = box(e);
          rectEl.style.left = b.x + "px"; rectEl.style.top = b.y + "px";
          rectEl.style.width = b.w + "px"; rectEl.style.height = b.h + "px"; };
        const up = e => {
          document.removeEventListener("pointermove", move);
          document.removeEventListener("pointerup", up);
          stage.style.cursor = ""; stage.onpointerdown = null;
          const b = box(e), sc = scale();
          if (b.w > 10 && b.h > 10) {
            step.crop = {x: b.x / sc, y: b.y / sc, w: b.w / sc, h: b.h / sc};
            scheduleSave(); renderSteps();
          } else drawMarkers();
        };
        document.addEventListener("pointermove", move);
        document.addEventListener("pointerup", up);
      };
    };
    const un = tools.querySelector(".uncrop");
    if (un) un.onclick = () => { step.crop = null; scheduleSave(); renderSteps(); };

    stage.onclick = e => { if (e.target === img) { sel = null; drawMarkers(); } };
    drawMarkers();
    window.addEventListener("resize", drawMarkers);
  };
  return box;
}
