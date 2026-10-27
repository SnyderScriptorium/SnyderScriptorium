#!/usr/bin/env python3
"""Safe SEO/crawlability health check for Snyder Scriptorium.

This script is intentionally read-only: it never edits application files,
inventory, database records, or Git history. It verifies that Google's
discovery endpoints are reachable and that important public pages remain
indexable.
"""
import os
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

import requests

BASE = os.environ.get("SEO_BASE_URL", "https://www.snyderscriptorium.com").rstrip("/")
CHECK_URLS = ("/", "/about", "/blog", "/store", "/contact", "/find-us")
TIMEOUT = 20
UA = "SnyderScriptorium-SEO-HealthCheck/1.0"


def fail(message):
    print(f"ERROR: {message}")
    return False


def get(path):
    url = path if path.startswith("http") else urljoin(BASE + "/", path.lstrip("/"))
    return requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})


def check_endpoint(path):
    try:
        response = get(path)
    except requests.RequestException as exc:
        return fail(f"{path}: request failed: {exc}")
    if response.status_code != 200:
        return fail(f"{path}: HTTP {response.status_code}")
    return True


def check_sitemap(path):
    try:
        response = get(path)
    except requests.RequestException as exc:
        return fail(f"{path}: request failed: {exc}")
    if response.status_code != 200:
        return fail(f"{path}: HTTP {response.status_code}")
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        return fail(f"{path}: invalid XML: {exc}")

    urls = [loc.text.strip() for loc in root.findall(".//{*}loc") if loc.text and loc.text.strip()]
    if not urls:
        return fail(f"{path}: contains no URLs")

    bad_hosts = [u for u in urls if not (u == BASE or u.startswith(BASE + "/"))]
    if bad_hosts:
        return fail(f"{path}: contains URL outside {BASE}: {bad_hosts[0]}")

    print(f"OK: {path} ({len(urls)} URLs)")
    return True


def check_page(path):
    try:
        response = get(path)
    except requests.RequestException as exc:
        return fail(f"{path}: request failed: {exc}")
    if response.status_code != 200:
        return fail(f"{path}: HTTP {response.status_code}")

    html = response.text.lower()
    if '<meta name="robots" content="noindex' in html:
        return fail(f"{path}: contains a noindex robots directive")
    if '<link rel="canonical"' not in html:
        return fail(f"{path}: missing canonical link")

    print(f"OK: {path} (HTTP 200, indexable, canonical present)")
    return True


def main():
    ok = True
    print(f"Checking Snyder Scriptorium SEO endpoints at {BASE}")

    ok &= check_endpoint("/robots.txt")
    ok &= check_sitemap("/sitemap.xml")
    ok &= check_sitemap("/sitemap-blog.xml")

    for path in CHECK_URLS:
        ok &= check_page(path)

    if ok:
        print("SEO health check passed. No files or site data were modified.")
        return 0

    print("SEO health check FAILED. No files or site data were modified.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
