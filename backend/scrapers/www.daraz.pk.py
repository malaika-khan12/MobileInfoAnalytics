"""
Daraz.pk smartphone scraper.

Extracts Daraz mobile-phone information from:

1. Daraz embedded specification JSON.
2. JSON-LD Product data.
3. Product title.
4. Product description / bullet points.
5. Visible HTML specification rows.

The output follows the project's standard mobile JSON template.

Important:
- Only information actually available on the Daraz page is populated.
- Missing specifications remain null/empty.
- No unsupported values are invented.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Dict, Iterable, List, Optional

from bs4 import BeautifulSoup


class DarazScraper:

    def __init__(
        self,
        html: str,
        source_url: Optional[str] = None,
    ) -> None:

        self.html = html
        self.source_url = source_url

        self.soup = BeautifulSoup(
            html,
            "html.parser",
        )

        self.page_text = self._text(
            self.soup
        )

        self.scripts = [
            script.string or script.get_text()
            for script in self.soup.find_all("script")
            if script.string or script.get_text()
        ]

        self.embedded_objects = (
            self._collect_json_ld()
        )

        self.specifications = (
            self._collect_specifications()
        )

        self.product_name = (
            self._name()
        )

        self.description = (
            self._description()
        )

    # ==================================================================
    # BASIC HELPERS
    # ==================================================================

    @staticmethod
    def _text(node) -> str:

        if node is None:
            return ""

        if isinstance(
            node,
            str,
        ):
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
    def _normalize(
        value: str,
    ) -> str:

        return re.sub(
            r"[^a-z0-9]+",
            " ",
            str(value).lower(),
        ).strip()

    @staticmethod
    def _clean(
        value: Any,
    ) -> Optional[str]:

        if value is None:
            return None

        value = html_lib.unescape(
            str(value)
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        return value or None

    @staticmethod
    def _bits(
        value: Optional[str],
    ) -> int:

        if not value:
            return 0

        value = (
            str(value)
            .strip()
            .lower()
        )

        if value in {
            "",
            "-",
            "no",
            "none",
            "false",
            "n/a",
            "na",
            "not available",
            "not supported",
            "not specified",
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

        if value.startswith(
            "yes "
        ):
            return 1

        return 0

    @staticmethod
    def _prices(
        value: Optional[str],
    ) -> List[float]:

        if not value:
            return []

        result: List[float] = []

        for match in re.findall(
            r"\d[\d,]*(?:\.\d+)?",
            str(value),
        ):

            try:
                number = float(
                    match.replace(
                        ",",
                        "",
                    )
                )
            except ValueError:
                continue

            if number > 0:
                result.append(number)

        return result

    @staticmethod
    def _split_values(
        value: Optional[str],
    ) -> List[str]:

        if not value:
            return []

        return [
            part.strip()
            for part in re.split(
                r"\s*[,;|]\s*",
                value,
            )
            if part.strip()
        ]

    # ==================================================================
    # JSON-LD
    # ==================================================================

    def _collect_json_ld(
        self,
    ) -> List[Any]:

        objects: List[Any] = []

        for script in self.soup.find_all(
            "script",
            type="application/ld+json",
        ):

            raw = (
                script.string
                or script.get_text()
            )

            if not raw:
                continue

            raw = raw.strip()

            if not raw:
                continue

            try:
                objects.append(
                    json.loads(raw)
                )
            except json.JSONDecodeError:
                continue

        return objects

    def _walk(
        self,
        value: Any,
    ) -> Iterable[Any]:

        yield value

        if isinstance(
            value,
            dict,
        ):

            for child in value.values():
                yield from self._walk(
                    child
                )

        elif isinstance(
            value,
            list,
        ):

            for child in value:
                yield from self._walk(
                    child
                )

    # ==================================================================
    # BALANCED JSON ARRAY
    # ==================================================================

    @staticmethod
    def _extract_balanced_array(
        text: str,
        start: int,
    ) -> Optional[str]:

        if (
            start < 0
            or start >= len(text)
            or text[start] != "["
        ):
            return None

        depth = 0
        in_string = False
        escape = False
        quote = ""

        for index in range(
            start,
            len(text),
        ):

            char = text[index]

            if in_string:

                if escape:
                    escape = False
                    continue

                if char == "\\":
                    escape = True
                    continue

                if char == quote:
                    in_string = False

                continue

            if char in {
                '"',
                "'",
            }:
                in_string = True
                quote = char
                continue

            if char == "[":
                depth += 1
                continue

            if char == "]":

                depth -= 1

                if depth == 0:
                    return text[
                        start:index + 1
                    ]

        return None

    # ==================================================================
    # DARAZ SPECIFICATIONS
    # ==================================================================

    def _collect_specifications(
        self,
    ) -> Dict[str, str]:

        specs: Dict[str, str] = {}

        for script in self.scripts:

            lowered = script.lower()

            position = 0

            while True:

                match = re.search(
                    r'"specifications"\s*:',
                    lowered[position:],
                )

                if not match:
                    break

                colon_end = (
                    position
                    + match.end()
                )

                array_start = script.find(
                    "[",
                    colon_end,
                )

                if array_start < 0:
                    position = colon_end
                    continue

                array_text = (
                    self._extract_balanced_array(
                        script,
                        array_start,
                    )
                )

                if not array_text:
                    position = (
                        array_start + 1
                    )
                    continue

                try:

                    parsed = json.loads(
                        array_text
                    )

                except json.JSONDecodeError:

                    position = (
                        array_start + 1
                    )
                    continue

                if isinstance(
                    parsed,
                    list,
                ):
                    self._consume_spec_list(
                        parsed,
                        specs,
                    )

                position = (
                    array_start
                    + len(array_text)
                )

        # Visible HTML fallback
        for row in self.soup.find_all(
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

            value = self._text(
                cells[1]
            )

            if not label or not value:
                continue

            key = self._normalize(
                label
            )

            if key not in specs:
                specs[key] = value

        return specs

    def _consume_spec_list(
        self,
        values: list,
        specs: Dict[str, str],
    ) -> None:

        for item in values:

            if not isinstance(
                item,
                dict,
            ):
                continue

            label = self._clean(
                item.get("name")
            )

            if not label:
                continue

            extracted: List[str] = []

            item_values = item.get(
                "values"
            )

            if isinstance(
                item_values,
                list,
            ):

                for value_item in item_values:

                    if isinstance(
                        value_item,
                        dict,
                    ):

                        value = self._clean(
                            value_item.get(
                                "name"
                            )
                        )

                    else:

                        value = self._clean(
                            value_item
                        )

                    if value:
                        extracted.append(
                            value
                        )

            direct_value = item.get(
                "value"
            )

            if (
                not extracted
                and direct_value is not None
            ):

                value = self._clean(
                    direct_value
                )

                if value:
                    extracted.append(
                        value
                    )

            if not extracted:
                continue

            key = self._normalize(
                label
            )

            value = "; ".join(
                dict.fromkeys(
                    extracted
                )
            )

            if key not in specs:
                specs[key] = value

    # ==================================================================
    # SPEC LOOKUP
    # ==================================================================

    def _spec(
        self,
        *labels: str,
    ) -> Optional[str]:

        for label in labels:

            key = self._normalize(
                label
            )

            value = self.specifications.get(
                key
            )

            if value:
                return value

        return None

    def _spec_contains(
        self,
        *phrases: str,
    ) -> Optional[str]:

        normalized = [
            self._normalize(
                phrase
            )
            for phrase in phrases
        ]

        for key, value in (
            self.specifications.items()
        ):

            for phrase in normalized:

                if phrase in key:
                    return value

        return None

    # ==================================================================
    # DESCRIPTION
    # ==================================================================

    def _description(
        self,
    ) -> str:

        # JSON-LD product description
        for root in self.embedded_objects:

            for node in self._walk(
                root
            ):

                if not isinstance(
                    node,
                    dict,
                ):
                    continue

                if (
                    str(
                        node.get(
                            "@type",
                            ""
                        )
                    ).lower()
                    != "product"
                ):
                    continue

                description = node.get(
                    "description"
                )

                if description:

                    return (
                        self._clean(
                            description
                        )
                        or ""
                    )

        # Visible description
        for selector in [
            ".pdp-product-detail",
            ".html-content",
            "[class*='description']",
            "[class*='product-detail']",
        ]:

            node = self.soup.select_one(
                selector
            )

            if node:

                text = self._text(
                    node
                )

                if len(text) > 40:
                    return text

        return ""

    # ==================================================================
    # NAME
    # ==================================================================

    def _name(
        self,
    ) -> Optional[str]:

        for root in self.embedded_objects:

            for node in self._walk(
                root
            ):

                if not isinstance(
                    node,
                    dict,
                ):
                    continue

                if (
                    str(
                        node.get(
                            "@type",
                            ""
                        )
                    ).lower()
                    != "product"
                ):
                    continue

                name = node.get(
                    "name"
                )

                if name:
                    return self._clean(
                        name
                    )

        for script in self.scripts:

            match = re.search(
                r'"pdt_name"\s*:\s*"((?:\\.|[^"\\])*)"',
                script,
                re.IGNORECASE,
            )

            if match:

                try:
                    value = json.loads(
                        f'"{match.group(1)}"'
                    )
                except Exception:
                    value = match.group(1)

                value = self._clean(
                    value
                )

                if value:
                    return value

        node = self.soup.select_one(
            "h1"
        )

        if node:

            value = self._text(
                node
            )

            if value:
                return value

        return None

    # ==================================================================
    # PRICE
    # ==================================================================

    def _price(
        self,
    ) -> List[float]:

        for root in self.embedded_objects:

            for node in self._walk(
                root
            ):

                if not isinstance(
                    node,
                    dict,
                ):
                    continue

                if (
                    str(
                        node.get(
                            "@type",
                            ""
                        )
                    ).lower()
                    != "product"
                ):
                    continue

                offers = node.get(
                    "offers"
                )

                if isinstance(
                    offers,
                    dict,
                ):

                    values = self._prices(
                        offers.get("price")
                    )

                    if values:
                        return [
                            values[0]
                        ]

        for script in self.scripts:

            match = re.search(
                r'"pdt_price"\s*:\s*"Rs\.?\s*([^"]+)"',
                script,
                re.IGNORECASE,
            )

            if match:

                values = self._prices(
                    match.group(1)
                )

                if values:
                    return [
                        values[0]
                    ]

        for selector in [
            ".pdp-price",
            "[class*='pdp-price']",
            "[class*='product-price']",
        ]:

            node = self.soup.select_one(
                selector
            )

            if node:

                values = self._prices(
                    self._text(node)
                )

                if values:
                    return [
                        values[0]
                    ]

        match = re.search(
            r"(?:Rs\.?|PKR|₨)\s*"
            r"([0-9][0-9,]*(?:\.[0-9]+)?)",
            self.page_text,
            re.IGNORECASE,
        )

        if match:
            return self._prices(
                match.group(1)
            )

        return []

    # ==================================================================
    # MEMORY
    # ==================================================================

    def _ram(
        self,
    ) -> Optional[str]:

        value = self._spec_contains(
            "ram",
        )

        if value:

            match = re.search(
                r"(\d+(?:\.\d+)?\s*"
                r"(?:GB|MB))",
                value,
                re.IGNORECASE,
            )

            if match:
                return self._clean(
                    match.group(1)
                )

        text = (
            self.product_name
            + " "
            + self.description
        )

        match = re.search(
            r"(\d+(?:\.\d+)?\s*"
            r"(?:GB|MB)\s*RAM)",
            text,
            re.IGNORECASE,
        )

        if match:
            return self._clean(
                match.group(1)
            )

        return None

    def _storage(
        self,
    ) -> Optional[str]:

        value = self._spec(
            "Storage Capacity",
            "Internal Storage",
            "ROM",
            "Storage",
        )

        if value:
            return value

        text = (
            self.product_name
            + " "
            + self.description
        )

        match = re.search(
            r"(\d+(?:\.\d+)?\s*"
            r"(?:GB|TB))"
            r"\s*(?:storage|rom)",
            text,
            re.IGNORECASE,
        )

        if match:
            return self._clean(
                match.group(1)
            )

        return None

    # ==================================================================
    # DISPLAY
    # ==================================================================

    def _display_type(
        self,
    ) -> Optional[str]:

        value = self._spec_contains(
            "display",
            "screen",
            "panel",
        )

        if value:

            match = re.search(
                r"(IPS LCD|Super AMOLED|"
                r"Dynamic AMOLED|AMOLED|"
                r"OLED|LCD|LTPS|"
                r"PLS TFT|TFT)",
                value,
                re.IGNORECASE,
            )

            if match:
                return self._clean(
                    match.group(1)
                )

        text = (
            self.product_name
            + " "
            + self.description
        )

        match = re.search(
            r"(IPS LCD|Super AMOLED|"
            r"Dynamic AMOLED|AMOLED|"
            r"OLED|LCD|LTPS|"
            r"PLS TFT|TFT)",
            text,
            re.IGNORECASE,
        )

        if match:
            return self._clean(
                match.group(1)
            )

        return None

    def _display_size(
        self,
    ) -> Optional[str]:

        value = self._spec_contains(
            "display size",
            "screen size",
        )

        if value:
            return value

        text = (
            self.product_name
            + " "
            + self.description
        )

        match = re.search(
            r"(\d+(?:\.\d+)?\s*"
            r"(?:\"|inch|inches))",
            text,
            re.IGNORECASE,
        )

        if match:
            return self._clean(
                match.group(1)
            )

        return None

    def _display_resolution(
        self,
    ) -> Optional[str]:

        value = self._spec(
            "Display Resolution",
            "Screen Resolution",
            "Resolution",
        )

        if value:
            return value

        text = (
            self.product_name
            + " "
            + self.description
        )

        match = re.search(
            r"(\d{3,5}\s*[x×]\s*\d{3,5})",
            text,
            re.IGNORECASE,
        )

        if match:
            return self._clean(
                match.group(1)
            )

        return None

    # ==================================================================
    # PLATFORM
    # ==================================================================

    def _chipset(
        self,
    ) -> Optional[str]:

        value = self._spec(
            "Chipset",
            "Processor",
            "Processor Model",
        )

        if value:

            match = re.search(
                r"(Snapdragon\s*[\w+\- ]+|"
                r"Helio\s*[\w+\- ]+|"
                r"Dimensity\s*[\w+\- ]+|"
                r"Exynos\s*[\w+\- ]+|"
                r"Tensor\s*[\w+\- ]+|"
                r"Kirin\s*[\w+\- ]+)",
                value,
                re.IGNORECASE,
            )

            if match:
                return self._clean(
                    match.group(1)
                )

            value = re.sub(
                r"^(?:equipped\s+with\s+"
                r"|powered\s+by\s+"
                r"|featuring\s+)",
                "",
                value,
                flags=re.IGNORECASE,
            ).strip()

            return value

        text = (
            self.product_name
            + " "
            + self.description
        )

        patterns = [
            r"(Helio\s+[A-Za-z0-9+\-]+)",
            r"(Snapdragon\s+[A-Za-z0-9+\- ]+)",
            r"(Dimensity\s+[A-Za-z0-9+\- ]+)",
            r"(Exynos\s+[A-Za-z0-9+\- ]+)",
            r"(Tensor\s+[A-Za-z0-9+\- ]+)",
            r"(Kirin\s+[A-Za-z0-9+\- ]+)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                return self._clean(
                    match.group(1)
                )

        return None

    def _os(
        self,
    ) -> Optional[str]:

        value = self._spec(
            "Operating System",
            "OS",
            "Software",
        )

        if value:
            return value

        text = (
            self.product_name
            + " "
            + self.description
        )

        match = re.search(
            r"\b(Android\s+[0-9.]+)",
            text,
            re.IGNORECASE,
        )

        if match:
            return self._clean(
                match.group(1)
            )

        return None

    # ==================================================================
    # CAMERAS
    # ==================================================================

    def _camera_count(
        self,
    ) -> Optional[str]:

        value = self._spec(
            "Number Of Cameras",
            "Number of Cameras",
        )

        if value:
            return value

        text = (
            self.product_name
            + " "
            + self.description
        )

        match = re.search(
            r"\b(\d+)\s+cameras?\b",
            text,
            re.IGNORECASE,
        )

        if match:
            return (
                f"{match.group(1)} cameras"
            )

        return None

    def _main_camera(
        self,
    ) -> dict:

        megapixels = self._spec(
            "Camera Back (Megapixels)",
            "Rear Camera",
            "Main Camera",
            "Primary Camera",
        )

        if not megapixels:

            value = self._spec_contains(
                "camera back",
            )

            if value:
                megapixels = value

        if not megapixels:

            text = (
                self.product_name
                + " "
                + self.description
            )

            match = re.search(
                r"(\d+\s*MP"
                r"(?:\s*\+\s*\d+\s*MP)*)",
                text,
                re.IGNORECASE,
            )

            if match:
                megapixels = self._clean(
                    match.group(1)
                )

        camera_count = (
            self._camera_count()
        )

        if (
            megapixels
            and camera_count
        ):
            specifications = [
                f"{megapixels}; "
                f"{camera_count}"
            ]
        elif megapixels:
            specifications = [
                megapixels
            ]
        elif camera_count:
            specifications = [
                camera_count
            ]
        else:
            specifications = []

        features = self._spec(
            "Rear Camera Features",
            "Main Camera Features",
            "Camera Features",
        )

        video = self._spec(
            "Rear Camera Video",
            "Video Resolution",
            "Camera Video",
        )

        return {
            "Specifications": specifications,
            "Features": features,
            "Video": (
                self._split_values(video)
                if video
                else []
            ),
        }

    def _selfie_camera(
        self,
    ) -> dict:

        camera = self._spec(
            "Camera Front (Megapixels)",
            "Front Camera",
            "Selfie Camera",
        )

        if not camera:

            value = self._spec_contains(
                "camera front",
            )

            if value:
                camera = value

        features = self._spec(
            "Front Camera Features",
            "Selfie Camera Features",
        )

        video = self._spec(
            "Front Camera Video",
            "Selfie Camera Video",
        )

        return {
            "Specifications": (
                [camera]
                if camera
                else []
            ),
            "Features": features,
            "Video": (
                self._split_values(video)
                if video
                else []
            ),
        }

    # ==================================================================
    # BODY
    # ==================================================================

    def _body(
        self,
    ) -> dict:

        dimensions = self._spec(
            "Dimensions",
            "Product Dimensions",
        )

        weight = self._spec(
            "Weight",
            "Product Weight",
        )

        build = self._spec(
            "Build",
            "Body Material",
            "Material",
        )

        sim = self._spec(
            "SIM Type",
            "SIM",
            "Sim Type",
        )

        protection = self._spec(
            "Protection",
            "IP Rating",
            "Water Resistance",
        )

        return {
            "Dimensions": dimensions,
            "Weight": weight,
            "Build": build,
            "SIM": sim,
            "Protection": protection,
        }

    # ==================================================================
    # NETWORK
    # ==================================================================

    def _network(
        self,
    ) -> dict:

        values = []

        for label in [
            "Network Type",
            "Network",
            "Network Technology",
            "5G Support",
            "4G",
            "4G LTE",
            "3G",
            "2G",
        ]:

            value = self._spec(
                label
            )

            if value:
                values.append(
                    value
                )

        values.extend(
            [
                self.product_name,
                self.description,
            ]
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
    # DISPLAY
    # ==================================================================

    def _display(
        self,
    ) -> dict:

        return {
            "Type": self._display_type(),

            "Size": self._display_size(),

            "Resolution": (
                self._display_resolution()
            ),

            "Protection": self._spec(
                "Display Protection",
                "Screen Protection",
            ),
        }

    # ==================================================================
    # PLATFORM
    # ==================================================================

    def _platform(
        self,
    ) -> dict:

        return {
            "OS": self._os(),

            "Chipset": self._chipset(),

            "CPU": self._spec(
                "CPU",
                "CPU Type",
                "Processor Type",
            ),

            "GPU": self._spec(
                "GPU",
                "Graphics Processor",
            ),
        }

    # ==================================================================
    # MEMORY
    # ==================================================================

    def _memory(
        self,
    ) -> dict:

        ram = self._ram()

        storage = self._storage()

        card_slot = self._spec(
            "Memory Card Slot",
            "Card Slot",
            "Expandable Storage",
        )

        technology = self._spec(
            "Memory Technology",
            "Storage Technology",
        )

        types = []

        if ram and storage:

            types.append(
                f"{ram} / {storage}"
            )

        elif ram:

            types.append(
                ram
            )

        elif storage:

            types.append(
                storage
            )

        return {
            "Card slot": card_slot,
            "Types": types,
            "Technology": technology,
        }

    # ==================================================================
    # SOUND
    # ==================================================================

    def _sound(
        self,
    ) -> dict:

        speaker = self._spec(
            "Loudspeaker",
            "Speaker",
        )

        jack = self._spec(
            "3.5mm Jack",
            "Headphone Jack",
            "Headphone Port",
        )

        return {
            "Loudspeaker": speaker,

            "3.5mm jack": self._bits(
                jack
            ),
        }

    # ==================================================================
    # FEATURES
    # ==================================================================

    def _fingerprint(
        self,
    ) -> Optional[str]:

        value = self._spec(
            "Fingerprint",
            "Fingerprint Sensor",
            "Biometric",
        )

        if value:
            return value

        text = (
            self.product_name
            + " "
            + self.description
        ).lower()

        if "fingerprint" in text:
            return "Fingerprint sensor"

        return None

    def _features(
        self,
    ) -> dict:

        wlan = self._spec(
            "Wi-Fi",
            "WiFi",
            "WLAN",
        )

        bluetooth = self._spec(
            "Bluetooth",
        )

        positioning = self._spec(
            "GPS",
            "Positioning",
            "Navigation",
        )

        nfc = self._spec(
            "NFC",
            "NFC Support",
        )

        infrared = self._spec(
            "Infrared",
            "Infrared Port",
            "IR Blaster",
        )

        radio = self._spec(
            "FM Radio",
            "Radio",
        )

        usb = self._spec(
            "USB",
            "USB Type",
            "Charging Port",
        )

        sensors = self._spec(
            "Sensors",
            "Sensor",
        )

        fingerprint = (
            self._fingerprint()
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

    def _battery(
        self,
    ) -> dict:

        capacity = self._spec(
            "Battery Capacity",
            "Battery",
            "Capacity",
        )

        if not capacity:

            text = (
                self.product_name
                + " "
                + self.description
            )

            match = re.search(
                r"(\d{3,5}\s*mAh)",
                text,
                re.IGNORECASE,
            )

            if match:

                capacity = self._clean(
                    match.group(1)
                )

        wireless = self._spec(
            "Wireless Charging",
            "Wireless Charging Support",
        )

        charging = self._spec(
            "Fast Charging",
            "Charging",
            "Charging Technology",
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

    def _colors(
        self,
    ) -> List[str]:

        value = self._spec(
            "Color Family",
            "Color",
            "Colour",
            "Colors",
        )

        if not value:
            return []

        return self._split_values(
            value
        )

    # ==================================================================
    # LAUNCH
    # ==================================================================

    def _launch(
        self,
    ) -> dict:

        year = self._spec(
            "Year",
            "Release Year",
            "Launch Year",
        )

        announced = self._spec(
            "Announced",
            "Announcement Date",
        )

        return {
            "Announced": announced,

            "Status": (
                f"Available (Model year {year})"
                if year
                else "Available"
            ),
        }

    # ==================================================================
    # FINAL TEMPLATE
    # ==================================================================

    def to_template(
        self,
        raw: Optional[dict] = None,
    ) -> dict:

        name = self.product_name

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

            "Main Camera": (
                self._main_camera()
            ),

            "Selfie Camera": (
                self._selfie_camera()
            ),

            "Sound": self._sound(),

            "Features": self._features(),

            "Battery": self._battery(),

            "Colors": self._colors(),

            "Weight": self._spec(
                "SAR",
                "SAR Value",
            ),

            "Price": self._price(),
        }


if __name__ == "__main__":
    raise SystemExit(
        "This file is a scraper module. "
        "Run backend/navigation_to_page/www.daraz.pk.py instead."
    )