"""
MyMobile.pk product-page scraper.

Reads one already-loaded MyMobile.pk product page and converts its
RAW specification table into the project's template.json schema.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


class MymobileScraper:
    """HTML scraper for MyMobile.pk product specification pages."""

    def __init__(
        self,
        html: str,
        source_url: Optional[str] = None,
    ) -> None:
        self.soup = BeautifulSoup(html, "html.parser")
        self.source_url = source_url

    # ==============================================================
    # BASIC HELPERS
    # ==============================================================

    @staticmethod
    def _text(node) -> str:
        if node is None:
            return ""

        return re.sub(
            r"\s+",
            " ",
            node.get_text(" ", strip=True),
        ).strip()

    @staticmethod
    def _bits(value: Optional[str]) -> int:
        if not value:
            return 0

        value = value.strip().lower()

        if value in {
            "no",
            "none",
            "false",
            "not supported",
            "not available",
        }:
            return 0

        if value in {
            "yes",
            "true",
            "supported",
            "available",
        }:
            return 1

        if value.startswith("yes "):
            return 1

        if value.startswith("no "):
            return 0

        # Values such as:
        # Side-mounted
        # Yes with Glonass
        # Fingerprint (under display)
        return 1

    @staticmethod
    def _list(
        value: Optional[str],
        pattern: str = r"\s*,\s*",
    ) -> List[str]:

        if not value:
            return []

        return [
            item.strip()
            for item in re.split(pattern, value)
            if item.strip()
        ]

    @staticmethod
    def _prices(value: Optional[str]) -> List[float]:

        if not value:
            return []

        matches = re.findall(
            r"\d[\d,]*(?:\.\d+)?",
            value,
        )

        return [
            float(item.replace(",", ""))
            for item in matches
        ]

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(
            r"[^a-z0-9]+",
            " ",
            value.lower(),
        ).strip()

    # ==============================================================
    # RAW SPECIFICATION EXTRACTION
    # ==============================================================

    def _collect_specs(self) -> Dict[str, str]:
        """
        Extract MyMobile specification rows.

        Returns both:

            Label -> Value

        and:

            Section:Label -> Value

        Example:

            Size -> 8.0 inches
            Display:Size -> 8.0 inches

            Technology -> 5G, 4G
            Network:Technology -> 5G, 4G
        """

        specs: Dict[str, str] = {}

        current_section = ""

        for table in self.soup.find_all("table"):

            current_section = ""

            for row in table.find_all("tr"):

                cells = row.find_all(
                    ["th", "td"],
                    recursive=False,
                )

                values = [
                    self._text(cell)
                    for cell in cells
                ]

                values = [
                    value
                    for value in values
                    if value
                ]

                if not values:
                    continue

                # --------------------------------------------------
                # Section / group row
                # --------------------------------------------------

                if len(values) == 1:
                    current_section = values[0]
                    continue

                # --------------------------------------------------
                # Typical MyMobile row:
                #
                # Section | Label | Value
                #
                # or:
                #
                # Label | Value
                # --------------------------------------------------

                if len(values) >= 3:
                    possible_section = values[0]
                    label = values[1]
                    value = " ".join(values[2:])

                    if possible_section:
                        current_section = possible_section

                else:
                    label = values[0]
                    value = values[1]

                if not label or not value:
                    continue

                label_key = self._normalize(label)
                section_key = self._normalize(current_section)

                if not label_key:
                    continue

                # Save section-aware version.
                if section_key:
                    grouped_key = f"{section_key}:{label_key}"
                    specs[grouped_key] = value

                # Save plain label.
                #
                # IMPORTANT:
                # setdefault prevents a later ambiguous label from
                # overwriting the first one.
                specs.setdefault(label_key, value)

        return specs

    # ==============================================================
    # SPEC LOOKUP
    # ==============================================================

    def _find_global(
        self,
        specs: Dict[str, str],
        *labels: str,
    ) -> Optional[str]:

        for label in labels:

            key = self._normalize(label)

            value = specs.get(key)

            if value:
                return value

        return None

    def _find_section(
        self,
        specs: Dict[str, str],
        section_names: List[str],
        labels: List[str],
    ) -> Optional[str]:

        normalized_sections = [
            self._normalize(section)
            for section in section_names
        ]

        normalized_labels = [
            self._normalize(label)
            for label in labels
        ]

        for section in normalized_sections:

            for label in normalized_labels:

                key = f"{section}:{label}"

                value = specs.get(key)

                if value:
                    return value

        return None

    def _find(
        self,
        specs: Dict[str, str],
        *,
        sections: Optional[List[str]] = None,
        labels: Optional[List[str]] = None,
        allow_global: bool = True,
    ) -> Optional[str]:

        sections = sections or []
        labels = labels or []

        # First: section-specific lookup.
        if sections:
            value = self._find_section(
                specs,
                sections,
                labels,
            )

            if value is not None:
                return value

        # Second: global lookup only when explicitly allowed.
        if allow_global:
            return self._find_global(
                specs,
                *labels,
            )

        return None

    # ==============================================================
    # PRICE
    # ==============================================================

    def _extract_price(self) -> List[float]:
        """
        Extract MyMobile price.

        Example:

            From Rs. 530,000

        becomes:

            [530000.0]
        """

        page_text = self._text(self.soup)

        patterns = [
            r"From\s+Rs\.?\s*([\d,]+(?:\.\d+)?)",
            r"Price\s*[:\-]?\s*Rs\.?\s*([\d,]+(?:\.\d+)?)",
            r"Rs\.?\s*([\d,]+(?:\.\d+)?)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                page_text,
                re.IGNORECASE,
            )

            if match:

                prices = self._prices(
                    match.group(1)
                )

                if prices:
                    return prices

        return []

    # ==============================================================
    # RAW SCRAPE
    # ==============================================================

    def scrape(self) -> dict:

        specs = self._collect_specs()

        name_node = self.soup.select_one("h1")

        name = (
            self._text(name_node)
            if name_node
            else None
        )

        return {
            "name": name,
            "specs": specs,
            "price_text": self._extract_price(),
            "source_url": self.source_url,
        }

    # ==============================================================
    # TEMPLATE CONVERSION
    # ==============================================================

    def to_template(
        self,
        raw: Optional[dict] = None,
    ) -> dict:

        raw = raw or self.scrape()

        specs: Dict[str, str] = raw.get(
            "specs",
            {},
        )

        # ==========================================================
        # NETWORK
        # ==========================================================

        technology = self._find(
            specs,
            sections=[
                "Network",
                "Connectivity",
                "General",
            ],
            labels=[
                "Technology",
                "Network Technology",
            ],
        )

        bands_2g = self._find_global(
            specs,
            "2G Bands",
        )

        bands_3g = self._find_global(
            specs,
            "3G Bands",
        )

        bands_4g = self._find_global(
            specs,
            "4G Bands",
        )

        bands_5g = self._find_global(
            specs,
            "5G Bands",
        )

        technology_lower = (
            technology or ""
        ).lower()

        network_2g = bool(
            bands_2g
            or re.search(
                r"\b2g\b|\bgsm\b",
                technology_lower,
            )
        )

        network_3g = bool(
            bands_3g
            or re.search(
                r"\b3g\b|\bhspa\b|\bumts\b",
                technology_lower,
            )
        )

        network_4g = bool(
            bands_4g
            or re.search(
                r"\b4g\b|\blte\b",
                technology_lower,
            )
        )

        network_5g = bool(
            bands_5g
            or re.search(
                r"\b5g\b",
                technology_lower,
            )
        )

        # ==========================================================
        # LAUNCH
        # ==========================================================

        announced = self._find_global(
            specs,
            "Announced",
            "Announced Date",
        )

        released = self._find_global(
            specs,
            "Released",
            "Release Date",
        )

        status = self._find_global(
            specs,
            "Status",
        )

        if released and status:
            launch_status = (
                f"{status}. Released {released}"
            )
        elif released:
            launch_status = (
                f"Released {released}"
            )
        else:
            launch_status = status

        # ==========================================================
        # BODY
        # ==========================================================

        dimensions = self._find_global(
            specs,
            "Dimensions",
        )

        body_weight = self._find_global(
            specs,
            "Weight",
        )

        build = self._find_global(
            specs,
            "Build",
        )

        sim = self._find_global(
            specs,
            "SIM",
        )

        protection = self._find_global(
            specs,
            "Protection",
        )

        # ==========================================================
        # DISPLAY
        #
        # IMPORTANT:
        #
        # MyMobile's RAW SPECS:
        #
        # Type = Li-Ion
        # Size = 8.0 inches
        # Resolution = 2076x2160 px
        # Refresh Rate = 120Hz
        #
        # "Type" is BATTERY type.
        #
        # Therefore we NEVER globally use "Type" for Display.
        # ==========================================================

        display_type = self._find(
            specs,
            sections=[
                "Display",
                "Display & Size",
                "Display Details",
            ],
            labels=[
                "Display Type",
            ],
            allow_global=False,
        )

        display_size = self._find(
            specs,
            sections=[
                "Display",
                "Display & Size",
                "Display Details",
            ],
            labels=[
                "Size",
                "Display Size",
            ],
            allow_global=True,
        )

        display_resolution = self._find(
            specs,
            sections=[
                "Display",
                "Display & Size",
                "Display Details",
            ],
            labels=[
                "Resolution",
                "Display Resolution",
            ],
            allow_global=True,
        )

        display_protection = self._find(
            specs,
            sections=[
                "Display",
                "Display & Size",
                "Display Details",
            ],
            labels=[
                "Protection",
                "Display Protection",
            ],
            allow_global=False,
        )

        refresh_rate = self._find_global(
            specs,
            "Refresh Rate",
        )

        # MyMobile currently gives Refresh Rate separately.
        # Template has no Refresh Rate field, so put it into
        # Display.Type when no real Display Type exists.
        if display_type is None:
            display_type = refresh_rate

        # ==========================================================
        # PLATFORM
        # ==========================================================

        os_value = self._find_global(
            specs,
            "Operating System",
            "OS",
        )

        chipset = self._find_global(
            specs,
            "Chipset",
        )

        cpu = self._find_global(
            specs,
            "CPU",
        )

        gpu = self._find_global(
            specs,
            "GPU",
        )

        # ==========================================================
        # MEMORY
        #
        # DO NOT use global "Technology".
        #
        # Otherwise Network Technology:
        #
        #     5G, 4G
        #
        # gets incorrectly placed into Memory.Technology.
        # ==========================================================

        ram = self._find_global(
            specs,
            "RAM",
        )

        storage = self._find_global(
            specs,
            "Storage",
            "Internal Storage",
        )

        card_slot = self._find_global(
            specs,
            "Card Slot",
            "Memory Card",
            "Expandable Storage",
        )

        memory_technology = self._find(
            specs,
            sections=[
                "Memory",
                "Storage",
            ],
            labels=[
                "Technology",
                "Memory Technology",
                "Storage Technology",
            ],
            allow_global=False,
        )

        memory_types: List[str] = []

        if ram and storage:
            memory_types = [
                f"{ram} RAM / {storage}"
            ]

        elif ram:
            memory_types = [ram]

        elif storage:
            memory_types = [storage]

        # ==========================================================
        # MAIN CAMERA
        # ==========================================================

        camera = self._find_global(
            specs,
            "Camera",
            "Main Camera",
            "Rear Camera",
        )

        camera_megapixels = self._find_global(
            specs,
            "Megapixels",
        )

        camera_features = self._find_global(
            specs,
            "Camera Features",
            "Rear Camera Features",
        )

        camera_video = self._find_global(
            specs,
            "Video",
            "Rear Video Recording",
            "Video Recording",
        )

        main_camera_specs: List[str] = []

        if camera:
            main_camera_specs = [
                camera
            ]

        elif camera_megapixels:
            main_camera_specs = [
                camera_megapixels
            ]

        main_camera_video = (
            self._list(camera_video)
            if camera_video
            else []
        )

        # ==========================================================
        # SELFIE CAMERA
        # ==========================================================

        selfie_camera = self._find_global(
            specs,
            "Selfie Camera",
            "Front Camera",
        )

        selfie_features = self._find_global(
            specs,
            "Front Camera Features",
            "Selfie Camera Features",
        )

        selfie_video = self._find_global(
            specs,
            "Front Video Recording",
            "Selfie Video Recording",
        )

        selfie_specs: List[str] = []

        if selfie_camera:
            selfie_specs = [
                selfie_camera
            ]

        # ==========================================================
        # SOUND
        # ==========================================================

        loudspeaker = self._find_global(
            specs,
            "Loudspeaker",
        )

        jack = self._find_global(
            specs,
            "3.5mm Jack",
            "Headphone Jack",
        )

        # ==========================================================
        # FEATURES
        # ==========================================================

        wlan = self._find_global(
            specs,
            "WLAN",
            "Wi-Fi",
            "WiFi",
        )

        bluetooth = self._find_global(
            specs,
            "Bluetooth",
        )

        positioning = self._find_global(
            specs,
            "Positioning",
            "GPS",
        )

        nfc = self._find_global(
            specs,
            "NFC",
        )

        infrared = self._find_global(
            specs,
            "Infrared Port",
            "Infrared",
        )

        radio = self._find_global(
            specs,
            "Radio",
        )

        usb = self._find_global(
            specs,
            "USB",
            "USB Port",
        )

        sensors = self._find_global(
            specs,
            "Sensors",
            "Features & Sensors",
        )

        fingerprint = self._find_global(
            specs,
            "Fingerprint",
        )

        fingerprint_text = (
            fingerprint or ""
        ).lower()

        # ==========================================================
        # BATTERY
        #
        # IMPORTANT:
        # Battery Type = Li-Ion
        #
        # Battery Capacity = 5000 mAh
        #
        # The RAW SPECS use:
        #
        # Type
        # Size
        # Capacity
        # Refresh Rate
        #
        # So we explicitly avoid using "Type" globally for Display.
        # ==========================================================

        battery_type = self._find_global(
            specs,
            "Type",
            "Battery Type",
        )

        battery_capacity = self._find_global(
            specs,
            "Capacity",
            "Battery Capacity",
        )

        charging = self._find_global(
            specs,
            "Charging",
            "Battery Charging",
        )

        wireless_charging = self._find_global(
            specs,
            "Wireless Charging",
        )

        charging_values = (
            [charging]
            if charging
            else []
        )

        # ==========================================================
        # COLORS
        # ==========================================================

        colors = self._find_global(
            specs,
            "Colors",
            "Color",
        )

        color_values = self._list(
            colors
        )

        # ==========================================================
        # SAR
        # ==============================================================

        sar = self._find_global(
            specs,
            "SAR",
            "SAR Value",
        )

        # ==========================================================
        # FINAL TEMPLATE
        # ==========================================================

        return {
            "MobileName": raw.get("name"),

            "Network": {
                "2G": int(network_2g),
                "3G": int(network_3g),
                "4G": int(network_4g),
                "5G": int(network_5g),
            },

            "Launch": {
                "Announced": announced,
                "Status": launch_status,
            },

            "Body": {
                "Dimensions": dimensions,
                "Weight": body_weight,
                "Build": build,
                "SIM": sim,
                "Protection": protection,
            },

            "Display": {
                "Type": display_type,
                "Size": display_size,
                "Resolution": display_resolution,
                "Protection": display_protection,
            },

            "Platform": {
                "OS": os_value,
                "Chipset": chipset,
                "CPU": cpu,
                "GPU": gpu,
            },

            "Memory": {
                "Card slot": card_slot,
                "Types": memory_types,
                "Technology": memory_technology,
            },

            "Main Camera": {
                "Specifications": main_camera_specs,
                "Features": camera_features,
                "Video": main_camera_video,
            },

            "Selfie Camera": {
                "Specifications": selfie_specs,
                "Features": selfie_features,
                "Video": (
                    self._list(selfie_video)
                    if selfie_video
                    else []
                ),
            },

            "Sound": {
                "Loudspeaker": loudspeaker,
                "3.5mm jack": self._bits(jack),
            },

            "Features": {
                "WLAN": wlan,
                "Bluetooth": bluetooth,
                "Positioning": positioning,
                "NFC": self._bits(nfc),
                "Infrared port": self._bits(infrared),
                "Radio": self._bits(radio),
                "USB": usb,

                "BackFingerPrint": int(
                    "back" in fingerprint_text
                ),

                "SideFingerPrint": int(
                    "side" in fingerprint_text
                    or "side-mounted" in fingerprint_text
                ),

                "InDisplayFingerPrint": int(
                    "under display" in fingerprint_text
                    or "in-display" in fingerprint_text
                    or "in display" in fingerprint_text
                ),

                "Sensors": sensors,
            },

            "Battery": {
                "Capacity": battery_capacity,
                "WirelessCharging": int(
                    wireless_charging is not None
                    and wireless_charging.strip().lower()
                    not in {
                        "no",
                        "none",
                        "false",
                    }
                ),
                "Charging": charging_values,
            },

            "Colors": color_values,

            "Weight": sar,

            "Price": (
                raw.get("price_text")
                if isinstance(
                    raw.get("price_text"),
                    list,
                )
                else self._prices(
                    raw.get("price_text")
                )
            ),
        }