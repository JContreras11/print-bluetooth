/* Y50 diseñador de etiquetas — cliente
   1 px en el lienzo = 1 punto térmico (8 dots/mm = 203 dpi) */
"use strict";

const DPM = 8;                 // dots per mm
const SNAP = DPM / 4;          // quarter mm
const LS_KEY = "y50.design";

const canvas = document.getElementById("paper");
const ctx = canvas.getContext("2d", { willReadFrequently: true });
const wrap = document.getElementById("canvasWrap");
const handles = document.getElementById("handles");
const logEl = document.getElementById("log");
const propsPanel = document.getElementById("props");
const propFields = document.getElementById("propFields");
const fileImg = document.getElementById("fileImg");

let doc = { widthMm: 50, heightMm: 30, els: [] };
let sel = null;          // elemento seleccionado (referencia)
let drag = null;
let imgCache = {};       // dataURL -> HTMLImageElement

/* ---------- persistencia ---------- */

function saveDoc() {
  const clone = JSON.parse(JSON.stringify(doc));
  clone.els = clone.els.filter(e => e.type !== "img" || e.src);
  localStorage.setItem(LS_KEY, JSON.stringify({
    widthMm: doc.widthMm, heightMm: doc.heightMm, els: clone.els
  }));
}

function loadDoc() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      doc.widthMm = saved.widthMm || 50;
      doc.heightMm = saved.heightMm || 30;
      doc.els = saved.els || [];
    }
  } catch (e) { /* documento por defecto */ }
}

/* ---------- utilidades de documento ---------- */

function mm2dots(mm) { return Math.round(mm * DPM); }
function dots2mm(d) { return d / DPM; }

function newId() { return Math.random().toString(36).slice(2, 9); }

let lastType = "";

function addEl(type, x_mm, y_mm, extra) {
  const el = Object.assign({ id: newId(), type, x: mm2dots(x_mm), y: mm2dots(y_mm) }, extra);
  doc.els.push(el);
  sel = el;
  lastType = type;
  render(); syncProps(); saveDoc();
  return el;
}

function addText() { addEl("text", 4, 3, { text: "Escribe aquí", size: 48, bold: true, font: "sans", align: "left" }); }
function addQR() {
  const t = prompt("Contenido del QR:", "https://");
  if (t == null || t === "") return;
  const side = mm2dots(15);
  addEl("qr", 6, 4, { text: t, w: side, h: side });
}
function addBarcode() {
  const t = prompt("Contenido del Código 128:", "123456");
  if (t == null || t === "") return;
  addEl("barcode", 4, 15, { text: t, h: 72, showText: true });
}
function addRect() { addEl("rect", 2, 2, { w: mm2dots(30), h: mm2dots(12), lw: 4, fill: false }); }
function addImage() { fileImg.click(); }
fileImg.onchange = () => {
  if (!fileImg.files.length) return;
  const fr = new FileReader();
  fr.onload = () => {
    const el = addEl("img", 4, 4, { src: fr.result, w: 0, h: 0 });
    const im = loadImage(fr.result, () => {
      // tamaño inicial: caber en 25 mm de ancho
      const scale = mm2dots(25) / im.naturalWidth;
      el.w = Math.max(1, Math.round(im.naturalWidth * scale));
      el.h = Math.max(1, Math.round(im.naturalHeight * scale));
      render(); syncProps(); saveDoc();
    });
  };
  fr.readAsDataURL(fileImg.files[0]);
};

function removeSel() {
  doc.els = doc.els.filter(e => e !== sel);
  sel = null;
  render(); syncProps(); saveDoc();
}

function duplicate() {
  if (!sel) return;
  const c = JSON.parse(JSON.stringify({ ...sel, _box: undefined, _qr: undefined, _bar: undefined }));
  c.id = newId();
  c.x += 16; c.y += 16;
  doc.els.push(c);
  sel = c;
  render(); syncProps(); saveDoc();
}

function loadPreset(name) {
  if (name === "vacío") { doc.els = []; sel = null; render(); syncProps(); saveDoc(); return; }
  const base = () => { doc.els = []; sel = null; };
  if (name === "pequeño") {
    base();
    addEl("text", 3, 2, { text: "ARTÍCULO", size: 56, bold: true, font: "sans" });
    addEl("text", 3, 11, { text: "0,00 €", size: 40, bold: false, font: "sans" });
    addEl("barcode", 2, 19, { text: "0000000", h: 56, showText: false });
  } else if (name === "precio") {
    base();
    addEl("text", 8, 3, { text: "4,50 €", size: 64, bold: true });
    addEl("text", 2, 12, { text: "Precio especial", size: 26, font: "serif" });
    addEl("rect", 1, 1, { w: mm2dots(40), h: mm2dots(19), lw: 2 });
  } else {
    base();
    addEl("date", 3, 2, { text: "{D}/{M}/{Y}", size: 40, bold: true, align: "left" });
    addEl("date", 3, 11, { text: "{h}:{min}", size: 32, bold: false, align: "left" });
  }
  saveDoc();
}

function resizePaper() {
  doc.widthMm = clamp(parseInt(document.getElementById("inW").value || 50), 20, 50);
  doc.heightMm = clamp(parseInt(document.getElementById("inH").value || 30), 15, 200);
  document.getElementById("inW").value = doc.widthMm;
  document.getElementById("inH").value = doc.heightMm;
  if (sel) { clampEl(sel); }
  render(); saveDoc();
}
function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }

/* ---------- cachés de recursos ---------- */

function loadImage(src, cb) {
  if (imgCache[src]) return imgCache[src];
  const im = new Image();
  im.onload = () => cb && cb(im);
  im.src = src;
  imgCache[src] = im;
  return im;
}

function qrCanvas(text) {
  const type = 0; // auto
  const qr = window.qrcode(type, "M");
  qr.addData(text, "Byte");
  qr.make();
  const n = qr.getModuleCount();
  const c = document.createElement("canvas");
  c.width = n; c.height = n;
  const c2 = c.getContext("2d");
  c2.fillStyle = "#fff"; c2.fillRect(0, 0, n, n);
  c2.fillStyle = "#000";
  for (let y = 0; y < n; y++)
    for (let x = 0; x < n; x++)
      if (qr.isDark(y, x)) c2.fillRect(x, y, 1, 1);
  return c;
}

function qrCanvasCached(el) {
  const key = el.text;
  if (!el._qr || el._qrKey !== key) {
    el._qr = qrCanvas(key);
    el._qrKey = key;
  }
  return el._qr;
}

function barcodeCanvas(el) {
  const c = document.createElement("canvas");
  try {
    JsBarcode(c, el.text, {
      format: "CODE128", width: 2, height: Math.max(10, el.h),
      margin: 0, displayValue: !!el.showText, font: "system-ui", fontSize: 14,
      lineColor: "#000", background: "transparent",
    });
  } catch (e) {
    c.width = 1; c.height = 1;
  }
  return c;
}

function barcodeCanvasCached(el) {
  const key = el.text + "|" + el.h + "|" + el.showText;
  if (!el._bar || el._barKey !== key) {
    el._bar = barcodeCanvas(el);
    el._barKey = key;
  }
  return el._bar;
}

/* ---------- dibujo ---------- */

function drawEl(c, el) {
  c.save();
  c.translate(el.x, el.y);
  switch (el.type) {
    case "text": {
      const fam = { sans: "sans-serif", serif: "serif", mono: "monospace" }[el.font] || "sans-serif";
      c.font = `${el.bold ? "700" : "400"} ${el.size}px ${fam}`;
      c.textBaseline = "top";
      c.fillStyle = "#000";
      const lines = el.text.split("\n");
      const box = measureEl(el);
      lines.forEach((ln, i) => {
        let lx = 0;
        if (el.align === "center") { c.textAlign = "center"; lx = box.w / 2; }
        else if (el.align === "right") { c.textAlign = "right"; lx = box.w; }
        else c.textAlign = "left";
        c.fillText(ln, lx, i * el.size * 1.15);
      });
      break;
    }
    case "qr": {
      const q = qrCanvasCached(el);
      const n = q.width;
      const cw = el.w / n, ch = el.h / n;
      const px = q.getContext("2d").getImageData(0, 0, n, n).data;
      c.fillStyle = "#fff";
      c.fillRect(0, 0, el.w, el.h);
      c.fillStyle = "#000";
      for (let y = 0; y < n; y++)
        for (let x = 0; x < n; x++) {
          if (px[(y * n + x) * 4] < 128)
            c.fillRect(Math.floor(x * cw), Math.floor(y * ch), Math.ceil(cw), Math.ceil(ch));
        }
      break;
    }
    case "barcode": {
      const b = barcodeCanvasCached(el);
      c.drawImage(b, 0, 0);
      break;
    }
    case "img": {
      const im = loadImage(el.src);
      if (im.complete && im.naturalWidth) c.drawImage(im, 0, 0, el.w, el.h);
      break;
    }
    case "rect": {
      c.strokeStyle = "#000";
      c.lineWidth = el.lw || 2;
      if (el.fill) { c.fillStyle = "#000"; c.fillRect(0, 0, el.w, el.h); }
      if (el.lw > 0) c.strokeRect(el.lw / 2, el.lw / 2, el.w - el.lw, el.h - el.lw);
      break;
    }
    case "date": {
      const fam = { sans: "sans-serif", serif: "serif", mono: "monospace" }[el.font] || "sans-serif";
      c.font = `${el.bold ? "700" : "400"} ${el.size}px ${fam}`;
      c.textBaseline = "top"; c.textAlign = "left"; c.fillStyle = "#000";
      const d = new Date();
      const txt = el.text
        .replace(/\{Y\}/g, d.getFullYear())
        .replace(/\{M\}/g, String(d.getMonth() + 1).padStart(2, "0"))
        .replace(/\{D\}/g, String(d.getDate()).padStart(2, "0"))
        .replace(/\{h\}/g, String(d.getHours()))
        .replace(/\{min\}/g, String(d.getMinutes()).padStart(2, "0"))
        .replace(/\{sec\}/g, String(d.getSeconds()).padStart(2, "0"));
      c.fillText(txt, 0, 0);
      break;
    }
  }
  c.restore();
}

function bboxOf(el) {
  if (el.type === "qr" || el.type === "img" || el.type === "rect") return { w: el.w, h: el.h };
  if (el.type === "barcode") {
    const b = barcodeCanvasCached(el);
    return { w: b.width, h: b.height };
  }
  return measureEl(el); // text/date
}

function measureEl(el) {
  const fam = { sans: "sans-serif", serif: "serif", mono: "monospace" }[el.font] || "sans-serif";
  ctx.font = `${el.bold ? "700" : "400"} ${el.size}px ${fam}`;
  const lines = el.text.split("\n");
  let w = 0;
  lines.forEach(ln => { w = Math.max(w, ctx.measureText(ln).width); });
  return { w: Math.ceil(w) + 2, h: Math.ceil(lines.length * el.size * 1.15) };
}

/* ---------- render ---------- */

function render() {
  const w = mm2dots(doc.widthMm), h = mm2dots(doc.heightMm);
  canvas.width = w; canvas.height = h;
  // escala de visualización: caber en la pantalla (hasta 1:1 para planos grandes ya reducidos en zonas horizontales)
  const stage = document.getElementById("stage");
  const maxW = stage.clientWidth - 60, maxH = stage.clientHeight - 80;
  const disp = Math.min(1, maxW / w, maxH / h);
  canvas.style.width = Math.floor(w * disp) + "px";
  canvas.style.height = Math.floor(h * disp) + "px";
  canvas.dispScale = disp;

  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, w, h);
  doc.els.forEach(el => drawEl(ctx, el));

  // rejilla guía (solo visual, se elimina al imprimir)
  ctx.strokeStyle = "rgba(0,110,255,.25)";
  ctx.lineWidth = 1;
  for (let x = 0; x < w; x += DPM * 5) { ctx.beginPath(); ctx.moveTo(x + .5, 0); ctx.lineTo(x + .5, h); ctx.stroke(); }
  for (let y = 0; y < h; y += DPM * 5) { ctx.beginPath(); ctx.moveTo(0, y + .5); ctx.lineTo(w, y + .5); ctx.stroke(); }
  // marco de recorte (no sale en la impresión: se dibuja sobre el pixel offscreen antes del envío)
  ctx.strokeStyle = "rgba(80,150,255,.6)";
  ctx.strokeRect(.5, .5, w - 1, h - 1);

  drawSelection();
}

function drawSelection() {
  handles.innerHTML = "";
  const off = document.getElementById("selBox");
  if (off) off.remove();
  if (!sel) { propsPanel.classList.add("hidden"); return; }
  propsPanel.classList.remove("hidden");
  const el = sel;
  const bb = bboxOf(el);
  const disp = canvas.dispScale || 1;
  const sx = el.x * disp, sy = el.y * disp;
  const sb = document.createElement("div");
  sb.id = "selBox";
  sb.style.left = sx - 1 + "px";
  sb.style.top = sy - 1 + "px";
  sb.style.width = bb.w * disp + 2 + "px";
  sb.style.height = bb.h * disp + 2 + "px";
  wrap.appendChild(sb);
  ["tl", "br"].forEach(corner => {
    const hd = document.createElement("div");
    hd.className = "handle " + corner;
    if (corner === "br") {
      hd.style.left = (bb.w * disp - 6) + "px";
      hd.style.top = (bb.h * disp - 6) + "px";
    }
    hd.onmousedown = ev => startDrag(ev, el, corner === "br" ? "resize" : "resize-tl");
    handles.appendChild(hd);
  });
}

/* ---------- interacción selección/drag ---------- */

function hitTest(px, py) {
  for (let i = doc.els.length - 1; i >= 0; i--) {
    const el = doc.els[i];
    const bb = bboxOf(el);
    if (px >= el.x - 4 && py >= el.y - 4 && px <= el.x + bb.w + 4 && py <= el.y + bb.h + 4)
      return el;
  }
  return null;
}

canvas.onmousedown = ev => {
  const rect = canvas.getBoundingClientRect();
  const px = (ev.clientX - rect.left) / (canvas.dispScale || 1);
  const py = (ev.clientY - rect.top) / (canvas.dispScale || 1);
  const el = hitTest(px, py);
  sel = el;
  render(); syncProps();
  if (el) startDrag(ev, el, "move");
  saveDoc();
};

function startDrag(ev, el, mode) {
  ev.preventDefault(); ev.stopPropagation();
  const evx = ev.clientX, evy = ev.clientY;
  const ox = el.x, oy = el.y, ow = el.w, oh = el.h, os = el.size || 48, obb = bboxOf(el);
  const drag = e2 => {
    const dx = (e2.clientX - evx) / (canvas.dispScale || 1);
    const dy = (e2.clientY - evy) / (canvas.dispScale || 1);
    if (mode === "move") {
      el.x = snap(ox + dx);
      el.y = snap(oy + dy);
    } else if (mode === "resize") {
      if (el.type === "rect" || el.type === "img") {
        el.w = Math.max(8, snapStrict(ow + dx));
        el.h = Math.max(8, snapStrict(oh + dy));
      } else if (el.type === "qr") {
        el.w = el.h = Math.max(32, snapStrict(obb.w + dx));
      } else {
        // texto/fecha: escala por tamaño de letra
        const f = Math.max(.2, (obb.w + dx) / Math.max(1, obb.w));
        el.size = clamp(Math.round(os * f), 10, 300);
      }
    } else if (mode === "resize-tl") {
      if (el.type === "rect" || el.type === "img") {
        const nx = clamp(ox + dx, 0, Math.max(0, mm2dots(doc.widthMm) - ow));
        const ny = clamp(oy + dy, 0, Math.max(0, mm2dots(doc.heightMm) - oh));
        el.w = Math.max(8, ow + (ox - nx));
        el.h = Math.max(8, oh + (oy - ny));
        el.x = nx; el.y = ny;
      } else {
        const f = Math.max(.2, (obb.w - dx) / Math.max(1, obb.w));
        if (el.type === "qr") { el.w = el.h = Math.max(32, snapStrict(obb.w - dx)); }
        else el.size = clamp(Math.round(os * f), 10, 300);
        el.x = snap(ox + dx); el.y = snap(oy + dy);
      }
    }
    clampEl(el);
    render(); syncProps(false);
  };
  const up = () => {
    document.removeEventListener("mousemove", drag);
    document.removeEventListener("mouseup", up);
    saveDoc();
  };
  document.addEventListener("mousemove", drag);
  document.addEventListener("mouseup", up);
}

function snap(v) { return Math.round(v / SNAP) * SNAP; }
function snapStrict(v) { return Math.round(v / DPM) * DPM; }

function clampEl(el) {
  const bb = bboxOf(el);
  el.x = clamp(el.x, 0, Math.max(0, mm2dots(doc.widthMm) - bb.w));
  el.y = clamp(el.y, 0, Math.max(0, mm2dots(doc.heightMm) - bb.h));
}

document.addEventListener("keydown", ev => {
  if (!sel || ev.target.matches("input,textarea,select")) return;
  if (ev.key === "Delete") { removeSel(); return; }
  const step = ev.shiftKey ? DPM : 1;
  const map = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (map[ev.key]) {
    ev.preventDefault();
    sel.x += map[ev.key][0]; sel.y += map[ev.key][1];
    clampEl(sel); render(); syncProps(false); saveDoc();
  }
});

/* ---------- panel de propiedades ---------- */

function descriptors(el) {
  switch (el.type) {
    case "text": case "date": return [
      ["textarea", "Contenido", "text"],
      ["number", "Tamaño px", "size", 10, 300],
      ["check", "Negrita", "bold"],
      ["select", "Fuente", "font", { sans: "Sans", serif: "Serif", mono: "Mono" }],
      ["select", "Alineado", "align", { left: "Izq", center: "Centro", right: "Der" }],
    ];
    case "qr": return [
      ["textarea", "Contenido", "text"],
      ["number", "Lado px", "w", 32, 500],
    ];
    case "barcode": return [
      ["text", "Valor", "text"],
      ["number", "Alto px", "h", 20, 300],
      ["check", "Mostrar texto", "showText"],
    ];
    case "img": return [
      ["number", "Ancho px", "w", 8, 600],
      ["number", "Alto px", "h", 8, 600],
    ];
    case "rect": return [
      ["number", "Ancho px", "w", 2, 600],
      ["number", "Alto px", "h", 2, 600],
      ["number", "Borde px", "lw", 0, 32],
      ["check", "Relleno", "fill"],
    ];
  }
  return [];
}

function syncProps(rebind = true) {
  if (!sel) { propsPanel.classList.add("hidden"); return; }
  propsPanel.classList.remove("hidden");
  if (!rebind && propFields._elId === sel.id) return;
  propFields._elId = sel.id;
  propFields.innerHTML = "";
  descriptors(sel).forEach(d => {
    const [kind, label, key, a, b] = d;
    const row = document.createElement("label");
    const span = document.createElement("span"); span.textContent = label; row.appendChild(span);
    if (kind === "textarea") {
      const ta = document.createElement("textarea");
      ta.value = sel[key] || "";
      ta.oninput = () => { sel[key] = ta.value; render(); drawSelection(); saveDoc(); };
      row.appendChild(ta); row.style.flexDirection = "column"; row.style.alignItems = "stretch";
    } else if (kind === "select") {
      const s = document.createElement("select");
      Object.entries((a)).forEach(([v, t]) => {
        const o = document.createElement("option"); o.value = v; o.textContent = t; s.appendChild(o);
      });
      s.value = sel[key];
      s.onchange = () => { sel[key] = s.value; render(); drawSelection(); saveDoc(); };
      row.appendChild(s);
    } else if (kind === "check") {
      const inp = document.createElement("input");
      inp.type = "checkbox"; inp.checked = !!sel[key];
      inp.onchange = () => { sel[key] = inp.checked; render(); drawSelection(); saveDoc(); };
      inp.style.width = "auto"; row.appendChild(inp);
    } else {
      const inp = document.createElement("input");
      inp.type = "number";
      if (a !== undefined) inp.min = a;
      if (b !== undefined) inp.max = b;
      inp.value = sel[key] || 0;
      inp.oninput = () => {
        const v = parseInt(inp.value || 0);
        sel[key] = v;
        if (sel.type === "qr") sel.h = sel.w; // cuadrado
        clampEl(sel); render(); drawSelection(); saveDoc();
      };
      row.appendChild(inp);
    }
    propFields.appendChild(row);
  });
}

/* ---------- comunicación con la impresora ---------- */

function log(msg) { logEl.textContent = msg; }

async function refreshInfo() {
  const chip = document.getElementById("statusChip");
  chip.className = "chip off"; chip.textContent = "…";
  try {
    const r = await fetch("/api/info");
    const j = await r.json();
    if (j.error) { chip.className = "chip bad"; chip.textContent = "error"; log(j.error); return; }
    const st = j.status || "?";
    chip.className = j.ready ? "chip ok" : "chip bad";
    chip.textContent = `${j.model || "?"} · fw ${j.firmware || "?"} · ${st}`;
    log(`conectada por ${(j.transport || "").toString()}: serie ${j.serial || "?"}, estado ${st}`);
  } catch (e) {
    chip.className = "chip bad"; chip.textContent = "sin conexión";
    log("No puedo alcanzar la impresora: " + e);
  }
}

async function feed() {
  log("alimentando etiqueta…");
  try {
    const r = await fetch("/api/feed", { method: "POST" });
    const j = await r.json();
    log(j.error ? "Error: " + j.error : "etiqueta avanzada");
  } catch (e) { log("Error: " + e); }
}

async function sendRaw() {
  const hex = document.getElementById("rawHex").value.trim().replace(/[^0-9a-fA-F]/g, "");
  if (!hex) return;
  try {
    const r = await fetch("/api/raw", { method: "POST", body: JSON.stringify({ hex }) });
    const j = await r.json();
    log(j.error ? "Error: " + j.error : `enviados ${j.sent} bytes crudos`);
  } catch (e) { log("Error: " + e); }
}

function buildRows() {
  // redibuja a resolución 1:1 sin rejilla/marco
  const w = mm2dots(doc.widthMm), h = mm2dots(doc.heightMm);
  const savedSel = sel;
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, w, h);
  doc.els.forEach(el => drawEl(ctx, el));
  const data = ctx.getImageData(0, 0, w, h).data;
  sel = null;
  const Q = 128; // umbral de negro
  const bits = new Uint8Array(Math.ceil(w / 8) * h);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      const lum = data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
      if (lum < Q) bits[Math.floor(x / 8) + y * Math.ceil(w / 8)] |= 0x80 >> (x % 8);
    }
  let s = "";
  const CH = 0x8000;
  for (let i = 0; i < bits.length; i += 0x8000)
    s += String.fromCharCode.apply(null, bits.subarray(i, i + CH));
  const b64 = btoa(s);
  if (savedSel) { sel = savedSel; }
  return b64;
}

async function doPrint() {
  const btn = document.getElementById("btnPrint");
  btn.disabled = true;
  log("imprimiendo…");
  try {
    const copies = clamp(parseInt(document.getElementById("inCopies").value || 1), 1, 50);
    const density = clamp(parseInt(document.getElementById("inDensity").value || 8), 4, 14);
    const w = mm2dots(doc.widthMm), h = mm2dots(doc.heightMm);
    const body = {
      widthMm: doc.widthMm, wDots: w, hDots: h,
      copies, density, bits: buildRows(),
    };
    const r = await fetch("/api/print", { method: "POST", body: JSON.stringify(body) });
    const j = await r.json();
    if (j.error) log("La impresora rechazó: " + j.error);
    else log(`imprimido: ${copies} copia(s), ${w}×${h} dots`);
    refreshInfo();
  } catch (e) { log("Error: " + e); }
  btn.disabled = false;
}

/* ---------- arranque ---------- */
loadDoc();
document.getElementById("inW").value = doc.widthMm;
document.getElementById("inH").value = doc.heightMm;
render();
refreshInfo();
setInterval(refreshInfo, 15000);
