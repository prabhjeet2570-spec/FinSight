"""Restore immutable public filing snapshots; always check committed source hashes."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    identity = os.environ.get("EDGAR_USER_AGENT", "")
    if not identity or "@" not in identity:
        sys.exit("Set EDGAR_USER_AGENT to your application name and contact email.")
    manifest = json.loads((root / "data/manifest.json").read_text())
    with httpx.Client(
        headers={"User-Agent": identity}, timeout=30, follow_redirects=False
    ) as client:
        for filing in manifest["filings"]:
            response = client.get(filing["source_url"])
            response.raise_for_status()
            data = response.content
            if hashlib.sha256(data).hexdigest() != filing["sha256"]:
                sys.exit(
                    f"Public bytes changed for {filing['id']}; preserved existing local snapshot."
                )
            (root / "data" / filing["path"]).write_bytes(data)
            print("Verified", filing["id"], flush=True)
            time.sleep(0.25)
