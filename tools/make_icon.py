#!/usr/bin/env python3
"""Génère l'icône de l'application (PNG puis .iconset) sans dépendance externe.

Le dessin : un carré arrondi sombre, et cinq barres qui montent de gauche à
droite en passant du vert sombre au vert vif — l'image du classement « du plus
calme au plus énergique ».
"""

import math
import os
import struct
import sys
import zlib

BG = (18, 18, 18)
BAR_LOW = (15, 81, 50)
BAR_HIGH = (30, 215, 96)
ICONSET_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _blend(row, index, color, alpha):
    """Compose une couleur sur un pixel RGBA déjà présent."""
    if alpha <= 0:
        return
    alpha = min(1.0, alpha)
    base = index * 4
    old_a = row[base + 3] / 255.0
    new_a = alpha + old_a * (1 - alpha)
    if new_a <= 0:
        return
    for channel in range(3):
        old = row[base + channel] / 255.0 * old_a
        value = (color[channel] / 255.0 * alpha + old * (1 - alpha)) / new_a
        row[base + channel] = max(0, min(255, int(round(value * 255))))
    row[base + 3] = max(0, min(255, int(round(new_a * 255))))


def _span(row, x0, x1, color, alpha=1.0):
    """Remplit [x0, x1[ avec un anticrénelage sur les bords fractionnaires."""
    width = len(row) // 4
    if x1 <= x0:
        return
    x0 = max(0.0, x0)
    x1 = min(float(width), x1)
    if x1 <= x0:
        return
    first, last = int(math.floor(x0)), int(math.ceil(x1))
    for x in range(first, last):
        coverage = min(x + 1.0, x1) - max(float(x), x0)
        if coverage > 0:
            _blend(row, x, color, alpha * coverage)


def _rounded_rect_span(y, x0, y0, x1, y1, radius):
    """Bornes horizontales du carré arrondi pour la ligne y, ou None."""
    if y < y0 or y >= y1:
        return None
    if y < y0 + radius:
        dy = (y0 + radius) - y
    elif y > y1 - radius:
        dy = y - (y1 - radius)
    else:
        return x0, x1
    dy = min(dy, radius)
    dx = math.sqrt(max(0.0, radius * radius - dy * dy))
    return x0 + radius - dx, x1 - radius + dx


def render(size):
    """Renvoie les octets RGBA de l'icône à la taille demandée."""
    scale = size / 1024.0
    margin = 40 * scale
    radius = 225 * scale  # proportions d'une icône macOS
    x0, y0 = margin, margin
    x1, y1 = size - margin, size - margin

    bars = 5
    zone_left = 150 * scale
    zone_right = size - 150 * scale
    zone_bottom = size - 230 * scale
    zone_top = 230 * scale
    gap = 34 * scale
    bar_width = (zone_right - zone_left - gap * (bars - 1)) / bars
    bar_radius = min(bar_width / 2.0, 26 * scale)

    pixels = bytearray()
    for y in range(size):
        center_y = y + 0.5
        row = bytearray(size * 4)

        bounds = _rounded_rect_span(center_y, x0, y0, x1, y1, radius)
        if bounds:
            _span(row, bounds[0], bounds[1], BG, 1.0)

        for index in range(bars):
            left = zone_left + index * (bar_width + gap)
            right = left + bar_width
            height = (zone_bottom - zone_top) * (0.22 + 0.78 * index / (bars - 1.0))
            top = zone_bottom - height
            coverage = min(y + 1.0, zone_bottom) - max(float(y), top)
            if coverage <= 0:
                continue
            span = _rounded_rect_span(center_y, left, top, right, zone_bottom, bar_radius)
            if not span:
                continue
            color = _lerp(BAR_LOW, BAR_HIGH, index / (bars - 1.0))
            _span(row, span[0], span[1], color, min(1.0, coverage))

        pixels += b"\x00" + row  # filtre PNG « None » pour cette ligne
    return bytes(pixels)


def write_png(path, size):
    raw = render(size)

    def chunk(tag, data):
        block = tag + data
        return struct.pack(">I", len(data)) + block + struct.pack(">I", zlib.crc32(block))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # RGBA 8 bits
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as fh:
        fh.write(png)
    return path


def build_iconset(directory):
    os.makedirs(directory, exist_ok=True)
    cache = {}
    for size in ICONSET_SIZES:
        cache[size] = write_png(os.path.join(directory, "_%d.png" % size), size)
    names = [
        ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
    ]
    for name, size in names:
        with open(cache[size], "rb") as src, open(os.path.join(directory, name), "wb") as dst:
            dst.write(src.read())
    for size in ICONSET_SIZES:
        os.remove(cache[size])
    return directory


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "icon.iconset"
    if target.endswith(".png"):
        write_png(target, int(sys.argv[2]) if len(sys.argv) > 2 else 1024)
    else:
        build_iconset(target)
    print(target)
