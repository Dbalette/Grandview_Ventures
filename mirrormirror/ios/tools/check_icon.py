#!/usr/bin/env python3
"""Numeric checks on the App Store icon (Arizona playbook 12.5: numeric, never eyeballed).

    python3 check_icon.py [path/to/AppIcon-1024.png]

Fails unless the icon is
  * exactly 1024x1024,
  * opaque (App Store Connect rejects an alpha channel), and
  * plain background in every pixel an iOS icon mask clips. iOS rounds the corners of the square art, so any border,
    vignette or detail that reaches a corner is cut off and reads as a mistake.
The mask is a superellipse (exponent 5), a little more aggressive than Apple's own shape, so passing it is safe.
Pure standard library: runs on a Mac, on a CI runner and here.
"""
import struct
import sys
import zlib

DEFAULT = "MirrorMirror/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png"
EXPONENT = 5
TOLERANCE = 24  # summed per-channel difference from the corner colour that counts as "art"


def read_png(path):
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path}: not a PNG")
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    width, height, depth, ctype, _, _, interlace = ihdr
    if depth != 8 or ctype not in (2, 6) or interlace != 0:
        raise SystemExit(f"{path}: need an 8-bit, non-interlaced RGB or RGBA PNG (got depth {depth}, type {ctype}, interlace {interlace})")
    bpp = 3 if ctype == 2 else 4
    raw = zlib.decompress(idat)
    stride = width * bpp
    rows, prev = [], bytearray(stride)
    for y in range(height):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    return width, height, bpp, rows


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    width, height, bpp, rows = read_png(path)
    problems = []
    if (width, height) != (1024, 1024):
        problems.append(f"size is {width}x{height}, need 1024x1024")
    if bpp == 4 and any(row[i] != 255 for row in rows for i in range(3, len(row), 4)):
        problems.append("the icon has transparent pixels; App Store Connect rejects an alpha channel")
    bg = tuple(rows[0][0:3])
    clipped = art = 0
    for y in range(height):
        v = ((y + 0.5) / height) * 2 - 1
        row = rows[y]
        for x in range(width):
            u = ((x + 0.5) / width) * 2 - 1
            if abs(u) ** EXPONENT + abs(v) ** EXPONENT > 1:  # outside the squircle: the mask throws this away
                clipped += 1
                i = x * bpp
                if abs(row[i] - bg[0]) + abs(row[i + 1] - bg[1]) + abs(row[i + 2] - bg[2]) > TOLERANCE:
                    art += 1
    if art:
        problems.append(f"{art} of {clipped} pixels in the masked-off corners are not plain background (a border or detail reaches the corners)")
    print(f"{path}: {width}x{height}, background rgb{bg}, {clipped} masked-off pixels checked")
    if problems:
        for p in problems:
            print("FAIL:", p)
        sys.exit(1)
    print("PASS: opaque, 1024x1024, nothing but background where the mask clips")


if __name__ == "__main__":
    main()
