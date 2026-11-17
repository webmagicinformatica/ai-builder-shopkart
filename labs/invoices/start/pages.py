"""Part 1, step 1: a document becomes page images the model can read.

A PDF is rendered page by page (pypdfium2: a pip wheel, nothing to apt-get).
A PNG or JPEG photo is one page already. Then two cheap moves before we pay:
  - trim the blank margins (a half-empty A4 page is half wasted tokens)
  - cap the long side, so we decide the size, not the provider's resizer

Images are billed by patches: Claude cuts them into 28 x 28 pixel squares,
about one token each. `image_tokens()` is that estimate, before any call.
"""

import io
import math
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageFilter, ImageStat

DPI = 150          # PDF render resolution: small print stays sharp
MAX_SIDE = 1568    # longest side we send, in pixels
PATCH = 28         # Claude's patch size; about one token per patch


def load_pages(path: Path) -> list[Image.Image]:
    """Every page of a PDF, or the one image, as RGB images."""
    path = Path(path)
    # TODO 1: a PDF -> one image per page; a PNG or JPEG -> a list with one image.
    #   pdf = pdfium.PdfDocument(path); for each page: page.render(scale=DPI / 72).to_pil()
    #   (PDF points are 1/72 inch, so scale=DPI/72 renders at DPI). Close the PDF when done.
    #   A photo: Image.open(path). Convert everything to "RGB".
    raise NotImplementedError("TODO 1: render the pages")


def trim_margins(img: Image.Image, pad: int = 24) -> Image.Image:
    """Crop away the white border around the printed area."""
    white = Image.new("RGB", img.size, (255, 255, 255))
    box = ImageChops.difference(img, white).convert("L").point(lambda v: 255 if v > 24 else 0).getbbox()
    if not box:
        return img  # a blank page
    left, top, right, bottom = box
    return img.crop((max(0, left - pad), max(0, top - pad),
                     min(img.width, right + pad), min(img.height, bottom + pad)))


def fit(img: Image.Image, max_side: int = MAX_SIDE) -> Image.Image:
    """Shrink so the longest side is at most `max_side`. Never enlarges."""
    scale = max_side / max(img.size)
    if scale >= 1:
        return img
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def prepare(path: Path) -> list[Image.Image]:
    """The page images we actually send: trimmed and capped."""
    return [fit(trim_margins(page)) for page in load_pages(path)]


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def image_tokens(img: Image.Image) -> int:
    """About one token per 28 x 28 patch (Claude). OpenAI counts differently: see the bill."""
    # TODO 2: how many 28 x 28 patches cover the image? Round each side up.
    raise NotImplementedError("TODO 2: estimate the image tokens")


def sharpness(img: Image.Image) -> float:
    """How sharp the page is: variance of a Laplacian edge filter, at a fixed 1000 px width.

    Crisp print scores in the hundreds. A blurred phone photo scores far lower.
    A check you compute yourself, instead of asking the model how sure it is.
    """
    gray = img.convert("L")
    gray = gray.resize((1000, max(1, round(1000 * gray.height / gray.width))))
    edges = gray.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
    return ImageStat.Stat(edges).var[0]


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from shopkart import data

    out = Path(".shopkart/pages")
    out.mkdir(parents=True, exist_ok=True)
    print(f"{'file':<34}{'original':>12}{'sent':>12}{'~tokens':>9}{'sharpness':>11}")
    for f in data.invoice_files():
        original = load_pages(f)[0]
        sent = prepare(f)[0]
        sent.save(out / f"{f.stem}.png")
        print(f"{f.name:<34}{'%dx%d' % original.size:>12}{'%dx%d' % sent.size:>12}"
              f"{image_tokens(sent):>9}{sharpness(original):>11.0f}")
    print(f"\nThe images the model will see are in {out}/")
