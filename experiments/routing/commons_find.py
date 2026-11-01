"""Find candidate files for the routing set on Wikimedia Commons.

    python -I experiments/routing/commons_find.py search "fracture surface" "engineering drawing"
    python -I experiments/routing/commons_find.py category "Category:Fractography"

Prints one line per JPEG or PNG file that is large enough to use: title, width, height, size in
KB, licence, and the camera make and model from its EXIF data. The files in data/commons.json
were picked by hand from this output.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia asks every client to name itself and give a contact
USER_AGENT = {"User-Agent": "resourcly-routing-research/0.1 (prtkvptl@gmail.com)"}
FILE_INFO = {
    "prop": "imageinfo",
    "iiprop": "url|size|mime|extmetadata|metadata",
    "iiextmetadatafilter": "LicenseShortName",
}


def query(params: dict) -> list[dict]:
    """The pages a Commons API query returns, each with its image info."""
    url = API + "?" + urllib.parse.urlencode({"action": "query", "format": "json", **params})
    request = urllib.request.Request(url, headers=USER_AGENT)
    reply = json.load(urllib.request.urlopen(request, timeout=30))
    return list(reply.get("query", {}).get("pages", {}).values())


def describe(page: dict, mimes: tuple[str, ...], min_width: int) -> tuple | None:
    info = page["imageinfo"][0]
    if info["mime"] not in mimes or info["width"] < min_width:
        return None
    exif = {m["name"]: m["value"] for m in (info.get("metadata") or []) if isinstance(m, dict)}
    licence = info.get("extmetadata", {}).get("LicenseShortName", {}).get("value")
    size_kb = info["size"] // 1024
    return (
        page["title"][:90],
        info["width"],
        info["height"],
        size_kb,
        licence,
        exif.get("Make"),
        exif.get("Model"),
    )


def search(text: str) -> list[tuple]:
    """JPEG photos of 800 pixels or wider whose title or description matches the text."""
    params = {"generator": "search", "gsrnamespace": 6, "gsrsearch": text, "gsrlimit": 20}
    pages = query({**params, **FILE_INFO})
    return [d for p in pages if (d := describe(p, ("image/jpeg",), 800))]


def category(title: str) -> list[tuple]:
    """JPEG and PNG files of 600 pixels or wider in one Commons category."""
    params = {"generator": "categorymembers", "gcmtitle": title, "gcmtype": "file", "gcmlimit": 60}
    pages = query({**params, **FILE_INFO})
    return [d for p in pages if (d := describe(p, ("image/jpeg", "image/png"), 600))]


def main(mode: str, terms: list[str]) -> None:
    find = {"search": search, "category": category}[mode]
    for term in terms:
        print("##", term)
        for row in find(term):
            print("  ", row)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
