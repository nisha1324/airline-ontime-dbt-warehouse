"""The committed snapshot is intact and the snapshot writer is deterministic."""
import gzip
import hashlib
import json

import pytest

from scripts import download_data as dl


def test_committed_snapshot_matches_manifest():
    manifest = dl.verify()
    raw = gzip.decompress((dl.ROOT / manifest["snapshot"]).read_bytes())
    assert hashlib.sha256(raw).hexdigest() == manifest["csv_sha256"]
    assert len(raw) == manifest["csv_bytes"]
    assert dl.describe(raw) == {
        "rows": manifest["rows"],
        "first_month": manifest["first_month"],
        "last_month": manifest["last_month"],
    }


def test_gzip_is_deterministic_and_lossless():
    raw = b"Route,Airline\nA-B,X\n" * 1000
    first, second = dl.gzip_bytes(raw), dl.gzip_bytes(raw)
    assert first == second
    assert gzip.decompress(first) == raw


def test_committed_gzip_is_what_the_writer_produces():
    # So --update on an unchanged file never creates a spurious diff.
    manifest = json.loads(dl.MANIFEST.read_text())
    stored = (dl.ROOT / manifest["snapshot"]).read_bytes()
    assert dl.gzip_bytes(gzip.decompress(stored)) == stored


def test_unexpected_header_is_rejected():
    raw = ",".join(dl.EXPECTED_HEADER[:-1] + ["Month_Number"]).encode() + b"\n"
    with pytest.raises(SystemExit, match="Unexpected header"):
        dl.describe(raw)
