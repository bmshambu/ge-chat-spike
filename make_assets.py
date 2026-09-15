"""Rasterise the synthetic demo slide library into agent/assets/ (run once, locally).

The probe bundles these files inside the agent package and sends them as data: URIs,
so no storage is involved. Synthetic data only — never point this at a client template.

    python make_assets.py

Outputs:
  assets/slide-01..09.jpg        the 9 library pages, 800 px
  assets/tiny.png                slide 1 at 160 px
  assets/deck60/slide-01..60.jpg the 9 pages cycled to 60, each stamped "N / 60" so order is checkable
  assets/deck60/thumb-01..60.jpg the same at thumbnail size
  assets/heavy60/slide-01..60.jpg photo-heavy 1200 px slides (public gstatic test photos), stamped
  assets/heavy60/thumb-01..60.jpg the same at thumbnail size
"""
import io
import urllib.request
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

PDF = Path(r"C:\GenAi_Prjcts\claude-cowork-demo\Templfy\proposal_builder\ppt_gen_v3\templates\demo\library.pdf")
OUT = Path(__file__).parent / "agent" / "assets"
DECK60 = OUT / "deck60"
SLIDE_WIDTH = 800   # small enough that 9 slides stay well under ~1 MB of base64
TINY_WIDTH = 160
THUMB_WIDTH = 240
DECK_SIZE = 60


def _resize(img, width):
    return img.resize((width, round(img.height * width / img.width)))


def _badge(img, label):
    """Stamp a dark 'N / 60' badge in the top-right corner."""
    img = img.copy()
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=30)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    w, h = right - left + 28, bottom - top + 18
    x, y = img.width - w - 16, 16
    draw.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=(20, 20, 20))
    draw.text((x + 14 - left, y + 9 - top), label, font=font, fill=(255, 255, 255))
    return img


OUT.mkdir(parents=True, exist_ok=True)
DECK60.mkdir(parents=True, exist_ok=True)
pages = []
for i, page in enumerate(pdfium.PdfDocument(PDF), start=1):
    img = page.render(scale=SLIDE_WIDTH / page.get_width()).to_pil().convert("RGB")
    img.save(OUT / f"slide-{i:02d}.jpg", quality=80, optimize=True)
    if i == 1:
        _resize(img, TINY_WIDTH).save(OUT / "tiny.png", optimize=True)
    pages.append(img)

for n in range(1, DECK_SIZE + 1):
    stamped = _badge(pages[(n - 1) % len(pages)], f"{n} / {DECK_SIZE}")
    stamped.save(DECK60 / f"slide-{n:02d}.jpg", quality=80, optimize=True)
    _resize(stamped, THUMB_WIDTH).save(DECK60 / f"thumb-{n:02d}.jpg", quality=70, optimize=True)


# Photo-heavy deck: stands in for real slides with photos/charts, which cost far more bytes
# than the text-only library. 16:9 at 1200 px, photo cover-cropped, title band, badge.
HEAVY60 = OUT / "heavy60"
HEAVY_WIDTH, HEAVY_HEIGHT = 1200, 675
HEAVY60.mkdir(parents=True, exist_ok=True)
photos = []
for k in range(1, 6):
    with urllib.request.urlopen(f"https://www.gstatic.com/webp/gallery/{k}.jpg", timeout=30) as r:
        photos.append(Image.open(io.BytesIO(r.read())).convert("RGB"))


def _cover(photo, w, h):
    scale = max(w / photo.width, h / photo.height)
    img = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


title_font = ImageFont.load_default(size=44)
for n in range(1, DECK_SIZE + 1):
    slide = _cover(photos[(n - 1) % len(photos)], HEAVY_WIDTH, HEAVY_HEIGHT)
    draw = ImageDraw.Draw(slide)
    draw.rectangle((0, HEAVY_HEIGHT - 110, HEAVY_WIDTH, HEAVY_HEIGHT), fill=(0, 60, 110))
    draw.text((48, HEAVY_HEIGHT - 82), f"Synthetic photo slide {n}", font=title_font, fill=(255, 255, 255))
    stamped = _badge(slide, f"{n} / {DECK_SIZE}")
    stamped.save(HEAVY60 / f"slide-{n:02d}.jpg", quality=85, optimize=True)
    _resize(stamped, THUMB_WIDTH).save(HEAVY60 / f"thumb-{n:02d}.jpg", quality=70, optimize=True)


def _total_kb(folder, pattern):
    return sum(f.stat().st_size for f in folder.glob(pattern)) / 1024


for f in sorted(OUT.glob("*.*")):
    print(f"{f.name:14} {f.stat().st_size / 1024:7.1f} KB")
for folder in (DECK60, HEAVY60):
    print(f"{folder.name} slides {_total_kb(folder, 'slide-*.jpg'):7.1f} KB total, "
          f"thumbs {_total_kb(folder, 'thumb-*.jpg'):7.1f} KB total")
