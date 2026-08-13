"""
One-time download of Cook County GIS's Address Points layer (ArcGIS
FeatureServer -- one point per legal address in the county, incl. house
number/street/unit), filtered to Chicago, for the building-address join in
prep_buildings.py. Saves a local CSV cache so that join can run offline and
repeatably rather than re-downloading every time.

Source: https://gis.cookcountyil.gov/traditional/rest/services/addressZipCode/MapServer/0
(field CMPADDABRV is a pre-formatted "1763 W WELLINGTON AVE" style string).
"""
import csv
import json
import time
import urllib.request

BASE = "https://gis.cookcountyil.gov/traditional/rest/services/addressZipCode/MapServer/0/query"
PAGE_SIZE = 2000
OUT = "chicago_address_points.csv"


def fetch_page(offset):
    params = (
        "where=geocode_muni%3D%27CHICAGO%27"
        "&outFields=CMPADDABRV"
        "&returnGeometry=true&outSR=4326"
        f"&resultOffset={offset}&resultRecordCount={PAGE_SIZE}"
        "&f=json"
    )
    url = f"{BASE}?{params}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.load(resp)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  retry after error: {e}", flush=True)
            time.sleep(2)


def main():
    offset = 0
    n = 0
    with open(OUT, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["lon", "lat", "address"])
        while True:
            data = fetch_page(offset)
            feats = data.get("features", [])
            if not feats:
                break
            for feat in feats:
                addr = feat["attributes"].get("CMPADDABRV")
                geom = feat.get("geometry")
                if not addr or not geom:
                    continue
                writer.writerow([geom["x"], geom["y"], addr])
            n += len(feats)
            print(f"  ...{n} address points fetched", flush=True)
            if len(feats) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    print(f"done: {n} rows -> {OUT}")


if __name__ == "__main__":
    main()
