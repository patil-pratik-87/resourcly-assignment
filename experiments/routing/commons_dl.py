"""Download the 20 Wikimedia Commons files of the routing set and check them against commons.json.

    python -I experiments/routing/commons_dl.py

data/commons.json names each file with its URL, size, SHA-256, licence, author and page. The files
go to data/commons/, which git ignores. A file already there with the right hash is kept, and a
download whose hash differs stops the script, so build_dataset.py always starts from the same
bytes. This is the only step of the routing set that needs the network.
"""

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "data" / "commons.json"
OUT = HERE / "data" / "commons"
# Wikimedia asks every client to name itself and give a contact
USER_AGENT = {"User-Agent": "resourcly-routing-research/0.1 (prtkvptl@gmail.com)"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    changed = []
    for name, entry in manifest.items():
        path = OUT / name
        if path.is_file() and sha256(path.read_bytes()) == entry["sha256"]:
            print(f"ok    {name}")
            continue
        request = urllib.request.Request(entry["url"], headers=USER_AGENT)
        data = urllib.request.urlopen(request, timeout=120).read()
        if sha256(data) != entry["sha256"]:
            changed.append(name)
            print(f"FAIL  {name}: {len(data)} bytes, not the {entry['bytes']} in commons.json")
            continue
        path.write_bytes(data)
        print(f"got   {name} ({len(data) // 1024} KB, {entry['licence']})")
        time.sleep(0.5)  # be gentle with the Commons servers
    if changed:
        print(f"{len(changed)} file(s) changed on Commons since the set was built", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
