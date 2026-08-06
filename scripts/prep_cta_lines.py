"""
Reproject nb2_cta_lines_updated.geojson (EPSG:26971, same as coded_bldgs.geojson)
to EPSG:4326 for the map, and decode each segment's cryptic "groups" code (e.g.
"bropurred_eag_north_5") into a readable list of CTA line names.

Small dataset (23 features) so unlike the buildings, this is served directly as
a plain GeoJSON source -- no tiling needed.
"""
import json

import pyproj

SRC = "nb2_cta_lines_updated.geojson"
DST = "cta_lines_4326.geojson"
SRC_CRS = "EPSG:26971"

SEGMENT_TYPE_LABELS = {
    "eag": "Elevated",
    "hwy": "Highway median",
    "subway": "Subway",
}

# The "groups" prefix concatenates the abbreviations of every CTA line that
# runs on that segment (several lines share trackage downtown and on a few
# trunk lines). Abbreviation length isn't consistent across rows (e.g. Brown
# is "br" in some groups, "bro" in others), so rather than guess a parsing
# rule, every prefix actually present in the source data is mapped by hand
# here -- verified by matching each prefix's letter count against its
# expected line-name combination.
GROUP_LINES = {
    "bl": ["Blue"],
    "br": ["Brown"],
    "brgrorpipu": ["Brown", "Green", "Orange", "Pink", "Purple"],
    "bropur": ["Brown", "Purple"],
    "bropurred": ["Brown", "Purple", "Red"],
    "brorpipu": ["Brown", "Orange", "Pink", "Purple"],
    "gr": ["Green"],
    "gror": ["Green", "Orange"],
    "grpi": ["Green", "Pink"],
    "or": ["Orange"],
    "pi": ["Pink"],
    "pu": ["Purple"],
    "rd": ["Red"],
    "red": ["Red"],
    "redpur": ["Red", "Purple"],
    "yl": ["Yellow"],
}

transformer = pyproj.Transformer.from_crs(SRC_CRS, "EPSG:4326", always_xy=True)


def reproject_coords(coords, depth):
    if depth == 0:
        lon, lat = transformer.transform(coords[0], coords[1])
        return [round(lon, 7), round(lat, 7)]
    return [reproject_coords(c, depth - 1) for c in coords]


def main():
    src = json.load(open(SRC))
    out_features = []

    for feat in src["features"]:
        props = feat["properties"]
        prefix = props["groups"].split("_")[0]
        lines = GROUP_LINES.get(prefix)
        if lines is None:
            raise ValueError(f"Unrecognized groups prefix: {prefix!r}")

        geom = feat["geometry"]
        depth = 2 if geom["type"] == "MultiLineString" else 1
        geom["coordinates"] = reproject_coords(geom["coordinates"], depth)

        out_features.append({
            "type": "Feature",
            "properties": {
                "lines": lines,
                "line_label": "/".join(lines),
                "segment_type": props["segment_type"],
                "segment_type_label": SEGMENT_TYPE_LABELS[props["segment_type"]],
                "avg_daily_trains": round(props["avg_daily_trains"], 1),
            },
            "geometry": geom,
        })

    out = {"type": "FeatureCollection", "features": out_features}
    with open(DST, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"wrote {len(out_features)} features -> {DST}")


if __name__ == "__main__":
    main()
