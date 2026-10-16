// Guide page: view mode (full screenshots, TOC/meta switches), edit mode, and
// export. renderGuide + drawStepCanvas are self-contained so the exported file
// runs exactly the same rendering code as view mode.
"use strict";
let GID = null, STATE = null;
const app = document.getElementById("app");

// One step's screenshot: the crop (or the whole image), never zoomed, with its
// layers on top in this order: redactions -> annotations -> click markers.
// Layer coordinates are full-image pixels. maxW (optional) caps the canvas
// width, e.g. for grid thumbnails. Self-contained: exports embed its source.
function drawStepCanvas(canvas, img, step, maxW) {
  const W = img.naturalWidth, H = img.naturalHeight;
  const c0 = step.crop || {x: 0, y: 0, w: W, h: H};
  const x = Math.min(Math.max(0, c0.x), W - 1), y = Math.min(Math.max(0, c0.y), H - 1);
  const r = {x, y, w: Math.min(c0.w, W - x), h: Math.min(c0.h, H - y)};  // crop kept inside the image
  const s = Math.min(1, (maxW || r.w) / r.w);
  canvas.width = Math.max(1, Math.round(r.w * s));
  canvas.height = Math.max(1, Math.round(r.h * s));
  const c = canvas.getContext("2d");
  c.setTransform(s, 0, 0, s, -r.x * s, -r.y * s);  // draw in image pixels; the canvas edge crops
  c.drawImage(img, 0, 0);
  // Redactions: blur samples a copy that already has every black-out painted
  // (a blur never brings back what was blacked out), over an opaque base (at
  // the image edge the blurred copy is partly transparent and would show the
  // original through). Black-outs are painted again last.
  const reds = step.redactions || [];
  const blacks = reds.filter(d => d.type !== "blur");
  let src = img;
  if (blacks.length && blacks.length < reds.length) {
    src = document.createElement("canvas");
    src.width = W; src.height = H;
    const g = src.getContext("2d");
    g.drawImage(img, 0, 0);
    g.fillStyle = "#000";
    for (const d of blacks) g.fillRect(d.x, d.y, d.w, d.h);
  }
  for (const d of reds) {
    if (d.type !== "blur") continue;
    c.save();
    c.beginPath(); c.rect(d.x, d.y, d.w, d.h); c.clip();
    c.fillStyle = "#808080"; c.fillRect(d.x, d.y, d.w, d.h);
    c.filter = "blur(" + Math.max(16, Math.round(Math.min(d.w, d.h) / 4)) + "px)";
    c.drawImage(src, 0, 0);
    c.restore();
  }
  c.fillStyle = "#000";
  for (const d of blacks) c.fillRect(d.x, d.y, d.w, d.h);
  for (const a of step.annotations || []) {
    c.save();
    c.strokeStyle = c.fillStyle = a.color || "#EF4444";
    c.lineWidth = a.width || 8; c.lineJoin = "round"; c.lineCap = "round";
    if (a.type === "box") {
      c.strokeRect(a.x, a.y, a.w, a.h);
    } else if (a.type === "arrow") {
      const ang = Math.atan2(a.y2 - a.y1, a.x2 - a.x1), L = Math.max(14, (a.width || 8) * 3.5);
      const sp = 28 * Math.PI / 180;
      c.beginPath(); c.moveTo(a.x1, a.y1);
      c.lineTo(a.x2 - L * 0.7 * Math.cos(ang), a.y2 - L * 0.7 * Math.sin(ang)); c.stroke();
      c.beginPath(); c.moveTo(a.x2, a.y2);
      c.lineTo(a.x2 - L * Math.cos(ang - sp), a.y2 - L * Math.sin(ang - sp));
      c.lineTo(a.x2 - L * Math.cos(ang + sp), a.y2 - L * Math.sin(ang + sp));
      c.closePath(); c.fill();
    } else if (a.type === "text") {
      const size = a.size || 40;
      c.font = "bold " + size + 'px "Leelawadee UI","Segoe UI",sans-serif';
      c.textBaseline = "top";
      c.lineWidth = size * 0.18; c.strokeStyle = "#fff";  // white edge: readable on any background
      c.strokeText(a.text || "", a.x, a.y);
      c.fillText(a.text || "", a.x, a.y);
    }
    c.restore();
  }
  const k = Math.max(1, r.w / 960);  // keep rings visible once scaled down
  for (const m of step.markers || []) {
    const rad = m.size / 2;
    c.beginPath();
    if (m.shape === "rect") c.roundRect(m.x - rad, m.y - rad, m.size, m.size, m.size * 0.2);
    else c.arc(m.x, m.y, rad, 0, 2 * Math.PI);
    c.fillStyle = m.color + "26"; c.fill();
    c.lineWidth = Math.max(3 * k, rad * 0.14); c.strokeStyle = m.color; c.stroke();
  }
  c.setTransform(1, 0, 0, 1, 0, 0);
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
  const numbered = guide.steps.filter(s => s.kind !== "note" && s.kind !== "section");
  // a page: "section" entries open each guide or text block; numbering restarts
  const secs = guide.steps.filter(s => s.kind === "section" && !s.missing);
  const meta = guide.meta_count ? [guide.meta_count] : [];
  if (S.step_count) meta.push(numbered.length + " ขั้นตอน");
  if (S.created && fmt(guide.created)) meta.push("สร้างเมื่อ " + fmt(guide.created));
  if (S.updated && fmt(guide.updated)) meta.push("แก้ไขล่าสุด " + fmt(guide.updated));
  let html = '<div class="rg-wrap"><h1>' + E(guide.title) + "</h1>";
  if (meta.length) html += '<div class="rg-meta">' + meta.map(E).join(" · ") + "</div>";
  if (guide.description) html += '<p class="rg-desc">' + E(guide.description) + "</p>";  // a page's
  const toc = secs.length ? secs.filter(s => s.text) : numbered;  // an untitled text block: no entry
  if (S.toc && toc.length)
    html += '<nav class="rg-toc"><b>สารบัญ</b><ol>' + toc.map(s =>
      '<li><a href="#step-' + E(s.id) + '">' + E(s.text) + "</a></li>").join("") + "</ol></nav>";
  root.innerHTML = html + "</div>";
  const wrap = root.querySelector(".rg-wrap");
  let n = 0;
  for (const step of guide.steps) {
    const div = document.createElement("div");
    div.className = "rg-step";
    div.id = "step-" + step.id;
    if (step.kind === "section") {
      n = 0;
      div.className = "rg-secwrap";
      div.innerHTML = step.missing ? '<div class="rg-missing">' + E(step.text) + "</div>"
        : (step.text ? '<h2 class="rg-sec">' + E(step.text) + "</h2>" : "") +
          (step.body ? '<p class="rg-body">' + E(step.body) + "</p>" : "");
    } else if (step.kind === "note") {
      div.innerHTML = '<div class="rg-note">' + E(step.text) + "</div>";
    } else {
      div.innerHTML = '<div class="rg-head"><div class="rg-num">' + (++n) + "</div><div>" + E(step.text) + "</div></div>";
      if (step._src && (step._gif || step._img || /\.gif$/i.test(step.image || ""))) {
        const gif = document.createElement("img");  // GIF animated as-is; _img: baked, for print
        gif.className = "rg-gif"; gif.alt = step.text || ""; gif.src = step._src;
        div.appendChild(gif);
      } else if (step._src) {
        const cv = document.createElement("canvas");
        div.appendChild(cv);
        const img = new Image();
        img.onload = () => drawStepCanvas(cv, img, step);
        img.src = step._src;
      }
    }
    wrap.appendChild(div);
  }
  if (!guide.steps.length) wrap.insertAdjacentHTML("beforeend", '<p class="rg-empty">ยังไม่มีขั้นตอน</p>');
}

async function guidePage(id, mode) {
  GID = id;
  try {
    let r;
    while ((r = await api("/api/guide/" + encodeURIComponent(id))).status === 409) {
      COVER_HOLD = true;
      redactCover([0, 0]);  // its auto-redaction pass is still running
      await new Promise(res => setTimeout(res, 500));
    }
    if (COVER_HOLD) { COVER_HOLD = false; redactCover(null); }
    if (!r.ok) throw new Error(r.status);
    STATE = await r.json();
  } catch {
    return nav({page: "home", msg: "guide"});
  }
  document.title = "StepCap - " + STATE.title;
  const note = STATE.redact_note;  // what auto-redaction could not cover; never saved back
  delete STATE.redact_note;
  if (mode === "edit") editPage(); else viewPage();
  if (note) toast(note, 8000);
}

function viewPage() {
  app.innerHTML = `<header class="gtop">
      <button class="icon-btn" id="back" title="กลับหน้าแรก" aria-label="กลับหน้าแรก">${ICON.back}</button>
      <div class="gtitle">${esc(STATE.title)}</div>
      <button class="btn" id="edit">${ICON.edit} แก้ไข</button>
      <button class="btn dark" id="exp">${ICON.export} ส่งออก</button>
    </header><div class="gbody"><div id="rg"></div>
      ${STATE.steps.length ? "" : `<p class="muted">กด <b>แก้ไข</b> เพื่อเพิ่มภาพหรือหมายเหตุ หรือบันทึกใหม่จากหน้าแรก</p>`}</div>`;
  document.getElementById("back").onclick = () => nav({page: "home"});
  document.getElementById("edit").onclick = () => goGuide(GID, "edit");
  document.getElementById("exp").onclick = e => { e.stopPropagation(); exportMenu(e.currentTarget, GID); };
  const g = {...STATE, steps: STATE.steps.map(s => s.image ? {...s, _src: imgUrl(GID, s.image)} : s)};
  renderGuide(g, document.getElementById("rg"));
  startStatusPoll(() => {}, 1000);
}

const asDataUrl = blob => new Promise(res => {
  const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob);
});

const isGif = s => /\.gif$/i.test(s.image || "");

// The finished picture of one step, as export and download ship it: crop and
// every layer drawn into the pixels, so hidden parts are really gone.
function renderStepPng(step, gid) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const cv = document.createElement("canvas");
      drawStepCanvas(cv, img, step);
      cv.toBlob(b => b ? resolve(b) : reject(new Error("toBlob failed")), "image/png");
    };
    img.onerror = () => reject(new Error("image failed to load: " + step.image));
    img.src = imgUrl(gid, step.image);
  });
}

// One self-contained HTML file that looks like view mode. Every non-GIF image
// is flattened first, so no original screenshot ever leaves the machine. The
// file is plain HTML (pictures as <img>, no script): it reads the same in an
// e-mail preview or a viewer that blocks JavaScript, and its text is searchable.
// print: the PDF source -- adds A4 CSS with page numbers.
// ponytail: one string with data URLs; past ~400 MB of pictures the JS string
// limit throws and the export says it failed. Ship pictures as files if a
// guide ever gets that big (Markdown/Word already send raw blobs).
async function buildExportHtml(gid, {print = false, failed = [], doc = null} = {}) {
  const g = doc || await getJSON("/api/guide/" + encodeURIComponent(gid));
  const label = stepLabels(g), steps = [];
  for (const s of g.steps) {
    if (s.kind === "section" && s.missing) continue;  // a deleted guide: left out of the file
    const c = {...s}, home = s.gid || gid;  // a page's steps come from several guides
    try {
      if (s.image && isGif(s)) {
        const res = await api("/img/" + encodeURIComponent(home) + "/" + encodeURIComponent(s.image));
        if (!res.ok) throw new Error("gif " + res.status);  // gone: say so, don't embed the 404 text
        c._src = await asDataUrl(await res.blob());
        c._gif = true;
      } else if (s.image) {
        c._src = await asDataUrl(await renderStepPng(s, home));
        Object.assign(c, {crop: null, markers: [], annotations: [], redactions: []});
        c._img = true;
      }
    } catch {  // an unreadable image is exported without its picture
      failed.push(label[s.id]);
      delete c._src;
      Object.assign(c, {crop: null, markers: [], annotations: [], redactions: []});
    }
    delete c.image;
    steps.push(c);
  }
  const holder = document.createElement("div");
  await renderGuide({...g, steps}, holder);  // every picture is an <img> here: no canvas, no script
  const css = document.getElementById("rg-css").textContent;
  return `<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="generator" content="StepCap">
<title>${esc(g.title)}</title>
<style>body{margin:0;padding:32px 24px;background:#fff}@media (max-width:480px){body{padding:16px 12px}}
${css}${print ? PRINT_CSS : ""}</style></head>
<body>${holder.innerHTML}</body></html>`;
}

// A4 with "page / pages" at the bottom; a step never splits across pages and
// a heading never sits alone at the foot of one.
const PRINT_CSS = "@page{size:A4;margin:14mm 14mm 16mm;" +
  "@bottom-center{content:counter(page) \" / \" counter(pages);font:10px 'Segoe UI',sans-serif;color:#6b7280}}" +
  "body{padding:0}.rg-step{break-inside:avoid}.rg-secwrap{break-after:avoid}" +
  ".rg-step img{max-width:100%;max-height:230mm;width:auto;height:auto}";

// What a toast calls each step: its number, or "<guide> ขั้นที่ n" on a page
// (numbers restart after each section there).
function stepLabels(g) {
  const out = {};
  let n = 0, sec = null;
  for (const s of g.steps) {
    if (s.kind === "section") { n = 0; sec = s.text || ""; continue; }
    if (s.kind === "note") continue;
    n++;
    out[s.id] = sec === null ? n : `${sec} ขั้นที่ ${n}`;
  }
  return out;
}

// Labels sorted as the steps appear (the page's failures and the server's arrive apart).
function byDocOrder(labels, g) {
  const at = Object.values(stepLabels(g));
  return [...labels].sort((a, b) => at.indexOf(a) - at.indexOf(b));
}

// Finished pictures for Markdown and Word: every PNG comes from renderStepPng,
// so hidden parts are really gone; a GIF is only flagged (the server reads it
// from its guide folder). Sent as raw blobs after a JSON index -- never one
// giant base64 string. failed: labels of steps whose picture couldn't be drawn.
async function exportImages(g, gid) {
  const index = [], blobs = [], failed = [], label = stepLabels(g);
  for (const s of g.steps) {
    if (s.kind === "note" || s.kind === "section" || !s.image) continue;
    if (isGif(s)) { index.push({id: s.id, ext: "gif"}); continue; }
    try {
      const b = await renderStepPng(s, s.gid || gid);
      index.push({id: s.id, ext: "png", size: b.size});
      blobs.push(b);
    } catch { failed.push(label[s.id]); }
  }
  return {index, blobs, failed};
}

const EXPORT_FORMATS = [["html", "HTML"], ["pdf", "PDF"], ["md", "Markdown (.zip)"], ["docx", "Word (.docx)"]];
function exportMenu(anchor, id, kind = "guide") {
  popMenu(anchor, EXPORT_FORMATS.map(([f, label]) => ({label, run: () => exportDoc(kind, id, f)})));
}

// A guide, or a page compiled into one document, built in the page (pictures)
// and Python (assembly), saved via Save As.
let EXPORTING = false;
async function exportDoc(kind, id, format = "html") {
  if (EXPORTING) return;
  EXPORTING = true;
  toast("กำลังส่งออก…", 3600000);  // stays until the result replaces it
  const base = `/api/${kind}/${encodeURIComponent(id)}`, failed = [];
  const busy = {error: kind === "page" ? "คู่มือใน Page นี้กำลังซ่อนข้อมูลอยู่ ลองใหม่อีกครั้ง"
    : "คู่มือนี้กำลังซ่อนข้อมูลอยู่ ลองใหม่อีกครั้ง"};
  let r, doc;
  try {
    const src = await api(kind === "page" ? base + "/doc" : base);
    if (!src.ok) throw src.status === 409 ? busy : new Error(src.status);
    doc = await src.json();
    let body, type = "text/html; charset=utf-8";
    if (format === "html" || format === "pdf") {
      body = await buildExportHtml(id, {print: format === "pdf", failed, doc});
    } else {
      const x = await exportImages(doc, id);
      failed.push(...x.failed);
      body = new Blob([JSON.stringify({images: x.index}) + "\n", ...x.blobs]);
      type = "application/octet-stream";
    }
    const res = await api(base + "/export?format=" + format, {method: "POST", headers: {"Content-Type": type}, body});
    r = res.ok ? await res.json() : res.status === 409 ? busy : {error: "โปรแกรมตอบกลับผิดพลาด ลองใหม่อีกครั้ง"};
  } catch (e) {
    r = e === busy ? busy : {error: "เตรียมภาพหรือเนื้อหาไม่ได้ ลองใหม่อีกครั้ง"};
  } finally {
    EXPORTING = false;
  }
  document.querySelectorAll(".toast").forEach(t => t.remove());
  if (r.error) return toastErr("ส่งออกไม่สำเร็จ: " + r.error, 8000);
  if (!r.saved) return;  // cancelled
  const name = String(r.saved).split(/[\\/]/).pop();
  failed.push(...(r.missing || []));  // pictures the server couldn't use (e.g. a GIF gone)
  const notes = [];
  if (failed.length) notes.push(`ภาพของขั้นที่ ${byDocOrder(failed, doc).join(", ")} อ่านไม่ได้ ส่งออกโดยไม่มีภาพ`);
  if (r.skipped) notes.push(`ข้ามคู่มือที่ถูกลบ ${r.skipped} อัน`);
  for (const n of doc?.redact_notes || []) notes.push(n);  // a guide its pass couldn't cover
  if (notes.length) toastErr(`บันทึก ${name} แล้ว แต่` + notes.join(" และ"), 10000);
  else toast(`บันทึก ${name} แล้ว`, 4000);
}

// ---------------------------------------------------------------- edit mode
const KIND_TH = {click: "คลิก", rightclick: "คลิกขวา", doubleclick: "ดับเบิลคลิก", type: "พิมพ์",
  password: "รหัสผ่าน", shortcut: "ปุ่มลัด", note: "หมายเหตุ", image: "ภาพ"};
const SWATCHES = ["#FB923C", "#EF4444", "#EAB308", "#22C55E", "#3B82F6", "#A855F7"];
const DOC_SWITCHES = [["toc", "สารบัญ"], ["step_count", "จำนวนขั้นตอน"],
  ["created", "วันที่สร้าง"], ["updated", "วันที่แก้ไขล่าสุด"]];
const UPLOAD_FAILED = "ไฟล์นี้ใช้ไม่ได้ รองรับ PNG, JPG, GIF ขนาดไม่เกิน 25 MB";
let SAVET = null;
// The guide's click-target style; new markers use it.
const clickStyle = () => ({
  color: (STATE.settings.click_color || "#FB923C").toUpperCase(),
  shape: STATE.settings.click_shape || "circle",
  size: +STATE.settings.click_size || 44,
});
const newStepId = () => "s" + Math.random().toString(16).slice(2, 10);

let SAVE_FAILING = false;
// Autosave. A failed save keeps the edits pending, says so once, and retries.
async function saveNow() {
  clearTimeout(SAVET); SAVET = null;
  let ok = false;
  try { ok = (await post("/api/guide/" + encodeURIComponent(GID), STATE)).ok; } catch { /* offline */ }
  if (!ok) {
    if (!SAVE_FAILING) toastErr("บันทึกไม่สำเร็จ จะลองใหม่อัตโนมัติ");
    SAVE_FAILING = true;
    SAVET = setTimeout(saveNow, 3000);
  } else if (SAVE_FAILING) {
    SAVE_FAILING = false;
    toast("บันทึกแล้ว");
  }
  return ok;
}
function scheduleSave() { clearTimeout(SAVET); SAVET = setTimeout(saveNow, 500); }
// true when nothing is left unsaved; callers stay on the page otherwise
const flush = async () => !SAVET || await saveNow();

function editPage() {
  app.innerHTML = `<header class="gtop">
      <button class="icon-btn" id="back" title="กลับหน้าแรก" aria-label="กลับหน้าแรก">${ICON.back}</button>
      <input id="title" class="gtitle" type="text" value="${esc(STATE.title)}" aria-label="ชื่อคู่มือ">
      <button class="btn" id="done">${ICON.done} เสร็จสิ้น</button>
      <button class="btn dark" id="exp">${ICON.export} ส่งออก</button>
    </header><div class="gbody edit"><div class="ewrap" id="ewrap"></div></div>
    <div class="etb">
      <button type="button" class="tb" data-act="addpage" data-tip="เพิ่มลง Page">${ICON.page}</button>
      <button type="button" class="tb" data-pop="click" data-tip="จุดคลิก (สี รูปทรง ขนาด)">${ICON.brush}</button>
      <button type="button" class="tb" data-pop="doc" data-tip="ตั้งค่าเอกสาร">${ICON.sliders}</button>
      <div class="tbpop" id="tbpop" hidden></div>
    </div>`;
  app.querySelectorAll(".tb[data-tip]").forEach(b => b.setAttribute("aria-label", b.dataset.tip));
  const drop = () => { clearTimeout(SAVET); SAVET = null; SAVE_FAILING = false; };
  document.getElementById("title").oninput = e => { STATE.title = e.target.value; scheduleSave(); };
  document.getElementById("back").onclick = () => leaveEdit(flush, drop, () => nav({page: "home"}));
  document.getElementById("done").onclick = () => leaveEdit(flush, drop, () => goGuide(GID, "view"));
  document.getElementById("exp").onclick = async e => {
    e.stopPropagation();
    const b = e.currentTarget;
    if (await flush()) exportMenu(b, GID);
    else toastErr("ยังบันทึกการแก้ไขไม่ได้ จึงยังส่งออกไม่ได้ ลองใหม่อีกครั้ง");
  };
  document.querySelector('.tb[data-act="addpage"]').onclick = e => {
    e.stopPropagation(); addToPageMenu(e.currentTarget, GID);
  };
  document.querySelectorAll(".tb[data-pop]").forEach(b => b.onclick = e => {
    e.stopPropagation(); closePopMenu(); toggleToolPop(b.dataset.pop, b);
  });
  document.addEventListener("click", e => {
    if (!e.target.closest(".etb")) document.getElementById("tbpop").hidden = true;
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") document.getElementById("tbpop").hidden = true;
  });
  // Ctrl+V of an image (not while typing, not inside the image editor) adds an image step
  document.addEventListener("paste", e => {
    if (document.querySelector(".ied")) return;
    const item = [...(e.clipboardData?.items || [])]
      .find(i => i.kind === "file" && i.type.startsWith("image/"));
    if (!item) return;
    // in a text box, text (if any) wins; an image-only clipboard still adds a step
    const typing = e.target instanceof Element && e.target.closest("input, textarea");
    if (typing && e.clipboardData.types.includes("text/plain")) return;
    e.preventDefault();
    addImageStep(item.getAsFile());
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
  (kind === "click" ? renderClickPop : renderDocPop)(pop);
  pop.hidden = false;
}

function renderClickPop(pop) {
  const cur = clickStyle();
  pop.innerHTML = `<div class="pop-h">จุดคลิก</div>
    <div class="muted small">สี</div>
    <div class="sw">${SWATCHES.map(c =>
      `<button type="button" class="swatch${c === cur.color ? " on" : ""}" data-c="${c}" style="background:${c}" title="${c}"></button>`).join("")}</div>
    <div class="custom"><input type="color" id="cc" value="${cur.color.toLowerCase()}" title="เลือกสีเอง">
      <input type="text" id="hex" class="dlg-in" value="${cur.color}" maxlength="7" spellcheck="false"></div>
    <div class="muted small">รูปทรง</div>
    <div class="seg wide"><button type="button" data-shape="circle" class="${cur.shape === "circle" ? "on" : ""}">วงกลม</button>
      <button type="button" data-shape="rect" class="${cur.shape === "rect" ? "on" : ""}">สี่เหลี่ยม</button></div>
    <div class="muted small" style="margin-top:10px">ขนาด <b id="szl">${cur.size}</b></div>
    <input type="range" id="csz" min="24" max="96" value="${cur.size}" class="full">
    <div class="muted small">เปลี่ยนทุกวงในคู่มือนี้ และวงที่เพิ่มใหม่</div>`;
  pop.querySelectorAll(".swatch").forEach(b => b.onclick = () => setClickStyle({color: b.dataset.c}));
  pop.querySelector("#cc").onchange = e => setClickStyle({color: e.target.value});
  pop.querySelector("#hex").oninput = e => {
    if (/^#[0-9a-f]{6}$/i.test(e.target.value)) setClickStyle({color: e.target.value});
  };
  pop.querySelectorAll("[data-shape]").forEach(b => b.onclick = () => setClickStyle({shape: b.dataset.shape}));
  const sz = pop.querySelector("#csz");
  sz.oninput = () => { pop.querySelector("#szl").textContent = sz.value; };
  sz.onchange = () => setClickStyle({size: +sz.value});
}

// The guide-wide click style: writes only the given keys, onto every marker of
// every step; arrows, boxes and text keep their own colours.
function setClickStyle(patch) {
  const S = STATE.settings, p = {};
  if (patch.color) p.color = S.click_color = patch.color.toUpperCase();
  if (patch.shape) p.shape = S.click_shape = patch.shape;
  if (patch.size) p.size = S.click_size = +patch.size;
  for (const s of STATE.steps) for (const m of s.markers || []) Object.assign(m, p);
  renderSteps(); scheduleSave();
  const pop = document.getElementById("tbpop");
  if (pop.hidden || pop.dataset.kind !== "click") return;
  if (document.activeElement?.id === "hex") {  // keep the caret while typing a code
    pop.querySelectorAll(".swatch").forEach(b => b.classList.toggle("on", b.dataset.c === S.click_color));
  } else {
    renderClickPop(pop);
  }
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

// ---- images: upload, add as a step, download one step's picture
async function uploadImage(blob) {
  toast("กำลังเพิ่มภาพ…", 1500);
  try {
    const r = await api("/api/guide/" + encodeURIComponent(GID) + "/image", {method: "POST", body: blob});
    if (r.ok) return (await r.json()).image;
  } catch { /* too large: the server closes the connection */ }
  toastErr(UPLOAD_FAILED);
  return null;
}

// Asks the server for blur rects on the step's image and adds them; force
// runs even with the setting off. before() runs only when something will be
// added (the editor's undo point). Returns how many were added, or null after
// saying why the image could not be checked.
async function autoRedact(step, force, before) {
  const image = step.image;
  let res;
  try {
    const r = await post("/api/guide/" + encodeURIComponent(GID) + "/redact",
      {image, existing: step.redactions || [], force: !!force});
    res = r.ok ? await r.json() : {error: "ตรวจภาพไม่สำเร็จ"};
  } catch { res = {error: "ตรวจภาพไม่สำเร็จ"}; }
  if (res.error) { toastErr("ซ่อนข้อมูลอัตโนมัติไม่ได้: " + res.error); return null; }
  if (step.image !== image) return 0;  // replaced meanwhile; those rects were for the old one
  if (res.rects.length) {
    before?.();
    step.redactions = (step.redactions || []).concat(res.rects);
    scheduleSave();
  }
  return res.rects.length;
}

async function addImageStep(blob) {
  const image = await uploadImage(blob);
  if (!image) return;
  const step = {id: newStepId(), kind: "image", text: "", image,
    crop: null, markers: [], annotations: [], redactions: []};
  STATE.steps.push(step);
  renderSteps(); scheduleSave();
  const input = document.querySelector("#edit-" + step.id + " .stext");
  if (input) { input.scrollIntoView({block: "center"}); input.focus(); }
  if (await autoRedact(step, false)) renderSteps();
}

async function downloadStepImage(step) {
  let n = 0;
  for (const s of STATE.steps) { if (s.kind !== "note") n++; if (s === step) break; }
  let body;
  try {
    body = isGif(step)
      ? await (await api("/img/" + encodeURIComponent(GID) + "/" + encodeURIComponent(step.image))).blob()
      : await renderStepPng(step, GID);
  } catch {
    return toastErr("เปิดภาพนี้ไม่ได้");
  }
  let r;
  try {
    r = await (await api("/api/guide/" + encodeURIComponent(GID) + "/download?n=" + n,
      {method: "POST", body})).json();
  } catch { r = {error: "ดาวน์โหลดไม่สำเร็จ"}; }
  if (r.error) toastErr("บันทึกภาพไม่สำเร็จ: " + r.error);
  else if (r.saved) toast("บันทึกภาพแล้ว");
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
  const bar = document.createElement("div");
  bar.className = "addbar";
  bar.innerHTML = `<button type="button" class="btn addnote">+ เพิ่มหมายเหตุ</button>
    <button type="button" class="btn addimg">+ เพิ่มภาพ</button>
    <input type="file" accept="image/png,image/jpeg,image/gif" hidden>`;
  bar.querySelector(".addnote").onclick = () => {
    const note = {id: newStepId(), kind: "note", text: "", image: null, crop: null,
      markers: [], annotations: [], redactions: []};
    STATE.steps.push(note);
    renderSteps(); scheduleSave();
    const input = document.querySelector("#edit-" + note.id + " .stext");
    if (input) { input.scrollIntoView({block: "center"}); input.focus(); }
  };
  const file = bar.querySelector("input[type=file]");
  bar.querySelector(".addimg").onclick = () => file.click();
  file.onchange = () => { if (file.files[0]) addImageStep(file.files[0]); };
  host.appendChild(bar);
}

function dropTarget(el, i) {
  el.addEventListener("dragover", e => e.preventDefault());
  el.addEventListener("drop", e => {
    e.preventDefault();
    const raw = e.dataTransfer.getData("text/plain");
    if (!/^\d+$/.test(raw)) return;  // only our own step drags carry an index
    const from = +raw;
    if (from === i || from >= STATE.steps.length) return;
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
  const last = STATE.steps.length - 1;
  const ib = (act, label, icon, on = true) => `<button type="button" class="icon-btn" data-act="${act}"
    title="${label}" aria-label="${label}" ${on ? "" : "disabled"}>${icon}</button>`;
  el.innerHTML = `<div class="row1">${stepBadge(num)}
      <div class="txt">${num ? `<div class="kindtag">${esc(KIND_TH[step.kind] || step.kind)}</div>` : ""}
        <input type="text" class="stext" value="${esc(step.text)}" aria-label="${num ? "ข้อความขั้นที่ " + num : "หมายเหตุ"}"
          placeholder="${step.kind === "image" ? "คำอธิบายภาพ" : step.kind === "note" ? "พิมพ์หมายเหตุ" : ""}"></div>
      <div class="sbtns">${ib("up", "เลื่อนขึ้น", ICON.up, i > 0)}${ib("down", "เลื่อนลง", ICON.down, i < last)}
        ${ib("del", "ลบขั้นตอนนี้", ICON.trash)}</div></div>`;
  el.querySelector(".stext").oninput = e => { step.text = e.target.value; scheduleSave(); };
  el.querySelector('[data-act="del"]').onclick = async () => {
    if (!await uiConfirm("ลบขั้นตอนนี้?", "ลบ")) return;
    STATE.steps.splice(STATE.steps.indexOf(step), 1);
    renderSteps(); scheduleSave();
  };
  // the keyboard way to reorder; focus follows the moved step
  const move = (d, act) => {
    const at = STATE.steps.indexOf(step);
    STATE.steps.splice(at, 1);
    STATE.steps.splice(at + d, 0, step);
    renderSteps(); scheduleSave();
    const b = document.querySelector(`#edit-${step.id} [data-act="${act}"]`);
    (b && !b.disabled ? b : document.querySelector(`#edit-${step.id} .stext`))?.focus();
  };
  el.querySelector('[data-act="up"]').onclick = () => move(-1, "up");
  el.querySelector('[data-act="down"]').onclick = () => move(1, "down");
  // drag only from the badge, so text selection stays free
  const handle = el.querySelector(".drag");
  handle.onpointerdown = () => { el.draggable = true; };
  el.addEventListener("dragend", () => { el.draggable = false; });
  dragSource(el, i); dropTarget(el, i);
  if (step.image) el.appendChild(stepPreview(step));
  return el;
}

// The step's finished picture plus its image buttons; a picture that cannot be
// read shows a notice instead, and the step stays editable and deletable.
function stepPreview(step) {
  const box = document.createElement("div");
  box.innerHTML = `<div class="etools">
      <button type="button" class="btn ed">${ICON.edit} แก้ไขภาพ</button>
      <button type="button" class="btn dl">${ICON.export} ดาวน์โหลดภาพ</button></div>
    <div class="eprev"></div>`;
  const tools = box.querySelector(".etools"), prev = box.querySelector(".eprev");
  const fail = () => { tools.hidden = true; prev.innerHTML = '<div class="imgfail">เปิดภาพนี้ไม่ได้</div>'; };
  if (isGif(step)) {
    const im = document.createElement("img");
    im.alt = ""; im.onerror = fail; im.src = imgUrl(GID, step.image);
    prev.appendChild(im);
  } else {
    const cv = document.createElement("canvas");
    prev.appendChild(cv);
    const img = new Image();
    img.onload = () => drawStepCanvas(cv, img, step, 860);
    img.onerror = fail;
    img.src = imgUrl(GID, step.image);
  }
  tools.querySelector(".ed").onclick = () => openImageEditor(step.id);
  tools.querySelector(".dl").onclick = () => downloadStepImage(step);
  return box;
}

function gridCard(step, i, num) {
  const el = document.createElement("div");
  el.className = "gcard";
  el.draggable = true;
  el.title = "คลิกเพื่อแก้ไขขั้นตอนนี้";
  el.innerHTML = `<div class="gthumb"></div>
    <div class="gcap">${num ? `<span class="num">${num}</span>` : `<span class="notetag">หมายเหตุ</span>`}
      <span class="gt">${esc(step.text)}</span></div>`;
  const thumb = el.querySelector(".gthumb");
  const text = t => { thumb.innerHTML = `<div class="gtext">${esc(t)}</div>`; };
  if (!step.image) {
    text(step.text);
  } else if (isGif(step)) {
    const im = document.createElement("img");
    im.alt = ""; im.onerror = () => text("เปิดภาพนี้ไม่ได้"); im.src = imgUrl(GID, step.image);
    thumb.appendChild(im);
  } else {
    const cv = document.createElement("canvas");
    thumb.appendChild(cv);
    const img = new Image();
    img.onload = () => drawStepCanvas(cv, img, step, 480);
    img.onerror = () => text("เปิดภาพนี้ไม่ได้");
    img.src = imgUrl(GID, step.image);
  }
  dragSource(el, i); dropTarget(el, i);
  activatable(el, () => {
    STATE.settings.layout = "linear";
    scheduleSave(); renderSteps();
    const pop = document.getElementById("tbpop");
    if (!pop.hidden && pop.dataset.kind === "doc") renderDocPop(pop);
    document.getElementById("edit-" + step.id)?.scrollIntoView({block: "start"});
    document.querySelector("#edit-" + step.id + " .stext")?.focus({preventScroll: true});
  }, num ? "แก้ไขขั้นที่ " + num : "แก้ไขหมายเหตุ");
  return el;
}
