"""Crea il PDF del manuale dalla stessa pagina dell'app, con copertina nei colori del programma.

Uso: python crea_pdf.py <url> <file.pdf> [foto_copertina]   Serve solo la pagina di accesso: nessun dato di ospiti.
"""
import base64
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URL, OUT = sys.argv[1], sys.argv[2]
FOTO = Path(sys.argv[3]) if len(sys.argv) > 3 else None

COPERTINA = """
const c = document.createElement('section');
c.id = 'copertina';
c.innerHTML = '<h1>Manuale di istruzioni</h1><p>' + NOME + '</p><p class="v">Versione ' + VER + '</p>';
const m = document.querySelector('#main');
const ind = document.createElement('section');
ind.id = 'indice';
ind.innerHTML = '<h2>Indice</h2>';
document.querySelectorAll('.man-cap').forEach(a => {
  const l = document.createElement('a');
  l.href = '#' + a.id; l.textContent = a.querySelector('h2').textContent;
  ind.append(l);
});
m.prepend(c, ind);
"""
STILE = """
#copertina { height: 247mm; break-after: page; display: flex; flex-direction: column; justify-content: flex-end; padding: 18mm;
  border-radius: 6mm; color: #fff; print-color-adjust: exact; -webkit-print-color-adjust: exact;
  background: linear-gradient(0deg, #5a2a40e6, #5a2a4066 55%, #6f355022), SFONDO #8a4762 center/cover no-repeat; }
#copertina h1 { font: 600 40pt "Palatino Linotype", Georgia, serif; color: #fff; margin: 0 0 4mm; }
#copertina p { font-size: 16pt; margin: 0; color: #fff; }
#copertina .v { font-size: 11pt; margin-top: 3mm; color: #fbe8ef; }
#indice { break-after: page; padding: 8mm; }
#indice h2 { font: 600 24pt "Palatino Linotype", Georgia, serif; color: #6f3550; margin: 0 0 6mm; }
#indice a { display: block; font-size: 13pt; padding: 2.2mm 0; color: #6f3550; text-decoration: none; border-bottom: 1px solid #ecdad5; }
.man-griglia { margin: 0; }
"""
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1000, "height": 1300}, bypass_csp=True)  # copertina aggiunta solo per il PDF
    pg.goto(URL)
    pg.get_by_role("button", name="Apri il manuale di istruzioni").click()
    pg.evaluate("window.print = () => {}")
    pg.get_by_role("button", name="Stampa il manuale").click()
    pg.wait_for_function("[...document.images].every(i => i.complete)", timeout=60000)
    st = pg.evaluate("fetch('/api/status').then(r => r.json())")
    sf = ""
    if FOTO:
        sf = f'url("data:image/jpeg;base64,{base64.b64encode(FOTO.read_bytes()).decode()}"),'.replace("),", ") center/cover no-repeat,")
    pg.add_style_tag(content=STILE.replace("SFONDO", sf))
    pg.evaluate("([NOME, VER]) => {" + COPERTINA + "}", [st["app"], st["version"]])
    pg.emulate_media(media="print")
    pg.pdf(path=OUT, format="A4", print_background=True, margin={"top": "15mm", "bottom": "16mm", "left": "13mm", "right": "13mm"},
           display_header_footer=True, header_template="<span></span>",
           footer_template='<div style="width:100%;text-align:center;font-size:8px;color:#75656f">Pagina <span class="pageNumber"></span> di <span class="totalPages"></span></div>')
    b.close()
print(OUT)
