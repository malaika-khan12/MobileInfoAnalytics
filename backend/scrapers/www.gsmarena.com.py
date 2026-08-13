"""
scrapers/www.gsmarena.com.py

Single-page scraper for GSMArena phone spec pages
(e.g. https://www.gsmarena.com/xiaomi_redmi_note_14_4g_(global)-13616.php).

Per backend/scrapers/README.md: this file holds exactly one class,
GsmarenaScraper, whose only job is "given the HTML of a single product
page, extract the phone's specs" -- nothing about navigating there,
nothing about IP rotation. That's navigation_to_page/www.gsmarena.com.py's
job; this file never touches the network on its own except in the
__main__ test harness below.

Public surface (the "header" other files import):
    GsmarenaScraper(html, source_url=None)
    GsmarenaScraper.scrape() -> dict
        Raw spec dump: {"name": ..., "specs": {category: {label: value}},
        "colors": [...], "models": [...], "price_hl": "...", "source_url": ...}
        Nothing here is guessed or reshaped -- it's a faithful transcription
        of GSMArena's table, useful even for fields template.json doesn't
        have a slot for yet.
    GsmarenaScraper.to_template(raw=None) -> dict
        Reshapes the raw dump into filestorage/template.json's exact
        shape, ready to json.dump() to filestorage/mobiles/gsmarena__<slug>.json.

Standalone test (does NOT use Playwright -- just plain requests, since
this file owns no browser):
    python scrapers/www.gsmarena.com.py "https://www.gsmarena.com/xiaomi_redmi_note_14_4g_(global)-13616.php"
    python scrapers/www.gsmarena.com.py --file saved_page.html --raw
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

from bs4 import BeautifulSoup

SpecValue = Union[str, None]


class GsmarenaScraper:
    """Scrapes a single GSMArena product page's spec table.

    GSMArena wraps each spec category in its own <table> inside
    #specs-list. The category name lives in a <th rowspan=N> that's
    only present on the first <tr> of that table. Most rows have a
    <td class="ttl"> label + <td class="nfo"> value pair; a few rows
    (body protection, memory technology) have an empty/"&nbsp;" ttl and
    rely on the nfo's data-spec attribute as the only identifier -- we
    fall back to that so those rows aren't silently dropped.
    """

    SPEC_LIST_SELECTOR = "#specs-list table"

    def __init__(self, html: str, source_url: Optional[str] = None):
        self.soup = BeautifulSoup(html, "html.parser")
        self.source_url = source_url

    # ------------------------------------------------------------------
    # Stage 1: raw extraction
    # ------------------------------------------------------------------

    def scrape(self) -> dict:
        raw: Dict[str, Dict[str, SpecValue]] = {}

        for table in self.soup.select(self.SPEC_LIST_SELECTOR):
            rows = table.select("tr")
            if not rows:
                continue

            th = rows[0].find("th")
            category = th.get_text(strip=True) if th else None
            if not category:
                continue

            bucket = raw.setdefault(category, {})
            for row in rows:
                nfo = row.select_one("td.nfo")
                if nfo is None:
                    continue
                ttl = row.select_one("td.ttl")
                label = ttl.get_text(strip=True) if ttl else ""
                # Empty label ("&nbsp;" rows, e.g. body protection /
                # memory tech) -> fall back to the nfo's data-spec id
                # instead of dropping the row.
                key = label or nfo.get("data-spec") or f"_unlabeled_{len(bucket)}"
                bucket[key] = self._clean_cell(nfo)

        return {
            "name": self._extract_name(),
            "specs": raw,
            "colors": self._split_list(raw.get("Misc", {}).get("Colors"), r"\s*,\s*"),
            "models": self._split_list(raw.get("Misc", {}).get("Models"), r"\s*,\s*"),
            "price_hl": raw.get("Misc", {}).get("Price"),
            "source_url": self.source_url,
        }

    def _clean_cell(self, cell) -> str:
        # Multi-value cells (e.g. multiple camera modules) are separated
        # by <hr class="line"> -- turn those into a clear delimiter
        # instead of letting get_text() glue everything together.
        for hr in cell.select("hr.line"):
            hr.replace_with(" | ")
        text = cell.get_text(separator=" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()

    def _extract_name(self) -> Optional[str]:
        h1 = self.soup.select_one("h1.specs-phone-name-title, h1[data-spec='modelname']")
        return h1.get_text(strip=True) if h1 else None

    @staticmethod
    def _split_list(value: Optional[str], sep_pattern: str) -> List[str]:
        if not value:
            return []
        return [p.strip() for p in re.split(sep_pattern, value) if p.strip()]

    # ------------------------------------------------------------------
    # Stage 2: reshape into filestorage/template.json's exact schema
    # ------------------------------------------------------------------

    @staticmethod
    def _yes_no_to_bit(value: Optional[str]) -> int:
        if not value:
            return 0
        return 0 if value.strip().lower().startswith("no") else 1

    @staticmethod
    def _parse_prices(price_str: Optional[str]) -> List[float]:
        """'$ 155.00 / € 206.80 / £ 129.99' -> [155.0, 206.8, 129.99].
        Currencies that aren't present are simply omitted -- this never
        pads with a fake 0, since a 0 PKR price would be misleading
        downstream."""
        if not price_str:
            return []
        numbers = re.findall(r"[\d,]+\.?\d*", price_str)
        return [float(n.replace(",", "")) for n in numbers]

    def to_template(self, raw: Optional[dict] = None) -> dict:
        if raw is None:
            raw = self.scrape()
        specs = raw.get("specs", {})

        network = specs.get("Network", {})
        launch = specs.get("Launch", {})
        body = specs.get("Body", {})
        display = specs.get("Display", {})
        platform = specs.get("Platform", {})
        memory = specs.get("Memory", {})
        main_cam = specs.get("Main Camera", {})
        selfie_cam = specs.get("Selfie camera", {})
        sound = specs.get("Sound", {})
        comms = specs.get("Comms", {})
        features = specs.get("Features", {})
        battery = specs.get("Battery", {})
        misc = specs.get("Misc", {})
        eu_label = specs.get("EU LABEL", {})

        nettech = network.get("Technology", "") or ""
        fingerprint = (features.get("Sensors") or "").lower()
        charging = battery.get("Charging") or ""

        main_cam_spec = (
            main_cam.get("Quad") or main_cam.get("Triple")
            or main_cam.get("Dual") or main_cam.get("Single") or ""
        )
        selfie_cam_spec = selfie_cam.get("Dual") or selfie_cam.get("Single") or ""

        return {
            "MobileName": raw.get("name"),
            "Network": {
                "2G": 1 if "GSM" in nettech else 0,
                "3G": 1 if "HSPA" in nettech or "UMTS" in nettech else 0,
                "4G": 1 if "LTE" in nettech else 0,
                "5G": 1 if "5G" in nettech else 0,
            },
            "Launch": {
                "Announced": launch.get("Announced"),
                "Status": launch.get("Status"),
            },
            "Body": {
                "Dimensions": body.get("Dimensions"),
                "Weight": body.get("Weight"),
                "Build": body.get("Build"),
                "SIM": body.get("SIM"),
                "Protection": body.get("bodyother"),
            },
            "Display": {
                "Type": display.get("Type"),
                "Size": display.get("Size"),
                "Resolution": display.get("Resolution"),
                "Protection": display.get("Protection"),
            },
            "Platform": {
                "OS": platform.get("OS"),
                "Chipset": platform.get("Chipset"),
                "CPU": platform.get("CPU"),
                "GPU": platform.get("GPU"),
            },
            "Memory": {
                "Card slot": memory.get("Card slot"),
                "Types": self._split_list(memory.get("Internal"), r"\s*,\s*"),
                "Technology": memory.get("memoryother"),
            },
            "Main Camera": {
                "Specifications": self._split_list(main_cam_spec, r"\s*\|\s*"),
                "Features": main_cam.get("Features"),
                "Video": self._split_list(main_cam.get("Video"), r"\s*,\s*|(?<=\d)@|\s*\|\s*"),
            },
            "Selfie Camera": {
                "Specifications": self._split_list(selfie_cam_spec, r"\s*\|\s*"),
                "Video": self._split_list(selfie_cam.get("Video"), r"\s*,\s*"),
            },
            "Sound": {
                "Loudspeaker": sound.get("Loudspeaker"),
                "3.5mm jack": self._yes_no_to_bit(sound.get("3.5mm jack")),
            },
            "Features": {
                "WLAN": comms.get("WLAN"),
                "Bluetooth": comms.get("Bluetooth"),
                "Positioning": comms.get("Positioning"),
                "NFC": self._yes_no_to_bit(comms.get("NFC")),
                "Infrared port": self._yes_no_to_bit(comms.get("Infrared port")),
                "Radio": self._yes_no_to_bit(comms.get("Radio")),
                "USB": comms.get("USB"),
                "BackFingerPrint": 1 if "back" in fingerprint and "under display" not in fingerprint else 0,
                "SideFingerPrint": 1 if "side" in fingerprint else 0,
                "InDisplayFingerPrint": 1 if "under display" in fingerprint else 0,
                "Sensors": features.get("Sensors"),
            },
            "Battery": {
                "Capacity": battery.get("Type"),
                "WirelessCharging": 1 if "wireless" in charging.lower() else 0,
                "Charging": self._split_list(charging, r"\s*,\s*"),
            },
            "Colors": raw.get("colors", []),
            "Weight": eu_label.get("SAR") or misc.get("SAR EU"),
            "Price": self._parse_prices(raw.get("price_hl")),
        }


if __name__ == "__main__":
    import argparse
    import requests

    parser = argparse.ArgumentParser(description="Standalone test: scrape a single GSMArena product page.")
    parser.add_argument("url", nargs="?", help="GSMArena product URL.")
    parser.add_argument("--file", help="Path to a locally saved HTML file, for testing without hitting the network.")
    parser.add_argument("--raw", action="store_true", help="Print the raw {category: {label: value}} dump instead of the template-shaped output.")
    args = parser.parse_args()

    if args.file:
        page_html = Path(args.file).read_text(encoding="utf-8")
        source = args.file
    elif args.url:
        resp = requests.get(
            args.url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            },
            timeout=15,
        )
        resp.raise_for_status()
        page_html = resp.text
        source = args.url
    else:
        parser.error("Provide a URL or --file")

    scraper = GsmarenaScraper(page_html, source_url=source)
    raw_result = scraper.scrape()
    output = raw_result if args.raw else scraper.to_template(raw_result)
    print(json.dumps(output, indent=2, ensure_ascii=False))
