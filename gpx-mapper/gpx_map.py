#!/usr/bin/env python3
"""
Render GPX tracks as a heatmap — overlapping routes glow brighter.

Usage:
    python gpx_map.py maps/*.gpx -o output.png
    python gpx_map.py maps/*.gpx -o output.png --width 4096 --padding 60
"""

import argparse
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import gpxpy
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter

TILE_URL = "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
TILE_SIZE = 256
HEADERS = {"User-Agent": "gpx-heatmap/1.0"}

ACTIVITY_COLORS = {
    "Hike": "pink",
    "Walk": "pink",
    "Run": "red",
    "Ride": "cyan",
}


# ── Mercator projection ────────────────────────────────────────────────────────

def lng_to_tx(lng, zoom):
    return (lng + 180) / 360 * (2 ** zoom)

def lat_to_ty(lat, zoom):
    lat_r = math.radians(lat)
    return (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * (2 ** zoom)

def point_to_px(lat, lng, zoom, origin_tx, origin_ty):
    x = (lng_to_tx(lng, zoom) - origin_tx) * TILE_SIZE
    y = (lat_to_ty(lat, zoom) - origin_ty) * TILE_SIZE
    return x, y


# ── Tile download ──────────────────────────────────────────────────────────────

def fetch_tile(args):
    tx, ty, zoom = args
    url = TILE_URL.format(x=tx, y=ty, z=zoom)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return tx, ty, Image.open(BytesIO(r.content)).convert("RGB")
    except Exception as e:
        print(f"  Warning: tile {tx},{ty}@{zoom} failed: {e}", file=sys.stderr)
        return tx, ty, Image.new("RGB", (TILE_SIZE, TILE_SIZE), (20, 20, 20))


def build_background(zoom, origin_tx, origin_ty, width, height):
    """Download only tiles visible in the output (center-based, not bbox-based)."""
    tx_min = int(origin_tx)
    ty_min = int(origin_ty)
    tx_max = int(origin_tx + width / TILE_SIZE) + 1
    ty_max = int(origin_ty + height / TILE_SIZE) + 1

    jobs = [(tx, ty, zoom) for ty in range(ty_min, ty_max + 1) for tx in range(tx_min, tx_max + 1)]
    total = len(jobs)
    print(f"  Downloading {total} map tiles...")

    canvas = Image.new("RGB", ((tx_max - tx_min + 1) * TILE_SIZE, (ty_max - ty_min + 1) * TILE_SIZE))

    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, (tx, ty, tile) in enumerate(ex.map(fetch_tile, jobs), 1):
            px = (tx - tx_min) * TILE_SIZE
            py = (ty - ty_min) * TILE_SIZE
            canvas.paste(tile, (px, py))
            print(f"  Tiles: {i}/{total}", end="\r")

    print()

    # Crop to exact output size aligned to fractional tile origin
    offset_x = int((origin_tx - tx_min) * TILE_SIZE)
    offset_y = int((origin_ty - ty_min) * TILE_SIZE)
    return canvas.crop((offset_x, offset_y, offset_x + width, offset_y + height))


# ── GPX parsing ────────────────────────────────────────────────────────────────

def detect_color(filename):
    for activity, color in ACTIVITY_COLORS.items():
        if f"-{activity}." in filename or f"-{activity}_" in filename:
            return color
    return "red"


def parse_gpx(path):
    with open(path, encoding="utf-8") as f:
        gpx = gpxpy.parse(f)

    segments = []
    for track in gpx.tracks:
        for seg in track.segments:
            pts = [(p.latitude, p.longitude) for p in seg.points]
            if pts:
                segments.append(pts)
    for route in gpx.routes:
        pts = [(p.latitude, p.longitude) for p in route.points]
        if pts:
            segments.append(pts)
    return segments


# ── Heatmap colorization ───────────────────────────────────────────────────────

def colorize(acc, color):
    """Map normalized 0-1 accumulator to RGB using a glow gradient."""
    # Gradient stops (value → RGB)
    if color == "red":
        stops = [
            (0.0,  (0,   0,   0)),
            (0.25, (80,  0,   0)),
            (0.55, (200, 0,   0)),
            (0.75, (255, 60,  0)),
            (0.90, (255, 160, 30)),
            (1.0,  (255, 255, 200)),
        ]
    elif color == "cyan":
        stops = [
            (0.0,  (0,   0,   0)),
            (0.25, (0,   40,  60)),
            (0.55, (0,   180, 220)),
            (0.75, (0,   230, 255)),
            (1.0,  (200, 255, 255)),
        ]
    else:  # pink / default
        stops = [
            (0.0,  (0,   0,   0)),
            (0.25, (60,  0,   30)),
            (0.55, (220, 80,  120)),
            (0.75, (255, 150, 180)),
            (1.0,  (255, 230, 240)),
        ]

    H, W = acc.shape
    r = np.zeros((H, W), dtype=np.float32)
    g = np.zeros((H, W), dtype=np.float32)
    b = np.zeros((H, W), dtype=np.float32)

    for i in range(len(stops) - 1):
        v0, c0 = stops[i]
        v1, c1 = stops[i + 1]
        mask = (acc >= v0) & (acc < v1)
        t = np.where(mask, (acc - v0) / (v1 - v0), 0)
        r += mask * (c0[0] + t * (c1[0] - c0[0]))
        g += mask * (c0[1] + t * (c1[1] - c0[1]))
        b += mask * (c0[2] + t * (c1[2] - c0[2]))

    # Last stop exact value
    mask = acc >= stops[-1][0]
    r += mask * stops[-1][1][0]
    g += mask * stops[-1][1][1]
    b += mask * stops[-1][1][2]

    rgb = np.stack([r, g, b], axis=-1).clip(0, 255).astype(np.uint8)
    return Image.fromarray(rgb, "RGB")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GPX heatmap renderer")
    parser.add_argument("gpx_files", nargs="*", type=Path,
                        help="GPX files or directories (default: ./maps/)")
    parser.add_argument("-o", "--output", type=Path, default=Path("output.png"))
    parser.add_argument("--width", type=int, default=2048)
    parser.add_argument("--height", type=int, default=2048)
    parser.add_argument("--padding", type=int, default=40, help="Padding in pixels around tracks")
    parser.add_argument("--line-width", type=int, default=3)
    parser.add_argument("--blur", type=float, default=1.5, help="Glow blur radius (0 = off)")
    parser.add_argument("--color", choices=["red", "cyan", "pink"], default=None,
                        help="Override color for all tracks")
    parser.add_argument("--zoom", type=int, help="Force zoom level")
    parser.add_argument("--min-zoom", type=int, default=12, help="Minimum auto-zoom level (default: 12)")
    args = parser.parse_args()

    # Resolve input files — expand directories, default to ./maps/
    inputs = args.gpx_files or [Path("maps")]
    gpx_files = []
    for p in inputs:
        if p.is_dir():
            found = sorted(p.glob("**/*.gpx"))
            print(f"Found {len(found)} GPX file(s) in {p}/")
            gpx_files.extend(found)
        else:
            gpx_files.append(p)

    if not gpx_files:
        print("No GPX files found.", file=sys.stderr)
        sys.exit(1)

    # Load tracks
    all_segments = []  # list of (color, [(lat, lng), ...])

    for path in gpx_files:
        if not path.exists():
            print(f"Warning: {path} not found", file=sys.stderr)
            continue
        color = args.color or detect_color(path.name)
        try:
            segs = parse_gpx(path)
            for seg in segs:
                all_segments.append((color, seg))
            print(f"  {path.name}: {len(segs)} segment(s), color={color}")
        except Exception as e:
            print(f"Warning: {path.name} failed: {e}", file=sys.stderr)

    if not all_segments:
        print("No tracks loaded.", file=sys.stderr)
        sys.exit(1)

    all_lats = [lat for _, seg in all_segments for lat, lng in seg]
    all_lngs = [lng for _, seg in all_segments for lat, lng in seg]
    min_lat, max_lat = min(all_lats), max(all_lats)
    min_lng, max_lng = min(all_lngs), max(all_lngs)

    # Choose zoom to fit content into desired output dimensions
    if args.zoom:
        zoom = args.zoom
    else:
        # Počítej span jen z bodů blízkých mediánu (ignoruj outliers)
        lat_p5, lat_p95 = np.percentile(all_lats, [5, 95])
        lng_p5, lng_p95 = np.percentile(all_lngs, [5, 95])
        for zoom in range(18, 1, -1):
            span_x = (lng_to_tx(lng_p95, zoom) - lng_to_tx(lng_p5, zoom)) * TILE_SIZE
            span_y = (lat_to_ty(lat_p5, zoom) - lat_to_ty(lat_p95, zoom)) * TILE_SIZE
            if span_x <= args.width - args.padding * 2 and span_y <= args.height - args.padding * 2:
                break
        zoom = max(zoom, args.min_zoom)

    print(f"\nUsing zoom level {zoom}")

    # Median center — robustní vůči outlier GPX souborům z jiných měst
    center_lat = float(np.median(all_lats))
    center_lng = float(np.median(all_lngs))
    origin_tx = lng_to_tx(center_lng, zoom) - args.width / (2 * TILE_SIZE)
    origin_ty = lat_to_ty(center_lat, zoom) - args.height / (2 * TILE_SIZE)

    # Build background (exactly width×height)
    bg = build_background(zoom, origin_tx, origin_ty, args.width, args.height)
    W, H = bg.size  # == args.width, args.height

    # Accumulator per color channel
    accumulators = {}

    print(f"Rendering {len(all_segments)} track segment(s)...")
    for i, (color, points) in enumerate(all_segments, 1):
        if color not in accumulators:
            accumulators[color] = np.zeros((H, W), dtype=np.float32)

        px_points = [point_to_px(lat, lng, zoom, origin_tx, origin_ty) for lat, lng in points]
        px_ints = [(int(x), int(y)) for x, y in px_points]

        temp = Image.new("L", (W, H), 0)
        draw = ImageDraw.Draw(temp)
        if len(px_ints) >= 2:
            draw.line(px_ints, fill=200, width=args.line_width)
        accumulators[color] += np.array(temp, dtype=np.float32) / 200.0

        print(f"  Segments: {i}/{len(all_segments)}", end="\r")

    print()

    # Composite each color channel onto background
    result = bg.convert("RGBA")

    for color, acc in accumulators.items():
        acc = np.log1p(acc)
        if acc.max() > 0:
            acc = acc / acc.max()

        heatmap = colorize(acc, color)

        if args.blur > 0:
            heatmap = heatmap.filter(ImageFilter.GaussianBlur(radius=args.blur))

        alpha = (acc * 255).clip(0, 255).astype(np.uint8)
        if args.blur > 0:
            alpha_img = Image.fromarray(alpha, "L").filter(ImageFilter.GaussianBlur(radius=args.blur))
        else:
            alpha_img = Image.fromarray(alpha, "L")

        result.paste(heatmap, (0, 0), alpha_img)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.convert("RGB").save(args.output)
    print(f"Saved to {args.output}  ({result.width}×{result.height}px)")


if __name__ == "__main__":
    main()
