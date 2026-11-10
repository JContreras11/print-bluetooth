#!/usr/bin/env python3
"""Imprime una etiqueta de prueba en la Y50 para verificar el protocolo.

Uso:
  python3 scripts/print_test.py            # imprime "PRUEBA YPL" con borde y rayas
  python3 scripts/print_test.py texto      # imprime el texto que le pases
  python3 scripts/print_test.py status     # solo consulta de información
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFont
from lib.printer import Printer, explain_link_error
from lib.ypl import DPI

TESTPATTERN_TEXT = "PRUEBA YPL"
TESTPATTERN_FOOTER = "OK"


def make_label(width_mm=50, height_mm=30, texto=TESTPATTERN_TEXT):
    dpm = DPI
    W, H = width_mm * dpm, height_mm * dpm
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W - 1, H - 1], outline=0, width=2)

    font = _font(48)
    box = d.textbbox((0, 0), texto, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((W - tw) // 2 - box[0], 14), texto, font=font, fill=0)

    # rayas de 1 mm en la base para verificar el correcto alineado
    y0 = H - 22
    for i in range(0, width_mm, 2):
        d.rectangle([i * 8, y0, i * 8 + 8 - 1, H - 12], fill=0 if (i // 2) % 2 == 0 else 255)

    font2 = _font(22)
    box = d.textbbox((0, 0), TESTPATTERN_FOOTER, font=font2)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((W - tw) // 2 - box[0], y0 - 24 - th), TESTPATTERN_FOOTER, font=font2, fill=0)

    px = img.load()
    return [[1 if px[x, y] < 128 else 0 for x in range(W)] for y in range(H)]


def _font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def bigtext_rows(text, width_mm=50, height_mm=30):
    dpm = DPI
    W, H = width_mm * dpm, height_mm * dpm
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=0, width=2)
    size = 70
    while size > 10:
        font = _font(size)
        box = d.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= W - 16 and box[3] - box[1] <= H - 16:
            break
        size -= 4
    d.text(((W - box[2]) // 2, (H - box[3]) // 2 - box[1]), text, font=font, fill=0)
    px = img.load()
    return [[1 if px[x, y] < 128 else 0 for x in range(W)] for y in range(H)]


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "testpattern"
    p = Printer()
    try:
        info = p.info()
    except OSError as e:
        sys.exit(explain_link_error(e))
    print(">", info)
    if not info.get("ready", False):
        print("!! La impresora no está lista, aborto")
        return 1

    if cmd == "status":
        p.close()
        return 0

    if cmd == "texto":
        if len(sys.argv) < 3:
            sys.exit("uso: python3 scripts/print_test.py texto \"HOLA\"")
        rows = bigtext_rows(sys.argv[2])
    else:
        rows = make_label()

    print("imprimiendo etiqueta de prueba ...")
    p.print_rows(rows, 50, copies=1, on_status=lambda s: print(" estado:", s))
    print("listo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
