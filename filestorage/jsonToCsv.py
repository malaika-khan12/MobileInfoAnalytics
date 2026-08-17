#!/usr/bin/env python3
"""Convert normalized phone JSON files into a lossless CSV hierarchy.

The navigators save only the common template, not ``source_url``.  This module
therefore recovers the URL using the exact output-filename rules implemented by
the navigators.  Filtered manifests and catalog discovery files take priority;
deterministic reconstruction is used only where the filename preserves the
complete product path.  Mega.pk is intentionally never guessed because its
numeric path component is not present in the JSON filename.

The canonical ``<schema>/records.csv`` files are the input consumed by
``csvToDataBase.py``.  Per-table CSV files are also emitted for inspection,
object-storage query engines, and future warehouse COPY jobs.  ``record_key``
is a stable staging key and is not a database surrogate key.
"""

from __future__ import annotations

import argparse
import csv
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import unquote, urlparse, urlunparse


LOG = logging.getLogger("jsonToCsv")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "filestorage" / "mobiles"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "filestorage" / "csvs"
DEFAULT_FILESTORAGE_ROOT = PROJECT_ROOT / "filestorage"

INVALID_WINDOWS_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
GSMARENA_PRODUCT = re.compile(
    r"^(?P<slug>[a-z0-9][a-z0-9_()+.,%'-]*)-(?P<id>[0-9]+)\.php$",
    re.IGNORECASE,
)
GSMARENA_NON_PRODUCT = re.compile(
    r"-(?:phones?|reviews?|pictures?|opinions?|prices?|videos?|"
    r"related|compare|news)-",
    re.IGNORECASE,
)
DARAZ_PRODUCT = re.compile(
    r"^/products/[^/?#]+-i\d+(?:-s\d+)?\.html/?$",
    re.IGNORECASE,
)
MEGA_PRODUCT = re.compile(
    r"^/mobiles_products/\d+/[^/?#]+\.html/?$",
    re.IGNORECASE,
)
MYMOBILE_PRODUCT = re.compile(r"^/products/[^/?#]+/?$", re.IGNORECASE)
WHATAMOBILE_PRODUCT = re.compile(r"^/product/[^/?#]+/?$", re.IGNORECASE)
WHATMOBILE_PRODUCT = re.compile(
    r"^[A-Za-z][A-Za-z0-9']*_[A-Za-z0-9][A-Za-z0-9_]*-"
    r"[A-Za-z0-9][A-Za-z0-9-]*$"
)

SCHEMA_ORDER = (
    "original",
    "daraz",
    "mymobile",
    "mega",
    "whatamobile",
    "whatmobile",
)


@dataclass(frozen=True)
class SiteConfig:
    site: str
    schema: str
    filename_prefix: str
    preferred_host: str

    def output_filename(self, url: str) -> str:
        name = unquote(Path(urlparse(url).path.rstrip("/")).name)
        name = INVALID_WINDOWS_FILENAME.sub("_", name).rstrip(". ")
        if not name:
            raise ValueError(f"Cannot derive an output filename from {url!r}")
        return f"{self.filename_prefix}__{name}.json"

    def is_product_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return False
        if canonical_site(parsed.netloc) != self.site:
            return False
        path = unquote(parsed.path)
        filename = Path(path).name
        if self.schema == "original":
            match = GSMARENA_PRODUCT.fullmatch(filename)
            return bool(
                match
                and "_" in match.group("slug")
                and not GSMARENA_NON_PRODUCT.search(filename)
                and not parsed.query
                and not parsed.fragment
            )
        if self.schema == "daraz":
            return bool(DARAZ_PRODUCT.fullmatch(path) and not parsed.fragment)
        if self.schema == "mega":
            return bool(
                MEGA_PRODUCT.fullmatch(path)
                and not parsed.query
                and not parsed.fragment
            )
        if self.schema == "mymobile":
            return bool(
                MYMOBILE_PRODUCT.fullmatch(path)
                and not parsed.query
                and not parsed.fragment
            )
        if self.schema == "whatamobile":
            return bool(
                WHATAMOBILE_PRODUCT.fullmatch(path)
                and not parsed.query
                and not parsed.fragment
            )
        if self.schema == "whatmobile":
            return bool(
                WHATMOBILE_PRODUCT.fullmatch(filename)
                and not parsed.query
                and not parsed.fragment
            )
        return False

    def fallback_url(self, json_filename: str) -> str | None:
        marker = f"{self.filename_prefix}__"
        if not json_filename.startswith(marker) or not json_filename.endswith(".json"):
            return None
        leaf = json_filename[len(marker) : -len(".json")]
        if not leaf:
            return None
        if self.schema == "original":
            return f"https://{self.preferred_host}/{leaf}"
        if self.schema == "daraz":
            return f"https://{self.preferred_host}/products/{leaf}"
        if self.schema == "mymobile":
            return f"https://{self.preferred_host}/products/{leaf}/"
        if self.schema == "whatamobile":
            return f"https://{self.preferred_host}/product/{leaf}/"
        if self.schema == "whatmobile":
            return f"https://{self.preferred_host}/{leaf}"
        # Mega filenames omit /mobiles_products/<numeric-id>/.  Guessing it
        # would silently corrupt source lineage, so a manifest is mandatory.
        return None


SITE_CONFIGS: dict[str, SiteConfig] = {
    "gsmarena.com": SiteConfig(
        "gsmarena.com", "original", "gsmarena", "www.gsmarena.com"
    ),
    "daraz.pk": SiteConfig("daraz.pk", "daraz", "daraz", "www.daraz.pk"),
    "mymobile.pk": SiteConfig("mymobile.pk", "mymobile", "mymobile", "mymobile.pk"),
    "mega.pk": SiteConfig("mega.pk", "mega", "mega", "www.mega.pk"),
    "whatamobile.com.pk": SiteConfig(
        "whatamobile.com.pk",
        "whatamobile",
        "whatamobile",
        "www.whatamobile.com.pk",
    ),
    "whatmobile.com.pk": SiteConfig(
        "whatmobile.com.pk",
        "whatmobile",
        "whatmobile",
        "www.whatmobile.com.pk",
    ),
}

RECORD_FIELDS = [
    "record_key",
    "source_schema",
    "source_site",
    "source_file",
    "source_url",
    "url_recovery",
    "data_snapshot",
    "mobile_name",
    "network_2g",
    "network_3g",
    "network_4g",
    "network_5g",
    "launch_announced",
    "launch_status",
    "body_dimensions",
    "body_weight",
    "body_build",
    "body_sim",
    "body_protection",
    "display_type",
    "display_size",
    "display_resolution",
    "display_protection",
    "platform_os",
    "platform_chipset",
    "platform_cpu",
    "platform_gpu",
    "memory_card_slot",
    "memory_types_json",
    "memory_technology",
    "main_camera_specifications_json",
    "main_camera_features",
    "main_camera_video_json",
    "selfie_camera_specifications_json",
    "selfie_camera_features",
    "selfie_camera_video_json",
    "sound_loudspeaker",
    "sound_cable_jack",
    "features_wlan",
    "features_bluetooth",
    "features_positioning",
    "features_nfc",
    "features_infrared_port",
    "features_radio",
    "features_usb",
    "features_back_finger_print",
    "features_side_finger_print",
    "features_in_display_finger_print",
    "features_sensors",
    "battery_capacity",
    "battery_wireless_charging",
    "battery_charging_json",
    "colors_json",
    "exposure_weight",
    "prices_json",
    "completeness_score",
    "file_sha256",
    "payload_json",
]

TABLE_FIELDS: dict[str, list[str]] = {
    "entity": [
        "record_key",
        "data_snapshot",
        "name",
        "url",
        "sound_loudspeaker",
        "sound_cable_jack",
        "colors_json",
        "weight",
        "price_json",
        "source_file",
        "file_sha256",
        "completeness_score",
    ],
    "central_info": [
        "record_key",
        "product_id",
        "instance_number",
        "match_status",
    ],
    "network": ["record_key", "2g", "3g", "4g", "5g"],
    "launch": ["record_key", "announced", "status"],
    "body": [
        "record_key",
        "dimensions",
        "weight",
        "build",
        "sim",
        "protection",
    ],
    "display": ["record_key", "type", "size", "resolution", "protection"],
    "platform": ["record_key", "os", "chipset", "cpu", "gpu"],
    "memory": ["record_key", "card_slot", "technology", "types_json"],
    "camera_back": [
        "record_key",
        "specifications_json",
        "features",
        "video_json",
    ],
    "camera_front": [
        "record_key",
        "specifications_json",
        "features",
        "video_json",
    ],
    "features": [
        "record_key",
        "wlan",
        "bluetooth",
        "positioning",
        "nfc",
        "infrared_port",
        "radio",
        "usb",
        "back_finger_print",
        "side_finger_print",
        "in_display_finger_print",
        "sensors",
    ],
    "battery": [
        "record_key",
        "capacity",
        "wireless_charging",
        "charging_json",
    ],
    "raw_ingest": [
        "record_key",
        "source_schema",
        "source_url",
        "source_file",
        "data_snapshot",
        "file_sha256",
        "payload_json",
    ],
}

MANIFEST_RECORD_FIELDS = [
    "record_key",
    "source_schema",
    "source_site",
    "source_file",
    "source_url",
    "url_recovery",
    "data_snapshot",
    "mobile_name",
    "file_sha256",
    "completeness_score",
]
ERROR_FIELDS = ["source_site", "source_file", "error_code", "error_message"]


class ConversionError(ValueError):
    """A bad input record that should be quarantined instead of guessed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_site(value: str) -> str:
    host = value.lower().split("@")[-1].split(":")[0]
    return re.sub(r"^www\.", "", host)


def canonicalize_url(url: str, config: SiteConfig) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ConversionError("INVALID_URL", f"Not an HTTP(S) URL: {url!r}")
    if canonical_site(parsed.netloc) != config.site:
        raise ConversionError(
            "WRONG_URL_SITE",
            f"URL {url!r} does not belong to {config.site}",
        )
    return urlunparse(
        (
            "https",
            config.preferred_host,
            parsed.path,
            "",
            "",
            "",
        )
    )


def iter_http_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            yield value
        return
    if isinstance(value, Mapping):
        for child in value.values():
            yield from iter_http_strings(child)
        return
    if isinstance(value, list):
        for child in value:
            yield from iter_http_strings(child)


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConversionError("INVALID_JSON", f"{path}: {exc}") from exc


class UrlResolver:
    def __init__(
        self,
        config: SiteConfig,
        site_directory: Path,
        filestorage_root: Path,
    ) -> None:
        self.config = config
        self.site_directory = site_directory
        self.filestorage_root = filestorage_root
        self.by_filename: dict[str, set[str]] = {}
        self.index_sources: list[str] = []
        self._build_index()

    def _candidate_files(self) -> Iterator[Path]:
        manifest = self.filestorage_root / "sitemap_mobile" / f"{self.config.site}.json"
        if manifest.is_file():
            yield manifest
        for name in (
            "_catalog_discovery.json",
            "_catalog_coverage.json",
            "_crawl_summary.json",
        ):
            path = self.site_directory / name
            if path.is_file():
                yield path

    def _build_index(self) -> None:
        for path in self._candidate_files():
            try:
                payload = read_json(path)
            except ConversionError as exc:
                LOG.warning("Ignoring URL index file %s: %s", path, exc)
                continue
            found = 0
            for candidate in iter_http_strings(payload):
                if not self.config.is_product_url(candidate):
                    continue
                try:
                    normalized = canonicalize_url(candidate, self.config)
                    filename = self.config.output_filename(normalized)
                except (ConversionError, ValueError):
                    continue
                self.by_filename.setdefault(filename, set()).add(normalized)
                found += 1
            if found:
                self.index_sources.append(str(path))

    @staticmethod
    def _explicit_url(payload: Mapping[str, Any]) -> str | None:
        for key in ("source_url", "SourceURL", "sourceUrl", "url", "URL"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        metadata = payload.get("_metadata")
        if isinstance(metadata, Mapping):
            for key in ("source_url", "url"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def resolve(self, json_path: Path, payload: Mapping[str, Any]) -> tuple[str, str]:
        explicit = self._explicit_url(payload)
        if explicit:
            normalized = canonicalize_url(explicit, self.config)
            if not self.config.is_product_url(normalized):
                raise ConversionError(
                    "NON_PRODUCT_URL",
                    f"Embedded URL is not a recognized {self.config.site} product: {explicit}",
                )
            return normalized, "payload"

        candidates = self.by_filename.get(json_path.name, set())
        if len(candidates) == 1:
            return next(iter(candidates)), "manifest"
        if len(candidates) > 1:
            choices = ", ".join(sorted(candidates))
            raise ConversionError(
                "AMBIGUOUS_URL",
                f"{json_path.name} maps to multiple product URLs: {choices}",
            )

        fallback = self.config.fallback_url(json_path.name)
        if fallback:
            normalized = canonicalize_url(fallback, self.config)
            if self.config.is_product_url(normalized):
                return normalized, "filename"

        raise ConversionError(
            "UNRESOLVED_URL",
            f"Cannot safely recover the source URL for {json_path.name}; "
            f"provide it in the payload or the filtered/catalog manifest",
        )


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def section(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = payload.get(name)
    return value if isinstance(value, Mapping) else {}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return compact_json(value)
    return str(value).strip()


def bool_text(value: Any, default: bool) -> str:
    if value is None:
        return "true" if default else "false"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return "true" if value != 0 else "false"
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on", "supported"}:
        return "true"
    if normalized in {"0", "false", "f", "no", "n", "off", "none"}:
        return "false"
    return "true" if default else "false"


def list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item is not None]
    return [value]


def price_values(value: Any) -> list[int | float]:
    output: list[int | float] = []
    for item in list_value(value):
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)) and item > 0:
            output.append(item)
            continue
        match = re.search(r"[-+]?[0-9]+(?:\.[0-9]+)?", str(item).replace(",", ""))
        if not match:
            continue
        number = float(match.group(0))
        if number > 0:
            output.append(int(number) if number.is_integer() else number)
    return output


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def completeness(payload: Mapping[str, Any]) -> float:
    launch = section(payload, "Launch")
    body = section(payload, "Body")
    display = section(payload, "Display")
    platform = section(payload, "Platform")
    memory = section(payload, "Memory")
    main_camera = section(payload, "Main Camera")
    selfie_camera = section(payload, "Selfie Camera")
    features = section(payload, "Features")
    battery = section(payload, "Battery")
    values = [
        payload.get("MobileName"),
        launch.get("Announced"),
        launch.get("Status"),
        body.get("Dimensions"),
        body.get("Weight"),
        display.get("Type"),
        display.get("Size"),
        display.get("Resolution"),
        platform.get("OS"),
        platform.get("Chipset"),
        platform.get("CPU"),
        platform.get("GPU"),
        memory.get("Types"),
        main_camera.get("Specifications"),
        selfie_camera.get("Specifications"),
        features.get("WLAN"),
        features.get("Bluetooth"),
        features.get("USB"),
        features.get("Sensors"),
        battery.get("Capacity"),
        battery.get("Charging"),
        payload.get("Colors"),
        payload.get("Weight"),
        payload.get("Price"),
    ]
    return round(sum(has_value(item) for item in values) / len(values), 5)


def parse_snapshot(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def snapshot_for(path: Path, override: datetime | None) -> str:
    timestamp = override or datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    )
    return timestamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_phone_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConversionError("INVALID_JSON", f"{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConversionError(
            "INVALID_PAYLOAD", f"{path}: top-level JSON must be an object"
        )
    if not clean_text(payload.get("MobileName")):
        raise ConversionError("MISSING_NAME", f"{path}: MobileName is required")
    return payload, raw


def flatten_record(
    payload: Mapping[str, Any],
    *,
    config: SiteConfig,
    source_file: str,
    source_url: str,
    url_recovery: str,
    data_snapshot: str,
    file_sha256: str,
) -> dict[str, str]:
    network = section(payload, "Network")
    launch = section(payload, "Launch")
    body = section(payload, "Body")
    display = section(payload, "Display")
    platform = section(payload, "Platform")
    memory = section(payload, "Memory")
    main_camera = section(payload, "Main Camera")
    selfie_camera = section(payload, "Selfie Camera")
    sound = section(payload, "Sound")
    features = section(payload, "Features")
    battery = section(payload, "Battery")
    record_key = hashlib.sha256(
        f"{config.schema}\0{source_url}".encode("utf-8")
    ).hexdigest()
    prices = price_values(payload.get("Price"))
    return {
        "record_key": record_key,
        "source_schema": config.schema,
        "source_site": config.site,
        "source_file": source_file,
        "source_url": source_url,
        "url_recovery": url_recovery,
        "data_snapshot": data_snapshot,
        "mobile_name": clean_text(payload.get("MobileName")),
        "network_2g": bool_text(network.get("2G"), True),
        "network_3g": bool_text(network.get("3G"), True),
        "network_4g": bool_text(network.get("4G"), False),
        "network_5g": bool_text(network.get("5G"), True),
        "launch_announced": clean_text(launch.get("Announced")),
        "launch_status": clean_text(launch.get("Status")),
        "body_dimensions": clean_text(body.get("Dimensions")),
        "body_weight": clean_text(body.get("Weight")),
        "body_build": clean_text(body.get("Build")),
        "body_sim": clean_text(body.get("SIM")),
        "body_protection": clean_text(body.get("Protection")),
        "display_type": clean_text(display.get("Type")),
        "display_size": clean_text(display.get("Size")),
        "display_resolution": clean_text(display.get("Resolution")),
        "display_protection": clean_text(display.get("Protection")),
        "platform_os": clean_text(platform.get("OS")),
        "platform_chipset": clean_text(platform.get("Chipset")),
        "platform_cpu": clean_text(platform.get("CPU")),
        "platform_gpu": clean_text(platform.get("GPU")),
        "memory_card_slot": clean_text(memory.get("Card slot")),
        "memory_types_json": compact_json(list_value(memory.get("Types"))),
        "memory_technology": clean_text(memory.get("Technology")),
        "main_camera_specifications_json": compact_json(
            list_value(main_camera.get("Specifications"))
        ),
        "main_camera_features": clean_text(main_camera.get("Features")),
        "main_camera_video_json": compact_json(list_value(main_camera.get("Video"))),
        "selfie_camera_specifications_json": compact_json(
            list_value(selfie_camera.get("Specifications"))
        ),
        "selfie_camera_features": clean_text(selfie_camera.get("Features")),
        "selfie_camera_video_json": compact_json(
            list_value(selfie_camera.get("Video"))
        ),
        "sound_loudspeaker": clean_text(sound.get("Loudspeaker")),
        "sound_cable_jack": bool_text(sound.get("3.5mm jack"), True),
        "features_wlan": clean_text(features.get("WLAN")),
        "features_bluetooth": clean_text(features.get("Bluetooth")),
        "features_positioning": clean_text(features.get("Positioning")),
        "features_nfc": bool_text(features.get("NFC"), False),
        "features_infrared_port": bool_text(features.get("Infrared port"), False),
        "features_radio": bool_text(features.get("Radio"), True),
        "features_usb": clean_text(features.get("USB")),
        "features_back_finger_print": bool_text(features.get("BackFingerPrint"), False),
        "features_side_finger_print": bool_text(features.get("SideFingerPrint"), False),
        "features_in_display_finger_print": bool_text(
            features.get("InDisplayFingerPrint"), False
        ),
        "features_sensors": clean_text(features.get("Sensors")),
        "battery_capacity": clean_text(battery.get("Capacity")),
        "battery_wireless_charging": bool_text(battery.get("WirelessCharging"), False),
        "battery_charging_json": compact_json(list_value(battery.get("Charging"))),
        "colors_json": compact_json(list_value(payload.get("Colors"))),
        "exposure_weight": clean_text(payload.get("Weight")) or "Weight Unknown",
        "prices_json": compact_json(prices),
        "completeness_score": f"{completeness(payload):.5f}",
        "file_sha256": file_sha256,
        "payload_json": compact_json(payload),
    }


def normalized_rows(flat: Mapping[str, str], schema: str) -> dict[str, dict[str, str]]:
    key = flat["record_key"]
    entity_name = "central_info" if schema == "original" else "secondary_info"
    rows: dict[str, dict[str, str]] = {
        entity_name: {
            "record_key": key,
            "data_snapshot": flat["data_snapshot"],
            "name": flat["mobile_name"],
            "url": flat["source_url"],
            "sound_loudspeaker": flat["sound_loudspeaker"],
            "sound_cable_jack": flat["sound_cable_jack"],
            "colors_json": flat["colors_json"],
            "weight": flat["exposure_weight"],
            "price_json": flat["prices_json"],
            "source_file": flat["source_file"],
            "file_sha256": flat["file_sha256"],
            "completeness_score": flat["completeness_score"],
        },
        "network": {
            "record_key": key,
            "2g": flat["network_2g"],
            "3g": flat["network_3g"],
            "4g": flat["network_4g"],
            "5g": flat["network_5g"],
        },
        "launch": {
            "record_key": key,
            "announced": flat["launch_announced"],
            "status": flat["launch_status"],
        },
        "body": {
            "record_key": key,
            "dimensions": flat["body_dimensions"],
            "weight": flat["body_weight"],
            "build": flat["body_build"],
            "sim": flat["body_sim"],
            "protection": flat["body_protection"],
        },
        "display": {
            "record_key": key,
            "type": flat["display_type"],
            "size": flat["display_size"],
            "resolution": flat["display_resolution"],
            "protection": flat["display_protection"],
        },
        "platform": {
            "record_key": key,
            "os": flat["platform_os"],
            "chipset": flat["platform_chipset"],
            "cpu": flat["platform_cpu"],
            "gpu": flat["platform_gpu"],
        },
        "memory": {
            "record_key": key,
            "card_slot": flat["memory_card_slot"],
            "technology": flat["memory_technology"],
            "types_json": flat["memory_types_json"],
        },
        "camera_back": {
            "record_key": key,
            "specifications_json": flat["main_camera_specifications_json"],
            "features": flat["main_camera_features"],
            "video_json": flat["main_camera_video_json"],
        },
        "camera_front": {
            "record_key": key,
            "specifications_json": flat["selfie_camera_specifications_json"],
            "features": flat["selfie_camera_features"],
            "video_json": flat["selfie_camera_video_json"],
        },
        "features": {
            "record_key": key,
            "wlan": flat["features_wlan"],
            "bluetooth": flat["features_bluetooth"],
            "positioning": flat["features_positioning"],
            "nfc": flat["features_nfc"],
            "infrared_port": flat["features_infrared_port"],
            "radio": flat["features_radio"],
            "usb": flat["features_usb"],
            "back_finger_print": flat["features_back_finger_print"],
            "side_finger_print": flat["features_side_finger_print"],
            "in_display_finger_print": flat["features_in_display_finger_print"],
            "sensors": flat["features_sensors"],
        },
        "battery": {
            "record_key": key,
            "capacity": flat["battery_capacity"],
            "wireless_charging": flat["battery_wireless_charging"],
            "charging_json": flat["battery_charging_json"],
        },
        "raw_ingest": {
            "record_key": key,
            "source_schema": flat["source_schema"],
            "source_url": flat["source_url"],
            "source_file": flat["source_file"],
            "data_snapshot": flat["data_snapshot"],
            "file_sha256": flat["file_sha256"],
            "payload_json": flat["payload_json"],
        },
    }
    if schema != "original":
        rows["central_info"] = {
            "record_key": key,
            "product_id": "",
            "instance_number": "",
            "match_status": "unmatched_or_exact_match_at_load",
        }
    return rows


class AtomicCsvHierarchy:
    def __init__(self, output_dir: Path, schemas: Sequence[str]) -> None:
        self.output_dir = output_dir
        self.schemas = tuple(schemas)
        self.stack = ExitStack()
        self.writers: dict[tuple[str, str], csv.DictWriter] = {}
        self.temp_files: list[tuple[Path, Path]] = []
        self.files: list[str] = []

    def __enter__(self) -> "AtomicCsvHierarchy":
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for schema in self.schemas:
            self._open(schema, "records", RECORD_FIELDS)
            entity_name = "central_info" if schema == "original" else "secondary_info"
            self._open(schema, entity_name, TABLE_FIELDS["entity"])
            if schema != "original":
                self._open(schema, "central_info", TABLE_FIELDS["central_info"])
            for table, fields in TABLE_FIELDS.items():
                if table in {"entity", "central_info"}:
                    continue
                self._open(schema, table, fields)
        self._open("_manifest", "records", MANIFEST_RECORD_FIELDS)
        self._open("_manifest", "errors", ERROR_FIELDS)
        return self

    def _open(self, schema: str, table: str, fields: Sequence[str]) -> None:
        directory = self.output_dir / schema
        directory.mkdir(parents=True, exist_ok=True)
        final_path = directory / f"{table}.csv"
        temp_path = directory / f".{table}.csv.{os.getpid()}.tmp"
        handle = self.stack.enter_context(
            temp_path.open("w", encoding="utf-8", newline="")
        )
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="raise")
        writer.writeheader()
        self.writers[(schema, table)] = writer
        self.temp_files.append((temp_path, final_path))
        self.files.append(final_path.relative_to(self.output_dir).as_posix())

    def write_record(self, schema: str, flat: Mapping[str, str]) -> None:
        self.writers[(schema, "records")].writerow(flat)
        for table, row in normalized_rows(flat, schema).items():
            self.writers[(schema, table)].writerow(row)
        manifest_row = {field: flat[field] for field in MANIFEST_RECORD_FIELDS}
        self.writers[("_manifest", "records")].writerow(manifest_row)

    def write_error(self, row: Mapping[str, str]) -> None:
        self.writers[("_manifest", "errors")].writerow(row)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self.stack.close()
        if exc_type is None:
            for temp_path, final_path in self.temp_files:
                os.replace(temp_path, final_path)
        else:
            for temp_path, _ in self.temp_files:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
        return False


def site_for_directory(path: Path) -> str:
    return canonical_site(path.name)


def discover_inputs(
    input_dir: Path,
    selected_sites: set[str] | None,
) -> list[tuple[Path, str, SiteConfig]]:
    discovered: list[tuple[Path, str, SiteConfig]] = []
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    for site_directory in sorted(path for path in input_dir.iterdir() if path.is_dir()):
        site = site_for_directory(site_directory)
        if selected_sites is not None and site not in selected_sites:
            continue
        config = SITE_CONFIGS.get(site)
        for path in sorted(site_directory.glob("*.json")):
            if path.name.startswith("_"):
                continue
            if config is None:
                # Keep unsupported files visible to the quarantine path.
                discovered.append(
                    (path, site, SiteConfig(site, "", "", site_directory.name))
                )
            else:
                discovered.append((path, site, config))
    return discovered


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def display_path(path: Path) -> str:
    """Prefer a repository-relative path in persistent manifests."""

    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def upload_tree(output_dir: Path, archive_uri: str) -> int:
    parsed = urlparse(archive_uri)
    files = sorted(path for path in output_dir.rglob("*") if path.is_file())
    # Upload manifest last so its presence means every referenced object was
    # attempted first.
    files.sort(key=lambda path: path.name == "manifest.json")
    if parsed.scheme == "s3":
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "S3 archival requires boto3 (install requirements.txt)"
            ) from exc
        bucket = parsed.netloc
        if not bucket:
            raise ValueError("S3 URI must be s3://bucket/optional-prefix")
        prefix = parsed.path.strip("/")
        client = boto3.client("s3")
        for path in files:
            relative = path.relative_to(output_dir).as_posix()
            key = "/".join(part for part in (prefix, relative) if part)
            client.upload_file(str(path), bucket, key)
        return len(files)

    if parsed.scheme in {"az", "azure"}:
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Azure archival requires azure-storage-blob (install requirements.txt)"
            ) from exc
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is required")
        container = parsed.netloc
        if not container:
            raise ValueError("Azure URI must be az://container/optional-prefix")
        prefix = parsed.path.strip("/")
        service = BlobServiceClient.from_connection_string(connection_string)
        container_client = service.get_container_client(container)
        try:
            container_client.create_container()
        except Exception as exc:  # Azure raises ResourceExistsError by subtype.
            if (
                "ContainerAlreadyExists" not in type(exc).__name__
                and "exists" not in str(exc).lower()
            ):
                raise
        for path in files:
            relative = path.relative_to(output_dir).as_posix()
            blob_name = "/".join(part for part in (prefix, relative) if part)
            with path.open("rb") as handle:
                container_client.upload_blob(blob_name, handle, overwrite=True)
        return len(files)

    raise ValueError("--archive-uri must use s3://, az://, or azure://")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stream normalized phone JSON files into canonical and per-table CSVs."
        )
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--filestorage-root",
        type=Path,
        default=DEFAULT_FILESTORAGE_ROOT,
        help="Directory containing sitemap_mobile/ and mobiles/.",
    )
    parser.add_argument(
        "--site",
        action="append",
        default=[],
        help="Process only this site (repeatable; www. is optional).",
    )
    parser.add_argument(
        "--snapshot-at",
        type=parse_snapshot,
        help="Override file modification times with an ISO-8601 UTC snapshot.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Stop at the first invalid record instead of writing errors.csv.",
    )
    parser.add_argument(
        "--archive-uri",
        help="After conversion upload csvs/ to s3://bucket/prefix or az://container/prefix.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def run_conversion(args: argparse.Namespace) -> dict[str, Any]:
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    filestorage_root = args.filestorage_root.resolve()
    selected_sites = (
        {
            canonical_site(
                value.replace("https://", "").replace("http://", "").split("/")[0]
            )
            for value in args.site
        }
        if args.site
        else None
    )
    inputs = discover_inputs(input_dir, selected_sites)
    supported_schemas = sorted(
        {config.schema for _, _, config in inputs if config.schema},
        key=SCHEMA_ORDER.index,
    )
    resolvers: dict[str, UrlResolver] = {}
    counts_by_schema = {schema: 0 for schema in supported_schemas}
    processed = 0
    errors = 0
    recovery_counts: dict[str, int] = {}

    with AtomicCsvHierarchy(output_dir, supported_schemas) as outputs:
        for index, (path, site, config) in enumerate(inputs, start=1):
            relative = path.relative_to(input_dir).as_posix()
            try:
                if not config.schema:
                    raise ConversionError(
                        "UNSUPPORTED_SITE",
                        f"No database schema is defined for {site}",
                    )
                payload, raw = load_phone_json(path)
                resolver = resolvers.get(site)
                if resolver is None:
                    resolver = UrlResolver(config, path.parent, filestorage_root)
                    resolvers[site] = resolver
                    LOG.debug(
                        "%s URL index: %d filenames from %s",
                        site,
                        len(resolver.by_filename),
                        resolver.index_sources or "filename rules only",
                    )
                source_url, recovery = resolver.resolve(path, payload)
                flat = flatten_record(
                    payload,
                    config=config,
                    source_file=relative,
                    source_url=source_url,
                    url_recovery=recovery,
                    data_snapshot=snapshot_for(path, args.snapshot_at),
                    file_sha256=sha256_bytes(raw),
                )
                outputs.write_record(config.schema, flat)
                processed += 1
                counts_by_schema[config.schema] += 1
                recovery_counts[recovery] = recovery_counts.get(recovery, 0) + 1
                if index % 1000 == 0:
                    LOG.info("Processed %d/%d JSON files", index, len(inputs))
            except (ConversionError, OSError, ValueError) as exc:
                errors += 1
                code = (
                    exc.code if isinstance(exc, ConversionError) else "CONVERSION_ERROR"
                )
                LOG.error("%s: %s", relative, exc)
                outputs.write_error(
                    {
                        "source_site": site,
                        "source_file": relative,
                        "error_code": code,
                        "error_message": str(exc),
                    }
                )
                if args.strict:
                    raise

        output_files = list(outputs.files)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = {
        "format_version": 1,
        "generated_at": generated_at,
        "input_directory": display_path(input_dir),
        "output_directory": display_path(output_dir),
        "records_discovered": len(inputs),
        "records_written": processed,
        "records_rejected": errors,
        "records_by_schema": counts_by_schema,
        "url_recovery_counts": dict(sorted(recovery_counts.items())),
        "schemas": supported_schemas,
        "table_files": sorted(output_files),
        "source_contract": "filestorage/template.json",
    }
    atomic_write_json(output_dir / "_manifest" / "manifest.json", manifest)
    if args.archive_uri:
        uploaded = upload_tree(output_dir, args.archive_uri)
        manifest["archive_uri"] = args.archive_uri
        manifest["archive_files_uploaded"] = uploaded
        atomic_write_json(output_dir / "_manifest" / "manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        manifest = run_conversion(args)
    except Exception as exc:
        LOG.error("Conversion failed: %s", exc)
        if args.log_level == "DEBUG":
            LOG.exception("Detailed failure")
        return 1
    LOG.info(
        "CSV conversion complete: written=%d rejected=%d output=%s",
        manifest["records_written"],
        manifest["records_rejected"],
        manifest["output_directory"],
    )
    return 0 if manifest["records_rejected"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
