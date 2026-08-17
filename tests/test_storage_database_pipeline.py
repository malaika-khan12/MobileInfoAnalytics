from __future__ import annotations

import csv
from datetime import date
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


def payload(
    name: str = "Test Phone",
    announced: object = "2026, February",
    status: object = "Available. Released 2026, February",
) -> dict:
    return {
        "MobileName": name,
        "Network": {"2G": 1, "3G": 1, "4G": 1, "5G": 0},
        "Launch": {"Announced": announced, "Status": status},
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


class SnapshotTests(unittest.TestCase):
    def test_all_attached_gsmarena_announced_shapes(self) -> None:
        examples = {
            "2024, July 03": ("2024", "07-03"),
            "2024, December": ("2024", "12"),
            "2024, October 27": ("2024", "10-27"),
            "2024, October 28": ("2024", "10-28"),
            "2026, February": ("2026", "02"),
            "2026, July": ("2026", "07"),
            "2023, August 10": ("2023", "08-10"),
            "2025, March 02": ("2025", "03-02"),
            "2026, July 03": ("2026", "07-03"),
        }
        for text, expected in examples.items():
            with self.subTest(value=text):
                self.assertEqual(
                    json_to_csv.parse_gsmarena_snapshot_text(text), expected
                )

    def test_announced_then_status_then_utc_fallback(self) -> None:
        announced = json_to_csv.snapshot_for_payload(
            payload(announced="2024, July 03"), "original", date(2030, 1, 2)
        )
        self.assertEqual(
            announced,
            json_to_csv.SnapshotValue("2024", "07-03", "announced"),
        )

        status = json_to_csv.snapshot_for_payload(
            payload(
                announced="Not announced yet",
                status="Available. Released 2024, July",
            ),
            "original",
            date(2030, 1, 2),
        )
        self.assertEqual(
            status, json_to_csv.SnapshotValue("2024", "07", "status")
        )

        fallback = json_to_csv.snapshot_for_payload(
            payload(announced=None, status="Discontinued"),
            "original",
            date(2030, 1, 2),
        )
        self.assertEqual(
            fallback,
            json_to_csv.SnapshotValue("2030", "01-02", "current_utc"),
        )

    def test_bad_announced_day_falls_through_atomically(self) -> None:
        value = json_to_csv.snapshot_for_payload(
            payload(
                announced="2024, February 31",
                status="Available. Released 2024, March",
            ),
            "original",
            date(2030, 1, 2),
        )
        self.assertEqual(value, json_to_csv.SnapshotValue("2024", "03", "status"))

    def test_marketplace_never_derives_its_own_snapshot(self) -> None:
        value = json_to_csv.snapshot_for_payload(
            payload(announced="1999, January 01"),
            "mega",
            date(2030, 1, 2),
        )
        self.assertEqual(
            value, json_to_csv.SnapshotValue("", "", "original_database")
        )


class JsonToCsvTests(unittest.TestCase):
    def test_unknown_price_uses_explicit_negative_one_sentinel(self) -> None:
        self.assertEqual(json_to_csv.price_values(None), [-1])
        self.assertEqual(json_to_csv.price_values("Price unavailable"), [-1])

    def test_manifest_url_snapshot_and_hierarchy_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Path(temporary) / "filestorage"
            phones = storage / "mobiles" / "gsmarena.com"
            filename = "gsmarena__xiaomi_test_phone-123.php.json"
            write_json(
                phones / filename,
                payload("Xiaomi Test Phone", announced="2024, July 03"),
            )
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
                ]
            )
            self.assertEqual(status, 0)

            with (output / "original" / "records.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["source_url"], product_url)
            self.assertEqual(row["url_recovery"], "manifest")
            self.assertEqual(row["data_snapshot"], "2024")
            self.assertEqual(row["data_snapshot_detail"], "07-03")
            self.assertEqual(row["snapshot_source"], "announced")
            self.assertEqual(json.loads(row["prices_json"]), [100000, 99999.5])
            self.assertEqual(row["sound_cable_jack"], "false")
            self.assertEqual(row["exposure_weight"], "Weight Unknown")

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

    def test_mega_url_uses_manifest_and_snapshot_columns_are_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Path(temporary) / "filestorage"
            filename = "mega__Example-Phone.html.json"
            write_json(
                storage / "mobiles" / "mega.pk" / filename,
                payload("Example Phone", announced="1999, January 01"),
            )
            product_url = (
                "https://www.mega.pk/mobiles_products/23647/Example-Phone.html"
            )
            write_json(
                storage / "sitemap_mobile" / "mega.pk.json",
                {"mobile_urls": [{"url": product_url}]},
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
            with (output / "mega" / "records.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["source_url"], product_url)
            self.assertEqual(row["data_snapshot"], "")
            self.assertEqual(row["data_snapshot_detail"], "")
            self.assertEqual(row["snapshot_source"], "original_database")

    def test_mega_url_is_rejected_instead_of_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Path(temporary) / "filestorage"
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


class CsvToDatabaseTests(unittest.TestCase):
    def test_contract_field_order_matches_converter(self) -> None:
        self.assertEqual(tuple(json_to_csv.RECORD_FIELDS), csv_to_database.RECORD_FIELDS)

    def test_dry_run_needs_no_aws_or_redshift_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Path(temporary) / "filestorage"
            write_json(
                storage
                / "mobiles"
                / "gsmarena.com"
                / "gsmarena__xiaomi_test_phone-123.php.json",
                payload("Xiaomi Test Phone", announced="2024, July"),
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

    def test_copy_target_and_credentials_are_allowlisted(self) -> None:
        sql = csv_to_database.copy_sql(
            "staging.phone_records",
            "s3://example-bucket/private/run.csv",
            "arn:aws:iam::123456789012:role/RedshiftCopy",
            "us-east-1",
        )
        self.assertIn("COPY staging.phone_records", sql)
        self.assertIn("IAM_ROLE", sql)
        with self.assertRaises(csv_to_database.LoadValidationError):
            csv_to_database.copy_sql(
                "original.central_info; DROP TABLE original.central_info",
                "s3://example-bucket/run.csv",
                "arn:aws:iam::123456789012:role/RedshiftCopy",
                "us-east-1",
            )


class SqlContractTests(unittest.TestCase):
    def test_redshift_schema_and_etl_contract(self) -> None:
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
            self.assertIn(schema, function_sql)
        self.assertIn("data_snapshot_detail varchar(5)", schema_sql)
        self.assertIn(" super", schema_sql)
        self.assertNotIn("timestamptz", schema_sql)
        self.assertNotIn("jsonb", schema_sql)
        self.assertNotIn("text[]", schema_sql)
        self.assertIn("create or replace procedure etl.load_original", function_sql)
        self.assertIn("create or replace procedure etl.load_source", function_sql)
        self.assertIn("create or replace procedure etl.load_all", function_sql)
        self.assertIn("source.canonical_snapshot", function_sql)
        self.assertIn("source.canonical_snapshot_detail", function_sql)
        self.assertIn("analytics.price_comparison", function_sql)
        self.assertIn("analytics.product_bundle", function_sql)


if __name__ == "__main__":
    unittest.main()
