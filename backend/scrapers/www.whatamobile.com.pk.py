"""
WhatAMobile.com.pk product scraper.

Parses one already-loaded WhatAMobile product page and converts
its specifications into the project's template.json schema.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


class WhatamobileScraper:
    """
    Scraper for WhatAMobile.com.pk product pages.

    Expected navigator interface:

        scraper = WhatamobileScraper(
            html,
            source_url=url,
        )

        result = scraper.to_template()
    """

    KNOWN_SECTIONS = {
        "general": "General",
        "design": "Design",
        "network": "Network",
        "display": "Display",
        "media": "Media",
        "camera": "Camera",
        "software": "Software",
        "hardware": "Hardware",
        "connectivity": "Connectivity",
        "data": "Data",
        "battery": "Battery",
    }

    KNOWN_LABELS = [
        "Wireless Charging",
        "Battery Capacity",
        "Battery Type",
        "Operating System",
        "Internal Storage",
        "Memory Card Slot",
        "Storage Capacity",
        "Camera Features",
        "Rear Camera Features",
        "Front Camera Features",
        "Main Camera",
        "Primary Camera",
        "Rear Camera",
        "Secondary Camera",
        "Front Camera",
        "Selfie Camera",
        "Display Type",
        "Display Size",
        "Display Resolution",
        "Network Technology",
        "5G Support",
        "5G Bands",
        "4G Bands",
        "3G Bands",
        "2G Bands",
        "3.5mm Jack",
        "Headphone Jack",
        "Fingerprint Sensor",
        "Fingerprint",
        "Card Slot",
        "Loudspeaker",
        "Bluetooth",
        "Positioning",
        "Wi-Fi",
        "Wi-fi",
        "WLAN",
        "Wi-fi Hotspot",
        "USB",
        "GPS",
        "NFC",
        "Infrared Port",
        "Infrared",
        "FM Radio",
        "Radio",
        "Capacity",
        "Charging",
        "Refresh Rate",
        "Resolution",
        "Dimensions",
        "Weight",
        "Protection",
        "Build",
        "SIM",
        "Dual SIM",
        "Colors",
        "Colours",
        "Color",
        "Video",
        "Camera",
        "Features",
        "RAM",
        "Storage",
        "ROM",
        "OS",
        "Chipset",
        "CPU",
        "GPU",
        "Status",
        "Released",
        "Announced",
        "Price",
        "Model",
        "Device Type",
        "Flash",
        "Sensors",
        "Data",
    ]

    def __init__(
        self,
        html: str,
        source_url: Optional[str] = None,
    ) -> None:
        self.soup = BeautifulSoup(
            html,
            "html.parser",
        )

        self.source_url = source_url
        self.specs = self._collect_specs()

    # ==================================================================
    # BASIC HELPERS
    # ==================================================================

    @staticmethod
    def _text(node) -> str:
        """
        Extract clean text from a BeautifulSoup node.
        """
        if node is None:
            return ""

        if isinstance(node, str):
            return re.sub(
                r"\s+",
                " ",
                node,
            ).strip()

        return re.sub(
            r"\s+",
            " ",
            node.get_text(
                " ",
                strip=True,
            ),
        ).strip()

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(
            r"[^a-z0-9]+",
            " ",
            value.lower(),
        ).strip()

    @staticmethod
    def _bits(value: Optional[str]) -> int:
        if not value:
            return 0

        value = value.strip().lower()

        if value in {
            "",
            "-",
            "no",
            "none",
            "false",
            "not supported",
            "not available",
            "n/a",
            "na",
        }:
            return 0

        if value in {
            "yes",
            "true",
            "supported",
            "available",
            "present",
        }:
            return 1

        if value.startswith("yes "):
            return 1

        if value.startswith("available "):
            return 1

        if value.startswith("supported "):
            return 1

        return 0

    @staticmethod
    def _list(
        value: Optional[str],
        pattern: str = r"\s*,\s*",
    ) -> List[str]:
        if not value:
            return []

        return [
            item.strip()
            for item in re.split(
                pattern,
                value,
            )
            if item.strip()
        ]

    @staticmethod
    def _clean_video_values(
        value: Optional[str],
    ) -> List[str]:
        """
        Split video values and remove formatting characters accidentally
        preserved from source text.

        Example:
            "(4K@60fps, 1080p@60/240fps, 720p@960fps, HDR10"

        becomes:
            [
                "4K@60fps",
                "1080p@60/240fps",
                "720p@960fps",
                "HDR10",
            ]
        """

        if not value:
            return []

        values = re.split(
            r"\s*,\s*",
            value,
        )

        cleaned: List[str] = []

        for item in values:

            item = item.strip()

            item = item.lstrip(
                "([{"
            )

            item = item.rstrip(
                ")]}"
            )

            item = item.strip()

            if item:
                cleaned.append(item)

        return cleaned

    @staticmethod
    def _prices(
        value: Optional[str],
    ) -> List[float]:
        if not value:
            return []

        values: List[float] = []

        for match in re.findall(
            r"\d[\d,]*(?:\.\d+)?",
            value,
        ):
            try:
                number = float(
                    match.replace(",", "")
                )
            except ValueError:
                continue

            if number > 0:
                values.append(number)

        return values

    # ==================================================================
    # LABEL NORMALIZATION
    # ==================================================================

    def _canonical_label(
        self,
        raw_label: str,
    ) -> str:
        """
        Convert WhatAMobile's verbose first-column label into a
        canonical specification name.
        """

        if not raw_label:
            return ""

        raw = re.sub(
            r"\s+",
            " ",
            str(raw_label),
        ).strip()

        if "=>" in raw:
            raw = raw.split(
                "=>",
                1,
            )[0].strip()

        normalized_raw = self._normalize(
            raw
        )

        normalized_known = sorted(
            [
                (
                    self._normalize(label),
                    label,
                )
                for label in self.KNOWN_LABELS
            ],
            key=lambda item: len(item[0]),
            reverse=True,
        )

        for normalized_label, original_label in normalized_known:

            if normalized_raw == normalized_label:
                return original_label

            if normalized_raw.startswith(
                normalized_label + " "
            ):
                return original_label

        special_prefixes = {
            "primary camera is": "Primary Camera",
            "secondary camera": "Secondary Camera",
            "front camera": "Front Camera",
            "rear camera": "Rear Camera",
            "camera features": "Camera Features",
            "operating system os": "Operating System",
            "battery type battery type": "Battery Type",
            "card slot memory card slot": "Card Slot",
        }

        for prefix, label in special_prefixes.items():
            if normalized_raw.startswith(prefix):
                return label

        if len(raw.split()) <= 5:
            return raw.strip(" :|-")

        lowered = raw.lower()

        for separator in (
            " is ",
            " which ",
            " that ",
        ):
            index = lowered.find(
                separator
            )

            if index > 0:
                candidate = raw[:index].strip()

                if len(candidate.split()) <= 5:
                    return candidate

        return raw.strip(" :|-")

    # ==================================================================
    # SPEC COLLECTION
    # ==================================================================

    def _collect_specs(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """
        Collect specification tables by section.
        """

        sections: Dict[str, Dict[str, str]] = {}

        current_section = "General"

        for element in self.soup.select(
            "h2, h3, h4, table"
        ):

            tag = element.name

            if tag in {
                "h2",
                "h3",
                "h4",
            }:

                heading = self._normalize(
                    self._text(element)
                )

                if heading in self.KNOWN_SECTIONS:

                    current_section = (
                        self.KNOWN_SECTIONS[
                            heading
                        ]
                    )

                    sections.setdefault(
                        current_section,
                        {},
                    )

                continue

            if tag != "table":
                continue

            for row in element.find_all("tr"):

                cells = row.find_all(
                    ["th", "td"],
                    recursive=False,
                )

                if len(cells) < 2:
                    continue

                raw_label = self._text(
                    cells[0]
                )

                if not raw_label:
                    continue

                value = " ".join(
                    self._text(cell)
                    for cell in cells[1:]
                )

                value = re.sub(
                    r"\s+",
                    " ",
                    value,
                ).strip()

                label = self._canonical_label(
                    raw_label
                )

                if not label:
                    continue

                normalized_label = (
                    self._normalize(label)
                )

                section = sections.setdefault(
                    current_section,
                    {},
                )

                if normalized_label not in section:
                    section[
                        normalized_label
                    ] = value

        return sections

    # ==================================================================
    # LOOKUP
    # ==================================================================

    def _get(
        self,
        section: str,
        *labels: str,
    ) -> Optional[str]:

        section_data = self.specs.get(
            section,
            {},
        )

        for label in labels:

            key = self._normalize(
                label
            )

            value = section_data.get(
                key
            )

            if value:
                return value

        return None

    def _get_any(
        self,
        sections: List[str],
        *labels: str,
    ) -> Optional[str]:

        for section in sections:

            value = self._get(
                section,
                *labels,
            )

            if value is not None:
                return value

        return None

    # ==================================================================
    # TOP SUMMARY
    # ==================================================================

    def _find_summary_field(
        self,
        field_name: str,
    ) -> Optional[str]:
        """
        Find compact summary values such as:

            Display: LTPS IPS LCD
            Camera: 16 MP...
            OS: Android 9.0
            CPU: Octa-core...
        """

        pattern = re.compile(
            rf"^\s*{re.escape(field_name)}\s*:\s*(.+)$",
            flags=re.IGNORECASE,
        )

        for element in self.soup.find_all(
            ["li", "div", "p", "span"],
        ):

            text = self._text(
                element
            )

            if not text:
                continue

            match = pattern.match(
                text
            )

            if match:

                value = match.group(
                    1
                ).strip()

                if value:
                    return value

        return None

    # ==================================================================
    # NAME
    # ==================================================================

    def _mobile_name(self) -> Optional[str]:

        node = self.soup.select_one(
            "h1"
        )

        if not node:
            return None

        name = self._text(
            node
        )

        name = re.sub(
            r"\s+Price\s+in\s+Pakistan\s*$",
            "",
            name,
            flags=re.IGNORECASE,
        )

        return name.strip() or None

    # ==================================================================
    # PRICE
    # ==================================================================

    def _price(self) -> List[float]:

        general_price = self._get(
            "General",
            "Price",
        )

        if general_price:

            values = self._prices(
                general_price
            )

            if values:
                return values

        for selector in [
            ".woocommerce-Price-amount",
            ".price",
            ".amount",
            ".product-price",
        ]:

            for node in self.soup.select(
                selector
            ):

                values = self._prices(
                    self._text(node)
                )

                if values:
                    return values

        page_text = self._text(
            self.soup
        )

        match = re.search(
            r"(?:Rs\.?|PKR|₨)\s*"
            r"([0-9][0-9,]*(?:\.[0-9]+)?)",
            page_text,
            flags=re.IGNORECASE,
        )

        if match:
            return self._prices(
                match.group(1)
            )

        return []

    # ==================================================================
    # NETWORK
    # ==================================================================

    def _network(self) -> dict:

        values: List[str] = []

        for label in [
            "Technology",
            "2G",
            "2G Bands",
            "3G",
            "3G Bands",
            "4G",
            "4G Bands",
            "5G",
            "5G Bands",
            "5G Support",
        ]:

            value = self._get(
                "Network",
                label,
            )

            if value:
                values.append(
                    value
                )

        text = " ".join(
            values
        ).lower()

        return {
            "2G": int(
                bool(
                    re.search(
                        r"\b2g\b|\bgsm\b",
                        text,
                    )
                )
            ),
            "3G": int(
                bool(
                    re.search(
                        r"\b3g\b|\bhspa\b|\bumts\b",
                        text,
                    )
                )
            ),
            "4G": int(
                bool(
                    re.search(
                        r"\b4g\b|\blte\b",
                        text,
                    )
                )
            ),
            "5G": int(
                bool(
                    re.search(
                        r"\b5g\b",
                        text,
                    )
                )
            ),
        }

    # ==================================================================
    # LAUNCH
    # ==================================================================

    def _launch(self) -> dict:

        announced = self._get(
            "General",
            "Announced",
            "Announcement",
            "Announcement Date",
        )

        status = self._get(
            "General",
            "Status",
            "Availability",
        )

        return {
            "Announced": announced,
            "Status": status,
        }

    # ==================================================================
    # BODY
    # ==================================================================

    def _body(self) -> dict:

        dimensions = self._get(
            "Design",
            "Dimensions",
            "Dimension",
        )

        weight = self._get(
            "Design",
            "Weight",
        )

        build = self._get(
            "Design",
            "Build",
            "Build Material",
        )

        sim = self._get(
            "Network",
            "SIM",
            "SIM Type",
            "Dual SIM",
        )

        protection = self._get(
            "Design",
            "Protection",
        )

        return {
            "Dimensions": dimensions,
            "Weight": weight,
            "Build": build,
            "SIM": sim,
            "Protection": protection,
        }

    # ==================================================================
    # DISPLAY
    # ==================================================================

    def _display(self) -> dict:

        display_type = self._get(
            "Display",
            "Type",
            "Display Type",
        )

        if not display_type:
            display_type = (
                self._find_summary_field(
                    "Display"
                )
            )

        size = self._get(
            "Display",
            "Size",
            "Display Size",
        )

        resolution = self._get(
            "Display",
            "Resolution",
            "Display Resolution",
        )

        protection = self._get(
            "Display",
            "Protection",
            "Display Protection",
        )

        refresh_rate = self._get(
            "Display",
            "Refresh Rate",
        )

        if refresh_rate:

            if not display_type:
                display_type = refresh_rate

            elif (
                refresh_rate.lower()
                not in display_type.lower()
            ):

                display_type = (
                    f"{display_type}, "
                    f"{refresh_rate}"
                )

        return {
            "Type": display_type,
            "Size": size,
            "Resolution": resolution,
            "Protection": protection,
        }

    # ==================================================================
    # PLATFORM
    # ==================================================================

    def _platform(self) -> dict:

        os_value = self._get(
            "Software",
            "Operating System",
            "OS",
        )

        if not os_value:
            os_value = (
                self._find_summary_field(
                    "OS"
                )
            )

        chipset = self._get(
            "Hardware",
            "Chipset",
        )

        if not chipset:
            chipset = (
                self._find_summary_field(
                    "Chipset"
                )
            )

        cpu = self._get(
            "Hardware",
            "CPU",
            "Processor",
        )

        if not cpu:
            cpu = (
                self._find_summary_field(
                    "CPU"
                )
            )

        gpu = self._get(
            "Hardware",
            "GPU",
        )

        if not gpu:
            gpu = (
                self._find_summary_field(
                    "GPU"
                )
            )

        return {
            "OS": os_value,
            "Chipset": chipset,
            "CPU": cpu,
            "GPU": gpu,
        }

    # ==================================================================
    # MEMORY
    # ==================================================================

    def _memory(self) -> dict:

        ram = self._get(
            "Hardware",
            "RAM",
        )

        if not ram:
            ram = (
                self._find_summary_field(
                    "RAM"
                )
            )

        storage = self._get(
            "Hardware",
            "Internal Storage",
            "Storage",
            "ROM",
        )

        if not storage:
            storage = (
                self._find_summary_field(
                    "Storage"
                )
            )

        card_slot = self._get(
            "Hardware",
            "Card Slot",
            "Memory Card Slot",
        )

        technology = self._get(
            "Hardware",
            "Memory Technology",
            "Storage Technology",
        )

        memory_types: List[str] = []

        if ram and storage:

            memory_types.append(
                f"{ram} {storage}"
            )

        elif ram:

            memory_types.append(
                ram
            )

        elif storage:

            memory_types.append(
                storage
            )

        return {
            "Card slot": card_slot,
            "Types": memory_types,
            "Technology": technology,
        }

    # ==================================================================
    # CAMERA
    # ==================================================================

    def _main_camera(self) -> dict:

        primary = self._get(
            "Camera",
            "Primary Camera",
            "Main Camera",
            "Rear Camera",
        )

        if not primary:
            primary = (
                self._find_summary_field(
                    "Camera"
                )
            )

        features = self._get(
            "Camera",
            "Camera Features",
        )

        video = self._get(
            "Camera",
            "Video",
        )

        specifications = (
            [primary]
            if primary
            else []
        )

        return {
            "Specifications": specifications,
            "Features": features,
            "Video": (
                self._clean_video_values(
                    video
                )
                if video
                else []
            ),
        }

    def _selfie_camera(self) -> dict:

        secondary = self._get(
            "Camera",
            "Secondary Camera",
            "Front Camera",
            "Selfie Camera",
            "Secondary",
        )

        features = self._get(
            "Camera",
            "Front Camera Features",
            "Selfie Camera Features",
        )

        video = self._get(
            "Camera",
            "Front Video",
            "Selfie Video",
        )

        specifications = (
            [secondary]
            if secondary
            else []
        )

        return {
            "Specifications": specifications,
            "Features": features,
            "Video": (
                self._clean_video_values(
                    video
                )
                if video
                else []
            ),
        }

    # ==================================================================
    # SOUND
    # ==================================================================

    def _sound(self) -> dict:

        loudspeaker = self._get(
            "Media",
            "Loudspeaker",
        )

        jack = self._get_any(
            [
                "Media",
                "Connectivity",
            ],
            "3.5mm Jack",
            "Headphone Jack",
        )

        return {
            "Loudspeaker": loudspeaker,
            "3.5mm jack": self._bits(jack),
        }

    # ==================================================================
    # FEATURES
    # ==================================================================

    def _features(self) -> dict:

        wlan = self._get(
            "Connectivity",
            "Wi-Fi",
            "Wi-fi",
            "WLAN",
        )

        bluetooth = self._get(
            "Connectivity",
            "Bluetooth",
        )

        positioning = self._get(
            "Connectivity",
            "GPS",
            "Positioning",
        )

        nfc = self._get(
            "Connectivity",
            "NFC",
        )

        infrared = self._get(
            "Connectivity",
            "Infrared",
            "Infrared Port",
        )

        radio = self._get(
            "Media",
            "Radio",
            "FM Radio",
        )

        usb = self._get(
            "Connectivity",
            "USB",
            "USB Port",
        )

        sensors = self._get(
            "Hardware",
            "Sensors",
            "Sensor",
        )

        fingerprint = self._get(
            "Hardware",
            "Fingerprint",
            "Fingerprint Sensor",
        )

        # IMPORTANT:
        # WhatAMobile sometimes stores the fingerprint information
        # inside Sensors instead of a separate Fingerprint field.
        fingerprint_text = " ".join(
            value
            for value in (
                fingerprint,
                sensors,
            )
            if value
        ).lower()

        return {
            "WLAN": wlan,
            "Bluetooth": bluetooth,
            "Positioning": positioning,
            "NFC": self._bits(nfc),
            "Infrared port": self._bits(
                infrared
            ),
            "Radio": self._bits(
                radio
            ),
            "USB": usb,

            "BackFingerPrint": int(
                "back" in fingerprint_text
            ),

            "SideFingerPrint": int(
                "side" in fingerprint_text
                or "side-mounted"
                in fingerprint_text
                or "side mounted"
                in fingerprint_text
            ),

            "InDisplayFingerPrint": int(
                "under display"
                in fingerprint_text
                or "in-display"
                in fingerprint_text
                or "in display"
                in fingerprint_text
                or "under-screen"
                in fingerprint_text
                or "under screen"
                in fingerprint_text
            ),

            "Sensors": sensors,
        }

    # ==================================================================
    # BATTERY
    # ==================================================================

    def _battery(self) -> dict:

        capacity = self._get(
            "Battery",
            "Capacity",
        )

        charging = self._get(
            "Battery",
            "Charging",
            "Fast Charging",
            "Charging Technology",
        )

        wireless = self._get(
            "Battery",
            "Wireless Charging",
        )

        return {
            "Capacity": capacity,
            "WirelessCharging": self._bits(
                wireless
            ),
            "Charging": (
                [charging]
                if charging
                else []
            ),
        }

    # ==================================================================
    # COLORS
    # ==================================================================

    def _colors(self) -> List[str]:

        value = self._get_any(
            [
                "General",
                "Design",
            ],
            "Colors",
            "Colours",
            "Color",
        )

        return self._list(
            value
        )

    # ==================================================================
    # SAR
    # ==================================================================

    def _root_weight(self) -> Optional[str]:

        return self._get_any(
            [
                "General",
                "Hardware",
                "Connectivity",
            ],
            "SAR",
            "SAR Value",
        )

    # ==================================================================
    # FINAL TEMPLATE
    # ==================================================================

    def to_template(
        self,
        raw: Optional[dict] = None,
    ) -> dict:

        name = self._mobile_name()

        if not name:

            raise RuntimeError(
                "Could not extract MobileName "
                f"from {self.source_url or 'page'}"
            )

        return {
            "MobileName": name,

            "Network": self._network(),

            "Launch": self._launch(),

            "Body": self._body(),

            "Display": self._display(),

            "Platform": self._platform(),

            "Memory": self._memory(),

            "Main Camera": self._main_camera(),

            "Selfie Camera": self._selfie_camera(),

            "Sound": self._sound(),

            "Features": self._features(),

            "Battery": self._battery(),

            "Colors": self._colors(),

            "Weight": self._root_weight(),

            "Price": self._price(),
        }