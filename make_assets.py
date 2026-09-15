"""Rasterise the synthetic demo slide library into agent/assets/ (run once, locally).

The probe bundles these files inside the agent package and sends them as data: URIs,
so no storage is involved. Synthetic data only — never point this at a client template.

    python make_assets.py
"""
from pathlib import Path

import pypdfium2 as pdfium

PDF = Path(r"C:\GenAi_Prjcts\claude-cowork-demo\Templfy\proposal_builder\ppt_gen_v3\templates\demo\library.pdf")
OUT = Path(__file__).parent / "agent" / "assets"
SLIDE_WIDTH = 800   # small enough that 9 slides stay well under ~1 MB of base64
TINY_WIDTH = 160

OUT.mkdir(parents=True, exist_ok=True)
pdf = pdfium.PdfDocument(PDF)
for i, page in enumerate(pdf, start=1):
    img = page.render(scale=SLIDE_WIDTH / page.get_width()).to_pil().convert("RGB")
    img.save(OUT / f"slide-{i:02d}.jpg", quality=80, optimize=True)
    if i == 1:
        img.resize((TINY_WIDTH, round(img.height * TINY_WIDTH / img.width))).save(OUT / "tiny.png", optimize=True)

for f in sorted(OUT.iterdir()):
    print(f"{f.name:14} {f.stat().st_size / 1024:7.1f} KB")
