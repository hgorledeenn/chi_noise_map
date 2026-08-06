"""
Stream nb3_buildings_coded.geojson (EPSG:26971, Illinois State Plane East meters)
into a line-delimited GeoJSON file in EPSG:4326 (lon/lat) for tippecanoe. Also
assigns a sequential integer feature id (needed for Mapbox hover feature-state)
and records daily_noise stats/quantiles for building the color scale.

daily_noise is heavily zero-inflated (~80% of buildings have no modeled train
noise at all), so a plain quantile split would waste most of the color ramp on
one repeated value. Instead the first color stop is pinned to 0 (no noise) and
the remaining 8 stops are quantiles of the NONZERO subset only, spreading the
ramp across the buildings that actually have measurable noise.
"""
import json
import sys

import pyproj

SRC = "nb3_buildings_coded.geojson"
DST = "nb3_buildings_4326.geojsonl"
SRC_CRS = "EPSG:26971"

KEEP_PROPS = (
    "daily_noise",
    "noise_from_one_train",
    "intersected_daily_noise",
    "intersected_noise_from_one_train",
    "num_radials",
)

transformer = pyproj.Transformer.from_crs(SRC_CRS, "EPSG:4326", always_xy=True)


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
    daily_noise_values = []
    n_written = 0
    n_skipped = 0

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
            if daily_noise is not None:
                daily_noise_values.append(daily_noise)

            geom = feat["geometry"]
            if geom["type"] != "MultiPolygon":
                n_skipped += 1
                continue
            geom["coordinates"] = reproject_multipolygon(geom["coordinates"])

            out_feat = {
                "type": "Feature",
                "id": n_written,
                "properties": {k: props.get(k) for k in KEEP_PROPS},
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
