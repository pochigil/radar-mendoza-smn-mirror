#!/usr/bin/env python3
"""Copy the SMN CAP feeds and files into a folder served by GitHub Pages.

The Radar Mendoza API runs on Cloudflare Workers, and the SMN rate limit
(180 XML requests per 10 minutes per IP) is always used up on the IP that
Workers share, so the Worker reads this copy instead. This script does no
parsing beyond finding the file links: the Worker parses everything.

Layout of the site folder:
  feeds/index.xml        copy of https://ssl.smn.gob.ar/CAP/AR.php
  feeds/short-term.xml   copy of the short-term warnings RSS
  files/<host>/<path>    one copy per CAP file listed in the feeds
  status.json            when each feed was last copied successfully

A feed copy is only replaced by a good RSS body, so an error page never
overwrites it. A file the SMN answers 404 for is written empty, so the
Worker gives up on it instead of waiting forever.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SITE = sys.argv[1] if len(sys.argv) > 1 else "site"
FEEDS = {
    "index": ("https://ssl.smn.gob.ar/CAP/AR.php", "feeds/index.xml"),
    "short_term": ("https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml", "feeds/short-term.xml"),
}
# Stay well under 180 requests per 10 minutes, with runs every 5 minutes.
MAX_FILES = 120
UA = "radar-mendoza-smn-mirror (+https://github.com/pochigil/radar-mendoza-smn-mirror)"
LINK = re.compile(rb"https?://(?:[a-z0-9-]+\.)*smn\.gob\.ar/[^\s<>\"']+?\.xml")
CAP = re.compile(rb"<(?:[\w-]+:)?alert[\s>]")
# File names reused across issues (heat waves): copy them again every run.
REUSED = "/oladecalor/"
# After this many failed runs in a row, write an empty file so the Worker gives
# up on it instead of waiting (seen: forms.smn.gob.ar answering 522 for hours).
MAX_FAILURES = 3


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # network error, timeout
        return 0, str(e).encode()


def write(rel, body):
    path = os.path.join(SITE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, path)


def file_rel(url):
    u = urllib.parse.urlsplit(url)
    return "files/" + u.hostname + u.path


ITEM = re.compile(rb"<item[\s>]", re.I)


def items_sha1(body):
    """SHA-1 of a feed from its first <item> on. The channel header's dates
    change on every SMN build; the items only when the alerts do. The Worker
    reads this from status.json to skip downloading feeds that didn't change,
    and computes the same hash on what it downloads (src/refresh.ts)."""
    m = ITEM.search(body)
    return hashlib.sha1(body[m.start():] if m else b"").hexdigest()


def main():
    status_path = os.path.join(SITE, "status.json")
    try:
        with open(status_path) as f:
            status = json.load(f)
    except (OSError, ValueError):
        status = {}
    status.setdefault("feeds", {})
    failures = status.setdefault("failures", {})

    links = []
    feed_ok = {}
    for name, (url, rel) in FEEDS.items():
        code, body = get(url)
        ok = code == 200 and b"<rss" in body and b"<channel" in body
        feed_ok[name] = ok
        entry = status["feeds"].setdefault(name, {})
        entry["status"] = code
        if ok:
            write(rel, body)
            entry["ok"] = now_iso()
            entry["items_sha1"] = items_sha1(body)
        else:
            print(f"feed {name}: HTTP {code} {body[:80]!r}")
        try:
            with open(os.path.join(SITE, rel), "rb") as f:
                links += [m.decode() for m in LINK.findall(f.read())]
        except OSError:
            pass

    # Short-term warnings first, so a big run of alert files never delays them.
    wanted = list(dict.fromkeys(links))
    wanted.sort(key=lambda u: 0 if "/avisocortoplazo/" in u else 1)
    keep = {file_rel(u) for u in wanted}

    copied = failed = 0
    limited = False
    todo = [u for u in wanted if REUSED in u or not os.path.exists(os.path.join(SITE, file_rel(u)))]
    for url in todo[:MAX_FILES]:
        code, body = get(url)
        rel = file_rel(url)
        if code == 200 and CAP.search(body):
            write(rel, body)
            failures.pop(url, None)
            copied += 1
        elif code in (404, 410):
            write(rel, b"")
            failures.pop(url, None)
            copied += 1
        elif code == 429:
            print(f"rate limited: {body[:80]!r}")
            limited = True
            break
        else:
            failed += 1
            failures[url] = failures.get(url, 0) + 1
            print(f"file {url}: HTTP {code} (failure {failures[url]})")
            # A reused file keeps its last good copy; a new one is given up as empty.
            if failures[url] >= MAX_FAILURES and not os.path.exists(os.path.join(SITE, rel)):
                write(rel, b"")
                copied += 1
        time.sleep(0.1)

    # Forget files the SMN no longer lists, only when the index answered.
    removed = 0
    if feed_ok["index"]:
        root = os.path.join(SITE, "files")
        for dirpath, _, names in os.walk(root):
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), SITE).replace(os.sep, "/")
                if rel not in keep:
                    os.remove(os.path.join(dirpath, n))
                    removed += 1

    for url in [u for u in failures if file_rel(u) not in keep]:
        del failures[url]
    status["updated"] = now_iso()
    status["backlog"] = len(todo) - copied
    write("status.json", json.dumps(status, indent=1).encode())
    write(".nojekyll", b"")
    write("index.html", (
        "<!doctype html><meta charset=utf-8><title>SMN CAP mirror</title>"
        "<p>Copy of the CAP alert feeds of the Servicio Meteorol&oacute;gico Nacional (SMN), "
        "used by the Radar Mendoza API. Data: SMN, "
        "<a href='https://creativecommons.org/licenses/by/4.0/'>CC BY 4.0</a>. "
        "Source: <a href='https://www.smn.gob.ar/'>smn.gob.ar</a>.</p>"
    ).encode())

    changed = copied > 0 or removed > 0 or failed > 0  # failure counts must persist too
    print(json.dumps({"feeds": feed_ok, "listed": len(wanted), "copied": copied,
                      "failed": failed, "removed": removed, "backlog": status["backlog"],
                      "rate_limited": limited}))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
