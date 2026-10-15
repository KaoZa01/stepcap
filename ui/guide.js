// Guide page (temporary: the old editor moved as-is; view/edit mode replace it).
"use strict";
let GID = null;
const DISPLAY_W = 680;
const app = document.getElementById("app");

async function guidePage(id, mode) { GID = id; document.body.classList.add("gp"); editor(); }
async function exportGuide(gid) { toast("เร็วๆ นี้"); }

// region of the image to show: explicit crop, else bbox around markers, else full
function regionFor(step, w, h){
  if(step.crop) return step.crop;
  const ms = step.markers || [];
  if(!ms.length) return {x:0,y:0,w,h};
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
  for(const m of ms){ x0=Math.min(x0,m.x-m.size); y0=Math.min(y0,m.y-m.size);
    x1=Math.max(x1,m.x+m.size); y1=Math.max(y1,m.y+m.size); }
  const pad=50; x0-=pad;y0-=pad;x1+=pad;y1+=pad;
  x0=Math.max(0,x0);y0=Math.max(0,y0);x1=Math.min(w,x1);y1=Math.min(h,y1);
  return {x:x0,y:y0,w:Math.max(1,x1-x0),h:Math.max(1,y1-y0)};
}

// draw one click step onto a canvas (used by preview + export; self-contained)
function drawStep(canvas, img, step){
  const w=img.naturalWidth, h=img.naturalHeight;
  const r = regionFor(step, w, h);
  const scale = DISPLAY_W / r.w;
  canvas.width = DISPLAY_W;
  canvas.height = Math.round(r.h*scale);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(img, r.x, r.y, r.w, r.h, 0, 0, canvas.width, canvas.height);
  for(const m of (step.markers||[])){
    const cx=(m.x-r.x)*scale, cy=(m.y-r.y)*scale, rad=(m.size/2)*scale;
    ctx.beginPath(); ctx.arc(cx,cy,rad,0,7);
    ctx.fillStyle = m.color+"26"; ctx.fill();
    ctx.lineWidth = Math.max(3, rad*0.14); ctx.strokeStyle = m.color; ctx.stroke();
  }
}

// read-only render of a whole guide into root (async: loads images). Self-contained
// so it can be stringified into the exported file. Each step uses step._src for image.
async function renderGuide(guide, root){
  function regionFor(step, w, h){
    if(step.crop) return step.crop;
    const ms = step.markers || []; if(!ms.length) return {x:0,y:0,w,h};
    let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
    for(const m of ms){ x0=Math.min(x0,m.x-m.size); y0=Math.min(y0,m.y-m.size);
      x1=Math.max(x1,m.x+m.size); y1=Math.max(y1,m.y+m.size); }
    const pad=50; x0=Math.max(0,x0-pad);y0=Math.max(0,y0-pad);
    x1=Math.min(w,x1+pad);y1=Math.min(h,y1+pad);
    return {x:x0,y:y0,w:Math.max(1,x1-x0),h:Math.max(1,y1-y0)};
  }
  const E = s => (s==null?"":String(s)).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const DW = 680;
  root.innerHTML = '<div class="rg-wrap"><h1>'+E(guide.title)+'</h1></div>';
  const wrap = root.querySelector(".rg-wrap");
  let n=0;
  for(const step of guide.steps){
    n++;
    const div = document.createElement("div"); div.className="rg-step";
    if(step.kind==="note"){
      div.innerHTML = '<div class="rg-note">'+E(step.text)+'</div>';
      wrap.appendChild(div); continue;
    }
    div.innerHTML = '<div class="rg-head"><div class="rg-num">'+n+'</div><div>'+E(step.text)+'</div></div>';
    if(step._src){
      const cv=document.createElement("canvas"); div.appendChild(cv);
      await new Promise(res=>{ const im=new Image();
        im.onload=()=>{ const r=regionFor(step,im.naturalWidth,im.naturalHeight);
          const sc=DW/r.w; cv.width=DW; cv.height=Math.round(r.h*sc);
          const c=cv.getContext("2d");
          c.drawImage(im,r.x,r.y,r.w,r.h,0,0,cv.width,cv.height);
          for(const m of (step.markers||[])){ const cx=(m.x-r.x)*sc,cy=(m.y-r.y)*sc,rr=(m.size/2)*sc;
            c.beginPath();c.arc(cx,cy,rr,0,7);c.fillStyle=m.color+"26";c.fill();
            c.lineWidth=Math.max(3,rr*0.14);c.strokeStyle=m.color;c.stroke(); }
          res(); };
        im.onerror=res; im.src=step._src; });
    }
    wrap.appendChild(div);
  }
}

// ---------------------------------------------------------------- editor
let STATE=null, SAVET=null, lastColor="#fb923c", lastSize=44, sel=null, cropMode=null;

function saveNow(){
  clearTimeout(SAVET); SAVET = null;
  return api("/api/guide/"+encodeURIComponent(GID),
    {method:"POST",headers:{"Content-Type":"application/json"},
     body:JSON.stringify(STATE)});
}
function scheduleSave(){ clearTimeout(SAVET); SAVET = setTimeout(saveNow, 500); }

async function editor(){
  STATE = await (await api("/api/guide/"+encodeURIComponent(GID))).json();
  document.title = "StepCap - " + STATE.title;
  render();
  startStatusPoll(() => {}, 1000, () => SAVET ? saveNow() : null);
}

function render(){
  app.innerHTML = `<header>
      <input id="title" type="text" value="${esc(STATE.title)}" style="flex:1;font-weight:600">
      <button id="prev">ดูตัวอย่าง</button>
      <button id="exp" class="primary">Export HTML</button>
      <button onclick="nav({page:'home'})">คู่มือทั้งหมด</button>
    </header><div class="wrap"><div id="steps"></div>
      <button id="addnote" style="margin-top:4px">+ เพิ่มหมายเหตุ</button></div>`;
  document.getElementById("title").oninput = e => { STATE.title=e.target.value; scheduleSave(); };
  document.getElementById("prev").onclick = preview;
  document.getElementById("exp").onclick = doExport;
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

// ---------------------------------------------------------------- preview
async function preview(){
  const dlg = document.createElement("dialog");
  dlg.innerHTML = `<div style="padding:16px;max-width:760px"><div style="text-align:right">
    <button onclick="this.closest('dialog').close()">ปิด</button></div><div id="pv"></div></div>`;
  document.body.appendChild(dlg); dlg.showModal();
  const g = JSON.parse(JSON.stringify(STATE));
  g.steps.forEach(s => { if(s.image) s._src = "/img/"+encodeURIComponent(GID)+"/"+encodeURIComponent(s.image)+"?t="+encodeURIComponent(T); });
  await renderGuide(g, dlg.querySelector("#pv"));
  dlg.addEventListener("close", ()=>dlg.remove());
}

// ---------------------------------------------------------------- export
async function doExport(){
  const g = JSON.parse(JSON.stringify(STATE));
  for(const s of g.steps){
    if(s.image){
      const blob = await (await api("/img/"+encodeURIComponent(GID)+"/"+encodeURIComponent(s.image))).blob();
      s._src = await new Promise(r=>{ const fr=new FileReader(); fr.onload=()=>r(fr.result); fr.readAsDataURL(blob); });
    }
    delete s.image;
  }
  const css = document.querySelector("style").textContent;
  const html = `<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(g.title)}</title>
<style>${css}</style></head><body><div class="wrap"><div id="root"></div></div>
<script>const guide=${JSON.stringify(g)};
(${renderGuide.toString()})(guide,document.getElementById("root"));<\/script></body></html>`;
  const blob = new Blob([html], {type:"text/html"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (g.title || "guide").replace(/[\\/:*?"<>|]/g,"_") + ".html";
  a.click();
  URL.revokeObjectURL(a.href);
}

