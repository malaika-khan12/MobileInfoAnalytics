from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


json_to_csv = load_module("json_to_csv_under_test", "filestorage/jsonToCsv.py")
csv_to_database = load_module(
    "csv_to_database_under_test", "filestorage/csvToDataBase.py"
)


def payload(name: str = "Test Phone") -> dict:
    return {
        "MobileName": name,
        "Network": {"2G": 1, "3G": 1, "4G": 1, "5G": 0},
        "Launch": {"Announced": "2026", "Status": "Available"},
        "Body": {
            "Dimensions": "1 x 2 x 3 mm",
            "Weight": "100 g",
            "Build": None,
            "SIM": "Nano-SIM",
            "Protection": None,
        },
        "Display": {
            "Type": "OLED",
            "Size": "6.5 inches",
            "Resolution": "1080 x 2400",
            "Protection": None,
        },
        "Platform": {
            "OS": "Android",
            "Chipset": "Example",
            "CPU": "Octa-core",
            "GPU": "Example GPU",
        },
        "Memory": {
            "Card slot": None,
            "Types": ["256GB 8GB RAM"],
            "Technology": "UFS",
        },
        "Main Camera": {
            "Specifications": ["50 MP"],
            "Features": "HDR",
            "Video": ["4K"],
        },
        "Selfie Camera": {
            "Specifications": ["12 MP"],
            "Features": "HDR",
            "Video": ["1080p"],
        },
        "Sound": {"Loudspeaker": "Yes", "3.5mm jack": 0},
        "Features": {
            "WLAN": "Wi-Fi",
            "Bluetooth": "5.4",
            "Positioning": "GPS",
            "NFC": 1,
            "Infrared port": 0,
            "Radio": 0,
            "USB": "USB-C",
            "BackFingerPrint": 0,
            "SideFingerPrint": 1,
            "InDisplayFingerPrint": 0,
            "Sensors": "Fingerprint",
        },
        "Battery": {
            "Capacity": "5000 mAh",
            "WirelessCharging": 0,
            "Charging": ["45W wired"],
        },
        "Colors": ["Black"],
        "Weight": None,
        "Price": ["Rs. 100,000", 99999.5],
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class JsonToCsvTests(unittest.TestCase):
    def test_manifest_url_and_table_hierarchy_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "filestorage"
            phones = storage / "mobiles" / "gsmarena.com"
            filename = "gsmarena__xiaomi_test_phone-123.php.json"
            write_json(phones / filename, payload("Xiaomi Test Phone"))
            product_url = "https://www.gsmarena.com/xiaomi_test_phone-123.php"
            write_json(
                storage / "sitemap_mobile" / "gsmarena.com.json",
                {"mobile_urls": [{"url": product_url}]},
            )
            output = storage / "csvs"

            status = json_to_csv.main(
                [
                    "--input-dir",
                    str(storage / "mobiles"),
                    "--output-dir",
                    str(output),
                    "--filestorage-root",
                    str(storage),
                    "--snapshot-at",
                    "2026-08-17T12:00:00+00:00",
                ]
            )
            self.assertEqual(status, 0)

            with (output / "original" / "records.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_url"], product_url)
            self.assertEqual(rows[0]["url_recovery"], "manifest")
            self.assertEqual(json.loads(rows[0]["prices_json"]), [100000, 99999.5])
            self.assertEqual(rows[0]["sound_cable_jack"], "false")
            self.assertEqual(rows[0]["exposure_weight"], "Weight Unknown")

            expected_tables = {
                "central_info.csv",
                "network.csv",
                "launch.csv",
                "body.csv",
                "display.csv",
                "platform.csv",
                "memory.csv",
                "camera_back.csv",
                "camera_front.csv",
                "features.csv",
                "battery.csv",
                "raw_ingest.csv",
                "records.csv",
            }
            self.assertEqual(
                {path.name for path in (output / "original").glob("*.csv")},
                expected_tables,
            )

    def test_mega_url_uses_numeric_path_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "filestorage"
            phones = storage / "mobiles" / "mega.pk"
            filename = "mega__Example-Phone.html.json"
            write_json(phones / filename, payload("Example Phone"))
            product_url = (
                "https://www.mega.pk/mobiles_products/23647/Example-Phone.html"
            )
            write_json(
                storage / "sitemap_mobile" / "mega.pk.json",
                {"mobile_urls": [{"url": product_url}]},
            )
            output = storage / "csvs"
            status = json_to_csv.main(
                [
                    "--input-dir",
                    str(storage / "mobiles"),
                    "--output-dir",
                    str(output),
                    "--filestorage-root",
                    str(storage),
                ]
            )
            self.assertEqual(status, 0)
            with (output / "mega" / "records.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["source_url"], product_url)
            self.assertEqual(row["url_recovery"], "manifest")

    def test_mega_url_is_rejected_instead_of_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "filestorage"
            write_json(
                storage / "mobiles" / "mega.pk" / "mega__Example-Phone.html.json",
                payload("Example Phone"),
            )
            output = storage / "csvs"
            status = json_to_csv.main(
                [
                    "--input-dir",
                    str(storage / "mobiles"),
                    "--output-dir",
                    str(output),
                    "--filestorage-root",
                    str(storage),
                ]
            )
            self.assertEqual(status, 2)
            with (output / "_manifest" / "errors.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                error = next(csv.DictReader(handle))
            self.assertEqual(error["error_code"], "UNRESOLVED_URL")

    def test_each_reconstructable_site_uses_navigator_filename_rule(self) -> None:
        examples = {
            "original": (
                "gsmarena__xiaomi_test_phone-123.php.json",
                "https://www.gsmarena.com/xiaomi_test_phone-123.php",
            ),
            "daraz": (
                "daraz__test-phone-i123456-s123.html.json",
                "https://www.daraz.pk/products/test-phone-i123456-s123.html",
            ),
            "mymobile": (
                "mymobile__test-phone.json",
                "https://mymobile.pk/products/test-phone/",
            ),
            "whatamobile": (
                "whatamobile__test-phone.json",
                "https://www.whatamobile.com.pk/product/test-phone/",
            ),
            "whatmobile": (
                "whatmobile__Samsung_Galaxy-S24.json",
                "https://www.whatmobile.com.pk/Samsung_Galaxy-S24",
            ),
        }
        configs = {item.schema: item for item in json_to_csv.SITE_CONFIGS.values()}
        for schema, (filename, expected) in examples.items():
            with self.subTest(schema=schema):
                self.assertEqual(configs[schema].fallback_url(filename), expected)
                self.assertTrue(configs[schema].is_product_url(expected))
        self.assertIsNone(configs["mega"].fallback_url("mega__Phone.html.json"))


class CsvToDatabaseTests(unittest.TestCase):
    def test_dry_run_validates_generated_records_without_psycopg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "filestorage"
            write_json(
                storage
                / "mobiles"
                / "gsmarena.com"
                / "gsmarena__xiaomi_test_phone-123.php.json",
                payload("Xiaomi Test Phone"),
            )
            output = storage / "csvs"
            self.assertEqual(
                json_to_csv.main(
                    [
                        "--input-dir",
                        str(storage / "mobiles"),
                        "--output-dir",
                        str(output),
                        "--filestorage-root",
                        str(storage),
                    ]
                ),
                0,
            )
            self.assertEqual(
                csv_to_database.main(["--csv-root", str(output), "--dry-run"]),
                0,
            )

    def test_sql_function_names_come_only_from_allowlist(self) -> None:
        for schema, function_name in csv_to_database.SCHEMA_FUNCTIONS.items():
            query = csv_to_database.query_for_schema(schema)
            self.assertIn(function_name, query)
            self.assertNotIn(schema + ";", query)
        with self.assertRaises(KeyError):
            csv_to_database.query_for_schema("original; drop schema original")


class SqlContractTests(unittest.TestCase):
    def test_schema_and_function_files_cover_every_required_source(self) -> None:
        schema_sql = (
            (PROJECT_ROOT / "db" / "schema_v1.sql").read_text(encoding="utf-8").lower()
        )
        function_sql = (
            (PROJECT_ROOT / "db" / "functions_v1.sql")
            .read_text(encoding="utf-8")
            .lower()
        )
        for schema in (
            "original",
            "daraz",
            "mymobile",
            "mega",
            "whatamobile",
            "whatmobile",
        ):
            self.assertIn(schema, schema_sql)
            self.assertIn(f"api.ingest_{schema}", function_sql)
        self.assertIn("warehouse.price_history", schema_sql)
        self.assertIn("warehouse.raw_ingest", schema_sql)
        self.assertIn("api.price_comparison", function_sql)
        self.assertIn("api.complete_listings", function_sql)
        self.assertIn("security definer", function_sql)


if __name__ == "__main__":
    unittest.main()
