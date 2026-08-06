"""
Aggregate the reprojected buildings (coded_bldgs_4326.geojsonl, from
prep_buildings.py) into square grids at three cell sizes, so the map can show
a coarse city-wide summary at low zoom, an intermediate level of detail, and
switch to individual buildings once zoomed in close.

Grid cells are defined directly in lon/lat, sized in meters using a single
reference latitude for the whole city (Chicago spans <0.4 degrees of
latitude, so cos(lat) varies <1% across it -- one reference latitude keeps
cells aligned into a clean grid without visibly distorting their shape).

Uses each building's first-ring vertex average as a cheap stand-in for its
centroid -- buildings are tiny relative to cell size, so this is accurate
enough for bucketing without needing a full shapely centroid over 820k
geometries.
"""
import json
import math

SRC = "coded_bldgs_4326.geojsonl"
REF_LAT = 41.85  # Chicago-ish; used to convert meters -> degrees longitude
METERS_PER_DEG_LAT = 111320.0
METERS_PER_DEG_LON = METERS_PER_DEG_LAT * math.cos(math.radians(REF_LAT))

# (label, cell size in meters, output filename)
GRIDS = [
    (300, "grid300.geojson"),
    (120, "grid120.geojson"),
    (45, "grid45.geojson"),
]


def rough_point(geom):
    ring = geom["coordinates"][0][0]
    n = len(ring)
    lon = sum(p[0] for p in ring) / n
    lat = sum(p[1] for p in ring) / n
    return lon, lat


def cell_polygon(row, col, dlat, dlon):
    lat0, lat1 = row * dlat, (row + 1) * dlat
    lon0, lon1 = col * dlon, (col + 1) * dlon
    ring = [
        [round(lon0, 7), round(lat0, 7)],
        [round(lon1, 7), round(lat0, 7)],
        [round(lon1, 7), round(lat1, 7)],
        [round(lon0, 7), round(lat1, 7)],
        [round(lon0, 7), round(lat0, 7)],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def main():
    buckets = {size: {} for size, _ in GRIDS}  # size -> {(row, col): [sum, count]}

    with open(SRC) as f:
        for i, line in enumerate(f):
            feat = json.loads(line)
            dist_train = feat["properties"]["dist_train"]
            lon, lat = rough_point(feat["geometry"])

            for size, _ in GRIDS:
                dlat = size / METERS_PER_DEG_LAT
                dlon = size / METERS_PER_DEG_LON
                cell = (math.floor(lat / dlat), math.floor(lon / dlon))
                bucket = buckets[size].setdefault(cell, [0.0, 0])
                bucket[0] += dist_train
                bucket[1] += 1

            if (i + 1) % 200000 == 0:
                print(f"  ...{i + 1} buildings processed")

    stats = {}
    for size, fname in GRIDS:
        dlat = size / METERS_PER_DEG_LAT
        dlon = size / METERS_PER_DEG_LON
        means = []
        with open(fname, "w") as out:
            for (row, col), (total, count) in buckets[size].items():
                mean = total / count
                means.append(mean)
                feat = {
                    "type": "Feature",
                    "properties": {
                        "cell_id": f"{size}_{row}_{col}",
                        "dist_train_mean": round(mean, 3),
                        "building_count": count,
                    },
                    "geometry": cell_polygon(row, col, dlat, dlon),
                }
                out.write(json.dumps(feat, separators=(",", ":")))
                out.write("\n")

        means.sort()
        n = len(means)

        def pct(p):
            idx = min(n - 1, int(p * (n - 1)))
            return means[idx]

        stats[f"grid{size}"] = {
            "cell_size_m": size,
            "cell_count": n,
            "dist_train_mean_min": means[0],
            "dist_train_mean_max": means[-1],
            "quantiles": {
                f"p{int(p * 100)}": pct(p)
                for p in (0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0)
            },
        }
        print(f"grid{size}: {n} cells -> {fname}")

    with open("grid_agg_stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
