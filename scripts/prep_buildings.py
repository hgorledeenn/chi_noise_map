"""
Stream coded_bldgs.geojson (EPSG:26971, Illinois State Plane East meters) into a
line-delimited GeoJSON file in EPSG:4326 (lon/lat) for tippecanoe, dropping the
redundant WKT text properties (they duplicate the real geometry as text and
roughly double the file size). Also assigns a sequential integer feature id
(needed for Mapbox hover feature-state) and records dist_train stats/quantiles
for building the color scale.
"""
import json
import sys

import pyproj

SRC = "coded_bldgs.geojson"
DST = "coded_bldgs_4326.geojsonl"
SRC_CRS = "EPSG:26971"

KEEP_PROPS = ("dist_train", "num_intersections", "tot_stories", "max_height")

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


def main():
    dist_train_values = []
    n_written = 0
    n_skipped = 0

    with open(SRC, "r") as fin, open(DST, "w") as fout:
        for i, line in enumerate(fin):
            if i < 4:
                continue
            line = line.strip().rstrip(",")
            if line in ("[", "]", "}", ""):
                continue

            feat = json.loads(line)
            props = feat["properties"]

            dist_train = props.get("dist_train")
            if dist_train is not None:
                dist_train_values.append(dist_train)

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

    dist_train_values.sort()
    n = len(dist_train_values)

    def pct(p):
        idx = min(n - 1, int(p * (n - 1)))
        return dist_train_values[idx]

    stats = {
        "count": n_written,
        "skipped_non_multipolygon": n_skipped,
        "dist_train_min": dist_train_values[0],
        "dist_train_max": dist_train_values[-1],
        "dist_train_quantiles": {
            f"p{int(p * 100)}": pct(p)
            for p in (0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0)
        },
    }
    with open("dist_train_stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
