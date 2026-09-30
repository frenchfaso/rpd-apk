#!/usr/bin/env python3
"""Seed one byte-identical official distfile; normal abuild checks still follow."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

NAME = "copium-152.0.tar.gz"
URL = "https://distfiles.alpinelinux.org/distfiles/edge/" + NAME
ORIGINAL_URL = "https://codeberg.org/selfisekai/copium/archive/152.0.tar.gz"
SIZE = 20697
SHA512 = "6bdfb803ec024224db07ae46eeb0df6ccdd86603d48b6166bfdd5c03df60bf05e680c05ee0e1638663ef943600d9e5658aadc2313483053783c8381a8244f326"
RECIPE_SHA256 = "ab527886ba48da8bbfb3bbd789e776a53153fc37f3b30588e2bd53ef297931db"


def validate_file(path, expected_size=SIZE, expected_hash=SHA512):
    if path.stat().st_size != expected_size:
        raise ValueError("Copium archive size differs from pinned original artifact")
    data = path.read_bytes()
    actual = hashlib.sha512(data).hexdigest()
    if len(data) != expected_size or actual != expected_hash:
        raise ValueError("Copium archive SHA512 differs from original recipe")
    return {"size_bytes": len(data), "sha512": actual}


def seed(recipe, sources, review):
    report = {"status": "UNPROVEN", "archive": NAME, "cache_url": URL,
              "original_recipe_url": ORIGINAL_URL, "expected_size_bytes": SIZE,
              "expected_sha512": SHA512, "recipe_sha256": RECIPE_SHA256,
              "normal_abuild_fetch_verify_required": True, "archive_unpacked": False}
    review.mkdir(parents=True, exist_ok=True)
    report_path = review / "copium-prefetch.json"
    temporary = None
    try:
        recipe_bytes = recipe.read_bytes()
        if hashlib.sha256(recipe_bytes).hexdigest() != RECIPE_SHA256:
            raise ValueError("Copium preseed requires the exact reviewed prepared recipe")
        if SHA512 + "  " + NAME not in recipe_bytes.decode():
            raise ValueError("Original Copium recipe checksum missing")
        sources.mkdir(parents=True, exist_ok=True)
        destination = sources / NAME
        if destination.exists():
            report["retrieval"] = "existing SRCDEST file; independently revalidated"
            report.update(validate_file(destination, SIZE, SHA512))
        else:
            report["retrieval"] = "official Alpine distfiles cache; one bounded request"
            with tempfile.NamedTemporaryFile(prefix=".copium-preseed-", dir=sources,
                                             delete=False) as output:
                temporary = Path(output.name)
            command = ["curl", "--fail", "--silent", "--show-error", "--location",
                       "--proto", "=https", "--max-time", "30", "--max-filesize", str(SIZE),
                       "--dump-header", str(review / "copium-prefetch-headers.txt"),
                       "--output", str(temporary), "--write-out",
                       "http_code=%{http_code}\nurl_effective=%{url_effective}\nsize_download=%{size_download}\n",
                       URL]
            result = subprocess.run(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
            (review / "copium-prefetch-curl.log").write_text(result.stdout)
            report["curl_exit_status"] = result.returncode
            if result.returncode:
                raise ValueError("Official Copium cache fetch failed; no archive seeded")
            if "http_code=200\n" not in result.stdout or "url_effective=" + URL + "\n" not in result.stdout:
                raise ValueError("Official Copium cache response URL/status differs")
            report.update(validate_file(temporary, SIZE, SHA512))
            # Publish complete verified bytes without replacing an existing file.
            os.link(temporary, destination)
        report["status"] = "PASS"
    except Exception as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("sources", type=Path)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()
    seed(args.recipe, args.sources, args.review)
