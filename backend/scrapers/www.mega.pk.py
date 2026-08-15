"""
Mega.pk mobile product scraper.

Parses one already-loaded Mega.pk mobile product page and converts
its specifications into the project's template.json schema.

Expected navigator interface:

    scraper = MegaScraper(
        html,
        source_url=url,
    )

    result = scraper.to_template()
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


class MegaScraper:
    """
    HTML scraper for Mega.pk mobile product pages.

    Mega product pages expose specification sections such as:

        General Specs
        Display
        Storage
        Camera
        Processor
        Communication
        Design
        Features
        Connectors
        Dimensions
        Power Supply
        Software
        Miscellaneous
    """

    SECTION_ALIASES = {
        "general specs": "General Specs",
        "display": "Display",
        "storage": "Storage",
        "camera": "Camera",
        "processor": "Processor",
        "communication": "Communication",
        "design": "Design",
        "features": "Features",
        "connectors": "Connectors",
        "dimensions": "Dimensions",
        "power supply": "Power Supply",
        "software": "Software",
        "miscellaneous": "Miscellaneous",
    }

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
    def _clean_value(
        value: Optional[str],
    ) -> Optional[str]:
        if value is None:
            return None

        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        return value or None

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
            "n/a",
            "na",
            "not supported",
            "not available",
        }:
            return 0

        if value in {
            "yes",
            "true",
            "available",
            "supported",
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
    def _prices(
        value: Optional[str],
    ) -> List[float]:
        if not value:
            return []

        prices: List[float] = []

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
                prices.append(number)

        return prices

    @staticmethod
    def _clean_video_list(
        value: Optional[str],
    ) -> List[str]:
        if not value:
            return []

        result: List[str] = []

        for item in re.split(
            r"\s*,\s*",
            value,
        ):
            item = item.strip()

            item = item.lstrip(
                "([{"
            )

            item = item.rstrip(
                ")]}"
            )

            item = item.strip()

            if item:
                result.append(item)

        return result

    # ==================================================================
    # SECTION PARSING
    # ==================================================================

    def _section_name(
        self,
        text: str,
    ) -> Optional[str]:
        normalized = self._normalize(
            text
        )

        return self.SECTION_ALIASES.get(
            normalized
        )

    def _collect_specs(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """
        Collect Mega specification rows by section.

        Result:

            {
                "Display": {
                    "screen size": "...",
                    "screen resolution": "..."
                },
                "Storage": {
                    "internal storage space": "..."
                }
            }
        """

        sections: Dict[str, Dict[str, str]] = {}

        current_section = "General Specs"

        for element in self.soup.select(
            "h2, h3, h4, table"
        ):

            if element.name in {
                "h2",
                "h3",
                "h4",
            }:
                section = self._section_name(
                    self._text(element)
                )

                if section:
                    current_section = section
                    sections.setdefault(
                        current_section,
                        {},
                    )

                continue

            if element.name != "table":
                continue

            for row in element.find_all(
                "tr"
            ):

                cells = row.find_all(
                    ["th", "td"],
                    recursive=False,
                )

                if len(cells) < 2:
                    continue

                label = self._text(
                    cells[0]
                )

                if not label:
                    continue

                value = " ".join(
                    self._text(cell)
                    for cell in cells[1:]
                )

                value = self._clean_value(
                    value
                )

                if not value:
                    continue

                normalized_label = (
                    self._normalize(label)
                )

                section = sections.setdefault(
                    current_section,
                    {},
                )

                if (
                    normalized_label
                    not in section
                ):
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

        section_specs = self.specs.get(
            section,
            {},
        )

        for label in labels:

            key = self._normalize(
                label
            )

            value = section_specs.get(
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
    # MOBILE NAME
    # ==================================================================

    def _mobile_name(
        self,
    ) -> Optional[str]:

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
            "General Specs",
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
            "Network",
            "Network Technology",
            "Technology",
            "2G",
            "2G Bands",
            "3G",
            "3G Bands",
            "4G",
            "4G LTE",
            "4G Bands",
            "5G",
            "5G Support",
            "5G Bands",
        ]:

            value = self._get(
                "Communication",
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
                        r"\b2g\b|\bgsm\b|\bedge\b",
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

        release_year = self._get(
            "Miscellaneous",
            "Release year",
            "Release Year",
        )

        return {
            "Announced": None,
            "Status": (
                f"Released {release_year}"
                if release_year
                else None
            ),
        }

    # ==================================================================
    # BODY
    # ==================================================================

    def _body(self) -> dict:

        dimensions = self._get(
            "Dimensions",
            "Dimensions (WxHxD)",
            "Dimensions",
        )

        weight = self._get(
            "Dimensions",
            "Weight",
        )

        build = self._get(
            "Design",
            "Body",
            "Build",
        )

        sim = self._get(
            "Features",
            "Dual SIM card support",
            "SIM",
        )

        protection = self._get_any(
            [
                "Features",
                "Design",
            ],
            "IP code (level of dust/water resistance)",
            "Water Resistant",
            "Waterproof",
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
            "Display technology",
            "Display Technology",
            "Type",
        )

        display_value = self._get(
            "Display",
            "Display",
        )

        if not display_type and display_value:
            display_type = display_value

        size = self._get(
            "Display",
            "Screen size",
            "Display Size",
            "Size",
        )

        resolution = self._get(
            "Display",
            "Screen resolution",
            "Display Resolution",
            "Resolution",
        )

        protection = self._get(
            "Display",
            "Protection",
            "Display Protection",
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

        chipset = self._get(
            "Processor",
            "Chipset",
        )

        cpu = self._get(
            "Processor",
            "CPU type",
            "Processor core type",
            "CPU",
            "Processor",
        )

        gpu = self._get(
            "Processor",
            "Graphics processor type",
            "GPU",
            "Graphics Processor",
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
            "General Specs",
            "RAM",
        )

        if not ram:
            ram = self._get(
                "Processor",
                "RAM",
            )

        storage = self._get(
            "Storage",
            "Internal storage space",
            "Storage Capacity",
            "Internal Storage",
        )

        card_slot = self._get(
            "Storage",
            "SD Card",
            "Memory Card Slot",
        )

        memory_technology = self._get(
            "Storage",
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
            "Technology": memory_technology,
        }

    # ==================================================================
    # MAIN CAMERA
    # ==================================================================

    def _main_camera(self) -> dict:

        main_camera = self._get(
            "Camera",
            "Main Camera Pixels",
            "Main Camera Resolution",
            "Maximum resolution (still)",
            "Rear Camera",
            "Main Camera",
        )

        specifications = (
            [main_camera]
            if main_camera
            else []
        )

        feature_parts: List[str] = []

        for label in [
            "Built-in flash",
            "Auto focus",
            "Digital zoom (still image)",
            "Optical zoom",
            "Image stabilization",
        ]:

            value = self._get(
                "Camera",
                label,
            )

            if value:
                feature_parts.append(
                    f"{label}: {value}"
                )

        features = (
            "; ".join(
                feature_parts
            )
            if feature_parts
            else None
        )

        video = self._get(
            "Camera",
            "Maximum resolution (video)",
            "Video Resolution",
            "Video",
        )

        if not video:

            fps = self._get(
                "Camera",
                "Maximum numbers of fps when recording",
            )

            if fps:
                video = fps

        return {
            "Specifications": specifications,
            "Features": features,
            "Video": (
                self._clean_video_list(
                    video
                )
                if video
                else []
            ),
        }

    # ==================================================================
    # SELFIE CAMERA
    # ==================================================================

    def _selfie_camera(self) -> dict:

        front = self._get(
            "Camera",
            "Front Camera Resolution",
            "Front Camera",
            "Selfie Camera",
        )

        return {
            "Specifications": (
                [front]
                if front
                else []
            ),
            "Features": None,
            "Video": [],
        }

    # ==================================================================
    # SOUND
    # ==================================================================

    def _sound(self) -> dict:

        loudspeaker = self._get(
            "Features",
            "Loudspeaker",
            "Speaker",
        )

        if loudspeaker is None:
            loudspeaker = "Yes"

        jack = self._get(
            "Connectors",
            "Headphone Port",
            "3.5mm headphone output",
            "3.5mm Jack",
        )

        return {
            "Loudspeaker": loudspeaker,
            "3.5mm jack": (
                self._bits(jack)
                if jack is not None
                else 0
            ),
        }

    # ==================================================================
    # FEATURES
    # ==================================================================

    def _features(self) -> dict:

        wlan = self._get(
            "Communication",
            "WiFi (Wireless Fidelity)",
            "Wi-Fi",
            "WLAN",
        )

        bluetooth = self._get(
            "Communication",
            "Bluetooth",
        )

        positioning = self._get(
            "Communication",
            "GPS",
            "Positioning",
        )

        nfc = self._get(
            "Communication",
            "NFC Support",
            "NFC",
        )

        infrared = self._get(
            "Communication",
            "Infrared",
            "Infrared Port",
        )

        radio = self._get(
            "Communication",
            "Radio",
            "FM Radio",
        )

        usb = self._get(
            "Connectors",
            "Type of connection",
            "Charging via USB",
            "USB",
        )

        sensors = self._get(
            "Features",
            "Sensors",
        )

        fingerprint = self._get(
            "Features",
            "Finger Print",
            "Fingerprint",
            "Fingerprint Sensor",
        )

        fingerprint_text = (
            fingerprint or ""
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
                or "under-display"
                in fingerprint_text
                or "in display"
                in fingerprint_text
                or "in-display"
                in fingerprint_text
            ),

            "Sensors": sensors,
        }

    # ==================================================================
    # BATTERY
    # ==================================================================

    def _battery(self) -> dict:

        capacity = self._get(
            "Power Supply",
            "Battery capacity",
            "Battery Capacity",
            "Capacity",
        )

        battery_type = self._get(
            "Power Supply",
            "Battery Type",
            "Battery type",
            "Type",
        )

        charging = self._get(
            "Power Supply",
            "Charging",
            "Support Fast Charging",
            "Fast Charging",
        )

        wireless = self._get(
            "Features",
            "Built-in Wireless Charging",
            "Wireless Charging",
        )

        charging_values: List[str] = []

        if charging:
            charging_values.append(
                charging
            )

        return {
            "Capacity": (
                capacity
                or battery_type
            ),
            "WirelessCharging": self._bits(
                wireless
            ),
            "Charging": charging_values,
        }

    # ==================================================================
    # COLORS
    # ==================================================================

    def _colors(self) -> List[str]:

        color = self._get_any(
            [
                "Design",
                "General Specs",
            ],
            "Colour",
            "Color",
            "Colors",
            "Colours",
        )

        return self._list(
            color
        )

    # ==================================================================
    # SAR
    # ==================================================================

    def _sar(self) -> Optional[str]:

        return self._get_any(
            [
                "General Specs",
                "Miscellaneous",
                "Features",
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

            "Weight": self._sar(),

            "Price": self._price(),
        }