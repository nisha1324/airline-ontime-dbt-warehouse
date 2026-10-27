"""Fetch the BITRE domestic airline on-time performance file and snapshot it.

Source: Bureau of Infrastructure and Transport Research Economics (BITRE),
"Domestic Airlines - On Time Performance", published on data.gov.au
(https://data.gov.au/data/dataset/domestic-airline-on-time-performance).
Licence: Creative Commons Attribution 3.0 Australia.

data.gov.au replaces the CSV in place every month, so a pinned URL + SHA-256
would stop working at the next release. Instead the warehouse is built from a
snapshot committed as data/snapshots/otp_time_series_web.csv.gz (1.6 MB),
described by data/snapshots/SNAPSHOT.json. The file name never changes, so
dbt always reads the same path; older snapshots live in the git history.
This script:

  python scripts/download_data.py            # verify the committed snapshot
  python scripts/download_data.py --check    # also download the live file and
                                             # say whether BITRE has published
                                             # a newer one
  python scripts/download_data.py --update   # download the live file and make
                                             # it the new snapshot

The gzip is written with a fixed timestamp and no file name, so the same CSV
always gives byte-identical snapshot files.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "snapshots"
MANIFEST = SNAPSHOTS / "SNAPSHOT.json"
RAW = ROOT / "data" / "raw"

DATASET = "domestic-airline-on-time-performance"
API = f"https://data.gov.au/data/api/3/action/package_show?id={DATASET}"
CSV_RESOURCE = "cf663ed1-0c5e-497f-aea9-e74bfda9cf44"
USER_AGENT = "airline-ontime-dbt-warehouse (+https://github.com/nisha1324)"

EXPECTED_HEADER = [
    "Route", "Departing_Port", "Arriving_Port", "Airline", "Month",
    "Sectors_Scheduled", "Sectors_Flown", "Cancellations",
    "Departures_On_Time", "Arrivals_On_Time", "Departures_Delayed",
    "Arrivals_Delayed", "Year", "Month_Num",
]


def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def resource_info() -> dict:
    """The CSV resource's metadata from the data.gov.au CKAN API."""
    package = json.loads(fetch(API, timeout=30))["result"]
    for res in package["resources"]:
        if res["id"] == CSV_RESOURCE:
            return {
                "url": res["url"],
                "last_modified": res.get("last_modified"),
                "licence": package.get("license_title"),
            }
    raise SystemExit(f"CSV resource {CSV_RESOURCE} is no longer listed in {DATASET}")


def describe(raw: bytes) -> dict:
    """Row count and month range, after checking the header is what dbt expects."""
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    header, body = rows[0], rows[1:]
    if header != EXPECTED_HEADER:
        raise SystemExit(f"Unexpected header: {header}")
    months = sorted({(int(r[12]), int(r[13])) for r in body})
    return {
        "rows": len(body),
        "first_month": f"{months[0][0]}-{months[0][1]:02d}",
        "last_month": f"{months[-1][0]}-{months[-1][1]:02d}",
    }


def gzip_bytes(raw: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    return buf.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def verify() -> dict:
    """Check the committed snapshot against its manifest."""
    manifest = load_manifest()
    path = ROOT / manifest["snapshot"]
    raw = gzip.decompress(path.read_bytes())
    if sha256(raw) != manifest["csv_sha256"]:
        raise SystemExit(f"{path.name}: CSV SHA-256 does not match SNAPSHOT.json")
    if describe(raw)["rows"] != manifest["rows"]:
        raise SystemExit(f"{path.name}: row count does not match SNAPSHOT.json")
    print(f"OK  {manifest['snapshot']}: {manifest['rows']:,} rows, "
          f"{manifest['first_month']} to {manifest['last_month']}, "
          f"published {manifest['source_last_modified'][:10]}")
    return manifest


def download() -> tuple[bytes, dict]:
    info = resource_info()
    raw = fetch(info["url"])
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "otp_time_series_web.csv").write_bytes(raw)
    return raw, info


def update(raw: bytes, info: dict) -> None:
    stats = describe(raw)
    name = "otp_time_series_web.csv.gz"
    (SNAPSHOTS / name).write_bytes(gzip_bytes(raw))
    manifest = {
        "snapshot": f"data/snapshots/{name}",
        "source_dataset": f"https://data.gov.au/data/dataset/{DATASET}",
        "source_url": info["url"],
        "source_last_modified": info["last_modified"],
        "licence": info["licence"],
        "attribution": "Bureau of Infrastructure and Transport Research Economics (BITRE)",
        "downloaded": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "csv_bytes": len(raw),
        "csv_sha256": sha256(raw),
        **stats,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"NEW snapshot {name} (published {info['last_modified'][:10]}): "
          f"{stats['rows']:,} rows, {stats['first_month']} to {stats['last_month']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true",
                       help="download the live file and compare it with the snapshot")
    group.add_argument("--update", action="store_true",
                       help="download the live file and make it the new snapshot")
    args = parser.parse_args()

    if args.update and not MANIFEST.exists():
        update(*download())
        return
    manifest = verify()
    if not (args.check or args.update):
        return
    raw, info = download()
    if sha256(raw) == manifest["csv_sha256"]:
        print("Live file is identical to the snapshot.")
    elif args.update:
        update(raw, info)
    else:
        stats = describe(raw)
        print(f"Live file differs (published {info['last_modified'][:10]}, "
              f"{stats['rows']:,} rows to {stats['last_month']}). "
              "Run with --update to snapshot it.")
        sys.exit(2)


if __name__ == "__main__":
    main()
