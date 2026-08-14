"""Parse one already-loaded WhatMobile product page into template.json's schema."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


class WhatmobileScraper:
    """HTML-only scraper for WhatMobile's server-rendered ``table.specs``."""

    def __init__(self, html: str, source_url: Optional[str] = None) -> None:
        self.soup = BeautifulSoup(html, "html.parser")
        self.source_url = source_url

    @staticmethod
    def _text(node) -> str:
        return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()

    @staticmethod
    def _bits(value: Optional[str]) -> int:
        return int(bool(value and not value.strip().lower().startswith("no")))

    @staticmethod
    def _list(value: Optional[str], pattern: str = r"\s*,\s*") -> List[str]:
        return [item.strip() for item in re.split(pattern, value or "") if item.strip()]

    @staticmethod
    def _prices(value: Optional[str]) -> List[float]:
        return [float(item.replace(",", "")) for item in re.findall(r"\d[\d,]*", value or "")]

    def scrape(self) -> dict:
        table = self.soup.select_one("table.specs")
        specs: Dict[str, str] = {}
        if table:
            current_group = ""
            for row in table.select("tr"):
                cells = [self._text(cell) for cell in row.find_all(["th", "td"], recursive=False)]
                if len(cells) >= 3:
                    current_group, label, value = cells[0], cells[1], " ".join(cells[2:])
                elif len(cells) == 2:
                    label, value = cells
                else:
                    continue
                key = f"{current_group}:{label}" if current_group else label
                specs[key] = value
                specs.setdefault(label, value)

        name_node = self.soup.select_one("h1.hdng3, h1")
        # The price label and amount are separate text nodes on live pages, so
        # extract the labelled PKR value from the rendered page text rather
        # than relying on an adjacent DOM sibling.
        page_text = self._text(self.soup)
        price_match = re.search(r"Price\s+in\s+Rs\s*:\s*([\d,]+)", page_text, re.I)
        price_text = price_match.group(1) if price_match else ""
        return {"name": self._text(name_node) if name_node else None, "specs": specs,
                "price_text": price_text, "source_url": self.source_url}

    def to_template(self, raw: Optional[dict] = None) -> dict:
        raw = raw or self.scrape()
        s = raw["specs"]
        get = lambda *keys: next((s[key] for key in keys if s.get(key)), None)
        frequency = " ".join(filter(None, [get("Frequency:2G Band"), get("Frequency:3G Band"), get("Frequency:4G Band"), get("Frequency:5G Band"), get("Data")]))
        sensors = get("Features:Sensors")
        fingerprint = (sensors or "").lower()
        charging = get("Battery:", "Battery:Charging", "Battery")
        camera_main = get("Camera:Main")
        camera_features = get("Camera:Features")
        camera_front = get("Camera:Front")
        colors = self._list(get("Colors"))
        return {
            "MobileName": raw["name"],
            "Network": {"2G": self._bits(get("Frequency:2G Band") or ("GSM" if "GSM" in frequency else None)),
                        "3G": self._bits(get("Frequency:3G Band") or ("HSPA" if "HSPA" in frequency else None)),
                        "4G": self._bits(get("Frequency:4G Band") or ("LTE" if "LTE" in frequency else None)),
                        "5G": self._bits(get("Frequency:5G Band") or ("5G" if "5G" in frequency else None))},
            "Launch": {"Announced": None, "Status": None},
            "Body": {"Dimensions": get("Dimensions"), "Weight": get("Weight"), "Build": get("Extra"), "SIM": get("SIM"), "Protection": get("Extra")},
            "Display": {"Type": get("Display:Technology"), "Size": get("Display:Size"), "Resolution": get("Display:Resolution"), "Protection": get("Display:Protection")},
            "Platform": {"OS": get("Build:OS", "OS"), "Chipset": get("Processor:Chipset", "Chipset"), "CPU": get("Processor:CPU", "CPU"), "GPU": get("Processor:GPU", "GPU")},
            "Memory": {"Card slot": get("Memory:Card", "Card"), "Types": self._list(get("Memory:Built-in", "Built-in")), "Technology": get("Memory:Built-in", "Built-in")},
            "Main Camera": {"Specifications": self._list(camera_main, r"\s+\+\s+"), "Features": camera_features, "Video": self._list(camera_features, r".*?[Vv]ideo\s*\(|\)")},
            "Selfie Camera": {"Specifications": self._list(camera_front, r"\s*,\s*[Vv]ideo.*$"), "Video": self._list(camera_front, r".*?[Vv]ideo\s*\(|\)")},
            "Sound": {"Loudspeaker": get("Audio"), "3.5mm jack": self._bits("Yes" if "3.5" in (get("Audio") or "") else None)},
            "Features": {"WLAN": get("Connectivity:WLAN", "WLAN"), "Bluetooth": get("Bluetooth"), "Positioning": get("GPS"), "NFC": self._bits(get("NFC")), "Infrared port": self._bits(get("Infrared")), "Radio": self._bits(get("Radio")), "USB": get("USB"), "BackFingerPrint": int("back" in fingerprint), "SideFingerPrint": int("side" in fingerprint), "InDisplayFingerPrint": int("under display" in fingerprint), "Sensors": sensors},
            "Battery": {"Capacity": get("Battery:Capacity", "Capacity"), "WirelessCharging": int("wireless" in (charging or "").lower()), "Charging": self._list(charging)},
            "Colors": colors, "Weight": None, "Price": self._prices(raw["price_text"]),
        }
