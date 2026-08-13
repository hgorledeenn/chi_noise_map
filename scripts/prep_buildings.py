"""
Stream nb3_buildings_coded.geojson (EPSG:26971, Illinois State Plane East meters)
into a line-delimited GeoJSON file in EPSG:4326 (lon/lat) for tippecanoe. Also
assigns a sequential integer feature id (needed for Mapbox hover feature-state),
joins each building to its nearest street address (see ADDRESS JOIN below), and
records daily_noise stats/quantiles for building the color scale.

daily_noise is heavily zero-inflated (~80% of buildings have no modeled train
noise at all), so a plain quantile split would waste most of the color ramp on
one repeated value. Instead the first color stop is pinned to 0 (no noise) and
the remaining 8 stops are quantiles of the NONZERO subset only, spreading the
ramp across the buildings that actually have measurable noise.

ADDRESS JOIN -- nb3_buildings_coded.geojson only ever carried the noise-model
fields it was built for, no address. Rather than reverse-geocoding on demand in
the browser (slow, and one Nominatim request per building isn't something that
scales to 820k buildings), each building is matched once here, offline, to the
nearest point in chicago_address_points.csv (Cook County GIS's Address Points
layer -- see fetch_address_points.py) within ADDRESS_MAX_DIST meters of its
centroid. The result is baked in as a real "address" tile property, same as
daily_noise etc, so the browser never has to ask anywhere at runtime.

NOISE PERCENTILE -- same idea: a building's percentile rank among all buildings
with SOME train noise (daily_noise > 0) requires knowing that whole
distribution up front, so a first pass over SRC collects it before the main
pass computes each building's rank against it (see collect_daily_noise_values
/ noise_percentile below) and bakes it in as "noise_percentile", again so the
browser never recomputes it per hover.
"""
import bisect
import csv
import json
import sys

import pyproj
from scipy.spatial import cKDTree
from shapely.geometry import shape

SRC = "nb3_buildings_coded.geojson"
DST = "nb3_buildings_4326.geojsonl"
SRC_CRS = "EPSG:26971"
ADDRESS_POINTS_CSV = "chicago_address_points.csv"
ADDRESS_MAX_DIST = 75  # meters -- beyond this, treat the building as unmatched

KEEP_PROPS = (
    "daily_noise",
    "noise_from_one_train",
    "intersected_daily_noise",
    "intersected_noise_from_one_train",
    "num_radials",
)

transformer = pyproj.Transformer.from_crs(SRC_CRS, "EPSG:4326", always_xy=True)
to_src_crs = pyproj.Transformer.from_crs("EPSG:4326", SRC_CRS, always_xy=True)

# Directions and street-type abbreviations get a trailing period ("W", "AVE"
# -> "W.", "Ave."); everything else is just title-cased -- turns Cook
# County's "1763 W WELLINGTON AVE" into "1763 W. Wellington Ave.", matching
# the address style already used in this project's own story copy.
DIRECTIONS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}
STREET_TYPES = {
    "AVE", "ST", "BLVD", "CT", "DR", "LN", "PL", "RD", "PKWY", "TER", "CIR",
    "WAY", "HWY", "SQ", "PLZ", "EXPY", "FWY", "LOOP", "TRL", "PATH", "ROW",
}


def format_address(raw):
    tokens = raw.split()
    out = []
    for i, tok in enumerate(tokens):
        upper = tok.upper()
        if tok[0].isdigit():
            out.append(tok)
        elif upper in DIRECTIONS:
            out.append(upper + ".")
        elif i == len(tokens) - 1 and upper in STREET_TYPES:
            out.append(upper.capitalize() + ".")
        else:
            out.append(tok.capitalize())
    return " ".join(out)


def load_address_index():
    """cKDTree of Chicago address points, reprojected into SRC_CRS (meters)
    so nearest-neighbor distances line up with building centroids computed
    directly from the untransformed (still-meters) building geometry."""
    lons, lats, addrs = [], [], []
    with open(ADDRESS_POINTS_CSV, newline="") as f:
        for row in csv.DictReader(f):
            lons.append(float(row["lon"]))
            lats.append(float(row["lat"]))
            addrs.append(row["address"])
    xs, ys = to_src_crs.transform(lons, lats)
    tree = cKDTree(list(zip(xs, ys)))
    return tree, addrs


def reproject_multipolygon(coords):
    # coords: [ polygon [ ring [ [x, y], ... ] ] ]
    for polygon in coords:
        for ring in polygon:
            xs = [pt[0] for pt in ring]
            ys = [pt[1] for pt in ring]
            lons, lats = transformer.transform(xs, ys)
            for i in range(len(ring)):
                ring[i] = [round(lons[i], 7), round(lats[i], 7)]
    return coords


def collect_daily_noise_values():
    """A lightweight first pass over SRC -- just the daily_noise field, no
    geometry work -- so the main pass below can compute each building's
    percentile rank against the full distribution as it goes, instead of
    only being able to report distribution-wide stats after the fact."""
    values = []
    with open(SRC, "r") as fin:
        started = False
        for line in fin:
            if not started:
                if line.strip() == '"features": [':
                    started = True
                continue
            line = line.strip().rstrip(",")
            if line in ("[", "]", "}", ""):
                continue
            feat = json.loads(line)
            daily_noise = feat["properties"].get("daily_noise")
            if daily_noise is not None:
                values.append(daily_noise)
    return values


def color_stops(values, n_stops=16):
    """0, then n_stops - 1 quantiles of the nonzero subset -- see module
    docstring. More stops than colors in the map's COLOR_STEPS ramp gives a
    more gradual transition, since each stop only has to cover a narrower
    slice of the (heavily skewed) nonzero range."""
    nonzero = sorted(v for v in values if v > 0)
    n = len(nonzero)

    def pct(p):
        idx = min(n - 1, int(p * (n - 1)))
        return nonzero[idx]

    return [0.0] + [pct(i / (n_stops - 1)) for i in range(1, n_stops)]


def main():
    print("Collecting daily_noise distribution...", file=sys.stderr)
    daily_noise_values = collect_daily_noise_values()
    nonzero_sorted = sorted(v for v in daily_noise_values if v > 0)
    n_nonzero_total = len(nonzero_sorted)

    def noise_percentile(v):
        # Rank among buildings with SOME train noise, per bisect_right: a
        # building whose value ties the population max still reads 100, and
        # 0 (no train noise at all) always reads 0 since nonzero_sorted has
        # no values <= 0 to rank below.
        if n_nonzero_total == 0 or v is None:
            return 0
        return round(bisect.bisect_right(nonzero_sorted, v) / n_nonzero_total * 100)

    print("Loading address point index...", file=sys.stderr)
    address_tree, addresses = load_address_index()

    n_written = 0
    n_skipped = 0
    n_matched = 0

    with open(SRC, "r") as fin, open(DST, "w") as fout:
        started = False
        for line in fin:
            if not started:
                if line.strip() == '"features": [':
                    started = True
                continue

            line = line.strip().rstrip(",")
            if line in ("[", "]", "}", ""):
                continue

            feat = json.loads(line)
            props = feat["properties"]

            daily_noise = props.get("daily_noise")

            geom = feat["geometry"]
            if geom["type"] != "MultiPolygon":
                n_skipped += 1
                continue

            # Centroid in SRC_CRS meters -- computed BEFORE
            # reproject_multipolygon below, which mutates geom's coordinates
            # in place into lon/lat.
            cx, cy = shape(geom).centroid.coords[0]
            dist, idx = address_tree.query((cx, cy), distance_upper_bound=ADDRESS_MAX_DIST)
            if dist != float("inf"):
                address = format_address(addresses[idx])
                n_matched += 1
            else:
                address = None

            geom["coordinates"] = reproject_multipolygon(geom["coordinates"])

            out_feat = {
                "type": "Feature",
                "id": n_written,
                "properties": {
                    **{k: props.get(k) for k in KEEP_PROPS},
                    "address": address,
                    "noise_percentile": noise_percentile(daily_noise),
                },
                "geometry": geom,
            }
            fout.write(json.dumps(out_feat, separators=(",", ":")))
            fout.write("\n")
            n_written += 1

            if n_written % 100000 == 0:
                print(f"  ...{n_written} features written", file=sys.stderr)

    daily_noise_values.sort()
    n = len(daily_noise_values)
    n_nonzero = sum(1 for v in daily_noise_values if v > 0)

    def pct(p):
        idx = min(n - 1, int(p * (n - 1)))
        return daily_noise_values[idx]

    stats = {
        "count": n_written,
        "skipped_non_multipolygon": n_skipped,
        "address_matched": n_matched,
        "address_matched_fraction": n_matched / n_written,
        "daily_noise_min": daily_noise_values[0],
        "daily_noise_max": daily_noise_values[-1],
        "daily_noise_nonzero_fraction": n_nonzero / n,
        "daily_noise_quantiles": {
            f"p{int(p * 100)}": pct(p)
            for p in (0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0)
        },
        "daily_noise_color_stops": color_stops(daily_noise_values),
    }
    with open("daily_noise_stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
