const {chromium}=require('playwright');const fs=require('fs');
const [src,out,title]=process.argv.slice(2);
const code=fs.readFileSync(src,'utf8');
const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const lines=code.replace(/\n$/,'').split('\n');const n=lines.length;
const d=new Date().toLocaleString('es-ES',{timeZone:'Europe/Madrid'});
const html=`<!doctype html><meta charset="utf-8"><style>
body{font-family:Arial,sans-serif;margin:0}
h1{font-size:16pt;margin:0 0 4px}.sub{font-size:9pt;color:#555;margin-bottom:10px}
.box{background:#f3f4f6;border-left:4px solid #2563eb;padding:6px 10px;font-size:9pt;margin-bottom:12px}
table{border-collapse:collapse;width:100%;font-family:Consolas,'DejaVu Sans Mono',monospace;font-size:7.2pt}
td{vertical-align:top;padding:0 4px;white-space:pre-wrap;word-break:break-all}
td.n{color:#999;text-align:right;width:28px;user-select:none;border-right:1px solid #ddd}
</style><h1>${esc(title)}</h1><div class="sub">Pine Script v6 · ${n} líneas · generado ${d}</div>
<div class="box">Para usarlo en TradingView copia el código desde el archivo .pine o desde la página del código (no desde este PDF: los números de línea y los saltos de página se copiarían). La última línea es «// Fin del script».</div>
<table>${lines.map((l,i)=>`<tr><td class="n">${i+1}</td><td>${esc(l)||' '}</td></tr>`).join('')}</table>`;
(async()=>{const b=await chromium.launch();const p=await b.newPage();await p.setContent(html);
await p.pdf({path:out,format:'A4',margin:{top:'12mm',bottom:'14mm',left:'10mm',right:'10mm'},displayHeaderFooter:true,headerTemplate:'<span></span>',footerTemplate:`<div style="font-size:7pt;width:100%;text-align:center;color:#888">${esc(title)} · página <span class="pageNumber"></span> de <span class="totalPages"></span></div>`});await b.close();})();
