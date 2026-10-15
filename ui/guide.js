// Guide page: view mode (full screenshots, TOC/meta switches), edit mode, and
// export. renderGuide + drawStepCanvas are self-contained so the exported file
// runs exactly the same rendering code as view mode.
"use strict";
let GID = null, STATE = null;
const app = document.getElementById("app");

// One step's screenshot: the crop (or the whole image), never zoomed; markers on top.
function drawStepCanvas(canvas, img, step) {
  const W = img.naturalWidth, H = img.naturalHeight;
  const c0 = step.crop || {x: 0, y: 0, w: W, h: H};
  const x = Math.min(Math.max(0, c0.x), W - 1), y = Math.min(Math.max(0, c0.y), H - 1);
  const r = {x, y, w: Math.min(c0.w, W - x), h: Math.min(c0.h, H - y)};  // crop kept inside the image
  canvas.width = Math.max(1, Math.round(r.w));
  canvas.height = Math.max(1, Math.round(r.h));
  const c = canvas.getContext("2d");
  c.drawImage(img, r.x, r.y, r.w, r.h, 0, 0, canvas.width, canvas.height);
  const k = Math.max(1, canvas.width / 960);  // keep rings visible once scaled down
  for (const m of step.markers || []) {
    const rad = m.size / 2;
    c.beginPath(); c.arc(m.x - r.x, m.y - r.y, rad, 0, 2 * Math.PI);
    c.fillStyle = m.color + "26"; c.fill();
    c.lineWidth = Math.max(3 * k, rad * 0.14); c.strokeStyle = m.color; c.stroke();
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

// ---------------------------------------------------------------- editor
let SAVET=null, lastColor="#fb923c", lastSize=44, sel=null, cropMode=null;

function saveNow(){
  clearTimeout(SAVET); SAVET = null;
  return api("/api/guide/"+encodeURIComponent(GID),
    {method:"POST",headers:{"Content-Type":"application/json"},
     body:JSON.stringify(STATE)});
}
function scheduleSave(){ clearTimeout(SAVET); SAVET = setTimeout(saveNow, 500); }

function editPage(){
  render();
  startStatusPoll(() => {}, 1000, () => SAVET ? saveNow() : null);
}

function render(){
  app.innerHTML = `<header class="gtop">
      <button class="icon-btn" id="back" title="กลับหน้าหลัก">${ICON.back}</button>
      <input id="title" class="gtitle" type="text" value="${esc(STATE.title)}">
      <button class="btn dark" id="done">${ICON.done} เสร็จสิ้น</button>
      <button class="btn" id="exp">${ICON.export} ส่งออก</button>
    </header><div class="gbody"><div class="ewrap"><div id="steps"></div>
      <button class="btn" id="addnote">+ เพิ่มหมายเหตุ</button></div></div>`;
  document.getElementById("title").oninput = e => { STATE.title=e.target.value; scheduleSave(); };
  document.getElementById("back").onclick = async () => { if(SAVET) await saveNow(); nav({page:"home"}); };
  document.getElementById("done").onclick = async () => { if(SAVET) await saveNow(); goGuide(GID, "view"); };
  document.getElementById("exp").onclick = async () => { if(SAVET) await saveNow(); exportGuide(GID); };
  document.getElementById("addnote").onclick = () => {
    STATE.steps.push({id:"s"+Math.random().toString(16).slice(2,10),kind:"note",text:"หมายเหตุ..."});
    render(); scheduleSave();
  };
  const host = document.getElementById("steps");
  STATE.steps.forEach((step,i)=>host.appendChild(stepCard(step,i)));
}

function stepCard(step,i){
  const el = document.createElement("div"); el.className="step"; el.draggable=true;
  el.dataset.i = i;
  el.innerHTML = `<div class="row">
      <div class="num" title="ลากเพื่อสลับลำดับ">${i+1}</div>
      <div class="txt"><div class="kindtag">${step.kind}</div>
        <input type="text" class="stext" value="${esc(step.text)}"></div>
      <button class="danger del">ลบ</button></div>`;
  el.querySelector(".stext").oninput = e => { step.text=e.target.value; scheduleSave(); };
  el.querySelector(".del").onclick = () => {
    if(!confirm("ลบขั้นตอนนี้?")) return;
    STATE.steps.splice(i,1); render(); scheduleSave();
  };
  // drag reorder
  el.addEventListener("dragstart", e => { e.dataTransfer.setData("i",i); el.classList.add("dragging"); });
  el.addEventListener("dragend", () => el.classList.remove("dragging"));
  el.addEventListener("dragover", e => e.preventDefault());
  el.addEventListener("drop", e => {
    e.preventDefault();
    const from = +e.dataTransfer.getData("i");
    if(from===i) return;
    const [m] = STATE.steps.splice(from,1); STATE.steps.splice(i,0,m);
    render(); scheduleSave();
  });
  if(step.image) el.appendChild(imageEditor(step));
  return el;
}

function imageEditor(step){
  const box = document.createElement("div");
  const tools = document.createElement("div"); tools.className="tools";
  tools.innerHTML = `<button class="addmk">+ เพิ่มวง</button>
    <button class="crop">ครอปภาพ</button>
    ${step.crop?'<button class="uncrop">ล้างครอป</button>':''}`;
  box.appendChild(tools);
  const stage = document.createElement("div"); stage.className="stage";
  const img = document.createElement("img");
  img.src = "/img/"+encodeURIComponent(GID)+"/"+encodeURIComponent(step.image)+"?t="+encodeURIComponent(T);
  stage.appendChild(img);
  box.appendChild(stage);
  const ctrl = document.createElement("div"); ctrl.className="mk-ctrl";
  box.appendChild(ctrl);

  img.onload = () => {
    const natW=img.naturalWidth, natH=img.naturalHeight;
    const scale = () => stage.clientWidth / natW;
    step.markers = step.markers || [];

    function drawMarkers(){
      stage.querySelectorAll(".marker,.croprect").forEach(n=>n.remove());
      const sc = scale();
      if(step.crop){
        const cr=document.createElement("div"); cr.className="croprect";
        cr.style.left=step.crop.x*sc+"px"; cr.style.top=step.crop.y*sc+"px";
        cr.style.width=step.crop.w*sc+"px"; cr.style.height=step.crop.h*sc+"px";
        stage.appendChild(cr);
      }
      step.markers.forEach((m,mi)=>{
        const d=document.createElement("div"); d.className="marker"+(sel===m?" sel":"");
        d.style.left=m.x*sc+"px"; d.style.top=m.y*sc+"px";
        d.style.width=m.size*sc+"px"; d.style.height=m.size*sc+"px";
        d.style.borderColor=m.color; d.style.background=m.color+"26";
        d.onpointerdown = ev => startDrag(ev,m,sc);
        stage.appendChild(d);
      });
      renderCtrl();
    }
    function renderCtrl(){
      if(!sel){ ctrl.innerHTML=""; return; }
      ctrl.innerHTML = `สีวง <input type="color" class="mcol" value="${sel.color}">
        ขนาด <input type="range" class="msize" min="24" max="96" value="${sel.size}">
        <button class="danger mdel">ลบวง</button>`;
      ctrl.querySelector(".mcol").oninput = e => { sel.color=lastColor=e.target.value; drawMarkers(); scheduleSave(); };
      ctrl.querySelector(".msize").oninput = e => { sel.size=lastSize=+e.target.value; drawMarkers(); scheduleSave(); };
      ctrl.querySelector(".mdel").onclick = () => {
        step.markers.splice(step.markers.indexOf(sel),1); sel=null; drawMarkers(); scheduleSave();
      };
    }
    function startDrag(ev,m,sc){
      ev.preventDefault(); sel=m; drawMarkers();
      const move = e => {
        const rect=stage.getBoundingClientRect();
        m.x=Math.max(0,Math.min(natW,(e.clientX-rect.left)/sc));
        m.y=Math.max(0,Math.min(natH,(e.clientY-rect.top)/sc));
        drawMarkers();
      };
      const up = () => { document.removeEventListener("pointermove",move);
        document.removeEventListener("pointerup",up); scheduleSave(); };
      document.addEventListener("pointermove",move);
      document.addEventListener("pointerup",up);
    }

    tools.querySelector(".addmk").onclick = () => {
      stage.style.cursor="crosshair";
      stage.onpointerdown = ev => {
        const rect=stage.getBoundingClientRect(), sc=scale();
        const m={x:(ev.clientX-rect.left)/sc, y:(ev.clientY-rect.top)/sc, color:lastColor, size:lastSize};
        step.markers.push(m); sel=m; stage.style.cursor=""; stage.onpointerdown=null;
        drawMarkers(); scheduleSave();
      };
    };
    tools.querySelector(".crop").onclick = () => {
      stage.style.cursor="crosshair";
      let start=null, rectEl=null;
      stage.onpointerdown = ev => {
        const r=stage.getBoundingClientRect(); start={x:ev.clientX-r.left,y:ev.clientY-r.top};
        rectEl=document.createElement("div"); rectEl.className="croprect"; stage.appendChild(rectEl);
        const move = e => { const cx=e.clientX-r.left, cy=e.clientY-r.top;
          const x=Math.min(start.x,cx),y=Math.min(start.y,cy),w=Math.abs(cx-start.x),h=Math.abs(cy-start.y);
          rectEl.style.left=x+"px";rectEl.style.top=y+"px";rectEl.style.width=w+"px";rectEl.style.height=h+"px"; };
        const up = e => { document.removeEventListener("pointermove",move); document.removeEventListener("pointerup",up);
          const sc=scale(), cx=e.clientX-r.left, cy=e.clientY-r.top;
          const x=Math.min(start.x,cx)/sc,y=Math.min(start.y,cy)/sc,w=Math.abs(cx-start.x)/sc,h=Math.abs(cy-start.y)/sc;
          stage.style.cursor=""; stage.onpointerdown=null;
          if(w>10&&h>10){ step.crop={x,y,w,h}; scheduleSave(); render(); }
          else drawMarkers();
        };
        document.addEventListener("pointermove",move); document.addEventListener("pointerup",up);
      };
    };
    const un = tools.querySelector(".uncrop");
    if(un) un.onclick = () => { step.crop=null; scheduleSave(); render(); };

    stage.onclick = e => { if(e.target===img){ sel=null; drawMarkers(); } };
    drawMarkers();
    window.addEventListener("resize", drawMarkers);
  };
  return box;
}

