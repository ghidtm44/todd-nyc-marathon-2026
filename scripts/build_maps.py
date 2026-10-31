#!/usr/bin/env python3
"""Render static, annotated crops of NYRR's published 2026 course map.

No network calls. The source PDF is retained separately, unmodified. Marker
locations are PDF page coordinates reviewed against the official document;
they are not geographic/surveyed coordinates.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import fitz
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "official-course-2026.pdf"
ASSETS = ROOT / "assets"
START = datetime(2026, 11, 1, 10, 55, tzinfo=ZoneInfo("America/New_York"))
FIRST_MILE_SECONDS = 9 * 60 + 22
LATER_MILE_SECONDS = 8 * 60 + 50
DISTANCE_MILES = 42.195 / 1.609344
SOURCE_SHA256 = "69681416e1cf2eefa5407c74c9dfa01a4573f43fe6d99fc772bd4d0058d9c8ff"

# These are centers of the actual printed numeral spans in the official PDF,
# reviewed at high resolution. The 2 and 3 below are the Pink course markers.
# Subway route numerals, kilometer symbols and the legend are excluded.
REVIEWED_CENTERS = {
    1: (288.77, 1144.65), 2: (318.22, 1086.10), 3: (312.93, 1035.11),
    4: (290.59, 999.74), 5: (299.47, 943.08), 6: (309.31, 885.25),
    7: (315.09, 830.59), 8: (307.65, 777.20), 9: (354.05, 741.23),
    10: (338.60, 695.33), 11: (301.74, 661.24), 12: (309.96, 608.55),
    13: (284.39, 566.49), 14: (263.56, 516.07), 15: (269.20, 492.21),
    16: (216.25, 492.21), 17: (210.45, 433.87), 18: (210.69, 373.65),
    19: (209.43, 308.70), 20: (214.44, 251.65), 21: (180.28, 239.05),
    22: (164.51, 294.48), 23: (169.51, 354.72), 24: (164.08, 410.94),
    25: (159.29, 476.96), 26: (138.64, 483.31),
}

# Bounds select published map detail, never a reconstructed course drawing.
PANELS = [
    {"file": "course-1.png", "title": "START + BROOKLYN", "subtitle": "Pink course · Start to mile 8",
     "clip": (185, 745, 455, 1210), "keys": ["start", *range(1, 9)],
     "left": {"start", 1, 4, 6, 8}},
    {"file": "course-2.png", "title": "BROOKLYN TO MANHATTAN", "subtitle": "Miles 9–16 · via Queens",
     "clip": (175, 470, 435, 770), "keys": list(range(9, 17)),
     "left": {11, 13, 14, 16}},
    {"file": "course-3.png", "title": "UPTOWN + THE FINISH", "subtitle": "Miles 17–26 · Bronx and Central Park",
     "clip": (90, 180, 300, 517), "keys": [*range(17, 27), "finish"],
     "left": {21, 22, 23, 24, 26, "finish"}},
]


def arrival(mile: float) -> datetime:
    seconds = 0 if mile == 0 else FIRST_MILE_SECONDS + (mile - 1) * LATER_MILE_SECONDS
    return START + timedelta(seconds=round(seconds))


def clock(mile: float, seconds: bool = False) -> str:
    fmt = "%I:%M:%S %p" if seconds else "%I:%M %p"
    # Map labels round to the nearest minute. The HTML table can retain exact
    # model seconds without suggesting race estimates are that precise.
    projected = arrival(mile)
    if not seconds:
        projected += timedelta(seconds=30)
    return projected.strftime(fmt).lstrip("0")


def inspect(page: fitz.Page) -> dict:
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                label = span["text"].strip()
                if label.isdigit() or label in {"START", "FINISH", "Mile", "Kilometer"}:
                    spans.append({key: span[key] for key in ("text", "bbox", "font", "size", "color")})
    return {"page": list(page.rect), "spans": spans}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    paths = [Path("/usr/share/fonts/truetype/dejavu") / name,
             Path("/usr/share/fonts/truetype/liberation2") / ("LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf")]
    for path in paths:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.truetype(name, size)


def spread_labels(items: list[tuple[str, float, float]], top: float, bottom: float,
                  spacing: float = 88) -> list[tuple[str, float, float, float]]:
    """Keep same-side leaders ordered and label boxes nonoverlapping."""
    ordered = sorted(items, key=lambda item: item[2])
    placed = []
    for key, x, y in ordered:
        label_y = max(y, top if not placed else placed[-1][3] + spacing)
        placed.append((key, x, y, label_y))
    if placed and placed[-1][3] > bottom:
        delta = placed[-1][3] - bottom
        placed = [(key, x, y, ly - delta) for key, x, y, ly in placed]
    return placed


def reviewed_markers(page: fitz.Page) -> dict:
    spans = inspect(page)["spans"]
    markers = {}
    for mile, (expected_x, expected_y) in REVIEWED_CENTERS.items():
        candidates = []
        for span in spans:
            if span["text"].strip() != str(mile) or span["color"] != 0xFFFFFF:
                continue
            x0, y0, x1, y1 = span["bbox"]
            x, y = (x0+x1)/2, (y0+y1)/2
            if abs(x-expected_x) < 0.1 and abs(y-expected_y) < 0.1:
                candidates.append((x, y))
        if len(candidates) != 1:
            raise ValueError(f"Reviewed mile {mile} did not resolve uniquely: {candidates}")
        markers[mile] = candidates[0]
    # Centers of the official green START and red FINISH circle vector shapes.
    markers["start"] = (259.5684, 1183.2343)
    markers["finish"] = (142.6955, 464.2351)
    return markers


def render_panel(page: fitz.Page, definition: dict, markers: dict) -> None:
    width = 840
    gutter = 220
    map_width = width - 2*gutter
    header, footer = 122, 82
    crop = fitz.Rect(definition["clip"])
    scale = map_width / crop.width
    map_height = round(crop.height * scale)
    # A uniform scale preserves the proportions of NYRR's published map.
    scale_y = scale
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=crop, alpha=False)
    map_image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    map_image = map_image.resize((map_width, map_height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, map_height + header + footer), "#f9f7f0")
    canvas.paste(map_image, (gutter, header))
    draw = ImageDraw.Draw(canvas)
    navy, pink = "#18234b", "#bd2467"
    draw.text((24, 20), definition["title"], font=font(31, True), fill=navy)
    draw.text((24, 62), definition["subtitle"], font=font(24), fill="#45516d")
    positions = {key: (gutter + (markers[key][0]-crop.x0)*scale,
                       header + (markers[key][1]-crop.y0)*scale_y)
                 for key in definition["keys"]}
    for side in ("left", "right"):
        items = [(key, *positions[key]) for key in definition["keys"]
                 if (key in definition["left"]) == (side == "left")]
        placed = spread_labels(items, header+48, header+map_height-48, spacing=90)
        for key, x, y, label_y in placed:
            edge = gutter-10 if side == "left" else width-gutter+10
            end = x-10 if side == "left" else x+10
            # A light casing keeps estimate leaders distinct from the white
            # transit annotation leaders present on NYRR's original map.
            line = [(edge, label_y), (end, y)]
            draw.line(line, fill="#fff7fb", width=6)
            draw.line(line, fill=pink, width=3)
            draw.ellipse((end-4, y-4, end+4, y+4), fill=pink, outline="white", width=1)
            x0 = 11 if side == "left" else width-gutter+15
            x1 = gutter-15 if side == "left" else width-11
            draw.rounded_rectangle((x0, label_y-41, x1, label_y+41), radius=10,
                                   fill="#ffffff", outline="#e3d6de", width=2)
            label = str(key).upper() if isinstance(key, str) else f"MILE {key}"
            mile = 0 if key == "start" else DISTANCE_MILES if key == "finish" else key
            draw.text(((x0+x1)/2, label_y-35), label, font=font(20, True), fill=pink, anchor="mt")
            draw.text(((x0+x1)/2, label_y-7), clock(mile), font=font(34, True), fill=navy, anchor="mt")
    yfooter = header+map_height+15
    draw.text((24, yfooter), "ESTIMATED · Sun Nov 1 · New York EST", font=font(21, True), fill=navy)
    draw.text((24, yfooter+29), "Official 2026 NYRR map detail; Todd’s times added.", font=font(20), fill="#45516d")
    canvas.save(ASSETS / definition["file"], optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true", help="Print marker span diagnostics only")
    args = parser.parse_args()
    if not SOURCE.exists():
        raise SystemExit(f"Official PDF missing: {SOURCE}")
    document = fitz.open(SOURCE)
    if len(document) != 1:
        raise SystemExit("Expected the one-page official 2026 course PDF")
    page = document[0]
    if args.inspect:
        print(json.dumps(inspect(page), indent=2))
        return
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit("Official PDF has changed; review marker locations before rebuilding")
    ASSETS.mkdir(parents=True, exist_ok=True)
    markers = reviewed_markers(page)
    for definition in PANELS:
        render_panel(page, definition, markers)
    page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(ASSETS / "official-course-2026.png")
    report = {"source_sha256": digest, "timezone": "America/New_York", "offset": START.strftime("%z"),
              "finish": clock(DISTANCE_MILES, seconds=True),
              "markers": [{"mile": key, "pdf_xy": list(value),
                           "time": clock(0 if key == "start" else DISTANCE_MILES if key == "finish" else key, seconds=True)}
                          for key, value in markers.items()]}
    (ASSETS / "map-build-report.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"generated": [p["file"] for p in PANELS], "markers": len(markers),
                      "finish": report["finish"], "offset": report["offset"]}))


if __name__ == "__main__":
    main()
