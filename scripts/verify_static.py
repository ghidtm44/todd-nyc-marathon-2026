#!/usr/bin/env python3
"""Verify the public, buildless spectator page and its hard-coded estimates."""
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"script", "input", "select", "button", "textarea", "form", "iframe"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = Counter()
        self.refs = []
        self.ids = set()
        self.rows = []
        self.row = None
        self.images = []
        self.viewport = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags[tag] += 1
        if "id" in attrs:
            assert attrs["id"] not in self.ids, f"Duplicate id: {attrs['id']}"
            self.ids.add(attrs["id"])
        for key, value in attrs.items():
            assert not key.startswith("on"), f"Runtime event handler: {key}"
            if key in {"src", "href"}:
                self.refs.append(value)
                assert not value.lower().startswith("javascript:"), "Javascript URL"
        if tag == "meta" and attrs.get("name") == "viewport":
            self.viewport = "width=device-width" in attrs.get("content", "")
        if tag == "img":
            self.images.append(attrs)
        if tag == "tr" and "data-mile" in attrs:
            assert self.row is None, "Nested estimate rows"
            self.row = {"mile": attrs["data-mile"], "attrs": attrs, "text": [], "times": []}
        if tag == "time" and self.row is not None:
            self.row["times"].append(attrs)

    def handle_endtag(self, tag):
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.row is not None:
            self.row["text"].append(data)


def local_path(reference):
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    path = (ROOT / unquote(parsed.path)).resolve()
    assert path.is_relative_to(ROOT), f"Reference escapes project: {reference}"
    return path


def main():
    html = (ROOT / "index.html").read_text()
    page = Page()
    page.feed(html)
    assert page.viewport, "Missing responsive viewport"
    assert page.tags["h1"] == 1, "Expected one page heading"
    assert not (FORBIDDEN & page.tags.keys()), f"Unexpected runtime/controls: {FORBIDDEN & page.tags.keys()}"
    expected_keys = {str(mile) for mile in range(1, 27)} | {"finish"}
    counts = Counter(row["mile"] for row in page.rows)
    assert set(counts) == expected_keys and all(v == 1 for v in counts.values()), f"Estimate rows: {counts}"
    start = datetime(2026, 11, 1, 10, 55, tzinfo=ZoneInfo("America/New_York"))
    assert start.utcoffset() == timedelta(hours=-5) and start.tzname() == "EST"
    for row in page.rows:
        distance = Decimal(42195) / Decimal("1609.344") if row["mile"] == "finish" else Decimal(row["mile"])
        elapsed = Decimal(562) + (distance - 1) * 530
        seconds = int(elapsed + Decimal("0.5"))
        precise = start + timedelta(seconds=seconds)
        rounded = (start + timedelta(seconds=float(elapsed) + 30)).replace(second=0, microsecond=0)
        clock = rounded.strftime("%I:%M%p").lstrip("0").lower()
        text = re.sub(r"[\s.]", "", "".join(row["text"]).lower())
        assert clock in text, f"Mile {row['mile']}: expected visible {clock}, got {text}"
        assert int(row["attrs"]["data-estimate-seconds"]) == seconds, f"Incorrect elapsed seconds at {row['mile']}"
        assert len(row["times"]) == 1, f"Missing <time> at {row['mile']}"
        actual = datetime.fromisoformat(row["times"][0]["datetime"])
        assert actual == precise and actual.utcoffset() == start.utcoffset(), f"Incorrect EST datetime at {row['mile']}"
    checked = set()
    for ref in page.refs:
        parsed = urlsplit(ref)
        if not parsed.path and parsed.fragment:
            assert parsed.fragment in page.ids, f"Missing fragment: {ref}"
        path = local_path(ref)
        if path is not None:
            assert path.is_file(), f"Missing asset: {ref}"
            checked.add(str(path.relative_to(ROOT)))
    css = (ROOT / "style.css").read_text()
    assert "@import" not in css, "External CSS imports are not expected"
    for ref in re.findall(r"url\(\s*['\"]?([^'\")]+)", css):
        path = local_path(ref)
        assert path is None or path.is_file(), f"Missing CSS asset: {ref}"
    assert len(page.images) == 3, "Expected three map panels"
    for image in page.images:
        assert image.get("alt", "").strip(), f"Missing map alt text: {image}"
        assert local_path(image["src"]) is not None, "Map images must be hosted with the static page"
    report = json.loads((ROOT / "assets/map-build-report.json").read_text())
    assert report["source_sha256"] == hashlib.sha256((ROOT / "source/official-course-2026.pdf").read_bytes()).hexdigest(), "Map source checksum mismatch"
    map_markers = {str(marker["mile"]): marker for marker in report["markers"]}
    assert set(map_markers) == expected_keys | {"start"}, "Map report does not cover all mile markers"
    assert len(report["markers"]) == len(map_markers) == 28, "Map marker entries must be unique"
    assert report["timezone"] == "America/New_York" and report["offset"] == "-0500", "Map timezone mismatch"
    for mile, marker in map_markers.items():
        distance = Decimal(42195) / Decimal("1609.344") if mile == "finish" else Decimal(0 if mile == "start" else mile)
        elapsed = Decimal(0) if mile == "start" else Decimal(562) + (distance - 1) * 530
        precise = start + timedelta(seconds=int(elapsed + Decimal("0.5")))
        expected = precise.strftime("%I:%M:%S %p").lstrip("0")
        assert marker["time"] == expected, f"Map time mismatch at {mile}"
    print("PASS: 26 mile estimates and finish, exact EST datetimes, map/table time consistency, official PDF checksum, 3 map panels, local assets, no scripts/controls.")
    print("Assets checked:", ", ".join(sorted(checked)))


if __name__ == "__main__":
    main()
