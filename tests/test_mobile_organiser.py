from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "filestorage"))

from mobile_organiser import BUILD_ID, __version__
from mobile_organiser.classification import obvious_non_mobile_reason
from mobile_organiser.cli import _approve_review, _audit, _run, _structured_output_probe
from mobile_organiser.config import ConfigurationError, Settings
from mobile_organiser.identity import (
    Candidate,
    CandidateCatalog,
    CanonicalRecord,
    decide_canonical_match,
)
from mobile_organiser.io_utils import (
    InputFileError,
    RepoPaths,
    URLResolver,
    discover_source_files,
    parse_jsonc,
    read_source_json,
    read_template_jsonc,
)
from mobile_organiser.ollama import ChatResult, OllamaClient, OllamaError, _http_error
from mobile_organiser.pipeline import FatalPipelineError, MobileOrganiser
from mobile_organiser.schema import (
    EXTRACTION_RECORD_SCHEMA,
    MOBILE_V2_SCHEMA,
    SchemaValidationError,
    batch_response_schema,
    classification_response_schema,
    finalize_record,
    mobile_extraction_response_schema,
    require_valid,
    validate_ollama_schema_compatibility,
    validate_template_shape,
    single_response_schema,
)
from mobile_organiser.source_evidence import merge_source_evidence
from mobile_organiser.state import StateStore


def extraction_record(company: str | None, model: str | None) -> dict:
    """A complete evidence contract with no invented/default values."""
    return {
        "CompanyName": company,
        "MobileName": model,
        "Network": {"2G": None, "3G": None, "4G": None, "5G": None},
        "Announced": None,
        "Status": None,
        "Body": {
            "Dimensions": {"DimensionA": None, "DimensionB": None, "DimensionC": None},
            "Weight": None,
            "Build": None,
            "Normal-SIM": None,
            "Nano-SIM": None,
            "E-SIM": None,
            "Resistance-Standard": None,
            "Resistance-Water": None,
            "Resistance-Dust": None,
        },
        "Display": {
            "Screen": None,
            "Refresh-Rate": None,
            "Brightness": None,
            "ResolutionA": None,
            "ResolutionB": None,
            "Ratio": None,
            "Pixel-Density": None,
            "Protection": None,
        },
        "Platform": {
            "OS": None,
            "Chipset": None,
            "Chipset-Size": None,
            "CPU": None,
            "GPU": None,
        },
        "Memory": {"Card slot": None, "Types": [], "Technology": None},
        "Main Camera": {"Specifications": [], "Features": None, "Video": []},
        "Selfie Camera": {"Specifications": [], "Video": []},
        "Sound": {"Loudspeaker": None, "3.5mm jack": None},
        "Features": {
            "WLAN": None,
            "Bluetooth": None,
            "Positioning": None,
            "NFC": None,
            "Infrared port": None,
            "Radio": None,
            "USB-A": None,
            "USB-B": None,
            "Micro-USB": None,
            "USB-C": None,
            "BackFingerPrint": None,
            "SideFingerPrint": None,
            "InDisplayFingerPrint": None,
        },
        "Battery": {"Capacity": None, "WirelessCharging": None, "Charging": []},
        "Colors": [],
        "Price": [],
    }


def result_for_input(value: dict) -> dict:
    filename = value["source_filename"].casefold()
    if "charger" in filename or "cable" in filename:
        return {
            "input_id": value["input_id"],
            "is_mobile_device": False,
            "device_kind": "other",
            "identity_confidence": 0.99,
            "canonical_candidate_serial": None,
            "canonical_match_confidence": 0,
            "record": None,
        }
    if value["site"] == "gsmarena.com":
        company, model = "Sony", "Xperia 1 III"
        selected = None
    else:
        company, model = "Sony", "Xperia 1 Mark 3"
        selected = (
            value["canonical_candidates"][0]["serial_number"]
            if value["canonical_candidates"]
            else None
        )
    record = extraction_record(company, model)
    record["Network"] = {"2G": 1, "3G": 1, "4G": 1, "5G": 1}
    record["Announced"] = "2021, April 14"
    record["Status"] = "Available. Released 2021, August 25"
    record["Memory"]["Types"] = [[256, 12]]
    return {
        "input_id": value["input_id"],
        "is_mobile_device": True,
        "device_kind": "smartphone",
        "identity_confidence": 0.99,
        "canonical_candidate_serial": selected,
        "canonical_match_confidence": 0.99 if selected is not None else 0,
        "record": record,
    }


def direct_result_for_input(value: dict) -> dict:
    result = result_for_input(value)
    result.pop("input_id")
    return result


def extraction_result_for_schema(value: dict, response_schema: dict | None) -> dict:
    result = direct_result_for_input(value)
    properties = response_schema.get("properties", {}) if response_schema else {}
    for key in ("canonical_candidate_serial", "canonical_match_confidence"):
        if key not in properties:
            result.pop(key, None)
    return result


class FakeOllamaClient:
    def __init__(self):
        self.calls = 0
        self.seen_inputs: list[dict] = []

    def chat_record(self, *, input_record, task="extract_one_known_mobile_for_template_v2", response_schema=None, **kwargs):
        self.calls += 1
        self.seen_inputs.append(dict(input_record))
        if task == "classify_one_marketplace_listing":
            filename = input_record["source_filename"].casefold()
            is_mobile = not ("charger" in filename or "cable" in filename or "cover" in filename)
            return ChatResult(
                {
                    "is_mobile_device": is_mobile,
                    "device_kind": "smartphone" if is_mobile else "other",
                    "classification_confidence": 0.99,
                },
                {"eval_count": 2},
            )
        return ChatResult(
            extraction_result_for_schema(input_record, response_schema),
            {"eval_count": 10},
        )


class ProbeClient:
    def chat_record(self, *, task="extract_one_known_mobile_for_template_v2", response_schema=None, **kwargs):
        if task == "classify_one_marketplace_listing":
            return ChatResult(
                {
                    "is_mobile_device": True,
                    "device_kind": "feature_phone",
                    "classification_confidence": 0.99,
                },
                {"eval_count": 2},
            )
        phone = extraction_record("Alcatel", "HC 800")
        phone["Network"] = {"2G": 1, "3G": 0, "4G": 0, "5G": 0}
        phone["Announced"] = "1997"
        result = {
                "is_mobile_device": True,
                "device_kind": "feature_phone",
                "identity_confidence": 0.99,
                "canonical_candidate_serial": None,
                "canonical_match_confidence": 0,
                "record": phone,
            }
        properties = response_schema.get("properties", {}) if response_schema else {}
        for key in ("canonical_candidate_serial", "canonical_match_confidence"):
            if key not in properties:
                result.pop(key, None)
        return ChatResult(result, {"eval_count": 5})


class IdentityDriftingProbeClient(ProbeClient):
    """Drift once, then use validator feedback to repair the forced extraction."""

    def chat_record(self, *, task="extract_one_known_mobile_for_template_v2", previous_response=None, **kwargs):
        response = super().chat_record(task=task, previous_response=previous_response, **kwargs)
        if task != "classify_one_marketplace_listing" and previous_response is None:
            response.value["record"]["CompanyName"] = "Apple"
            response.value["record"]["MobileName"] = "iPhone"
        return response


class AccessoryBlindClient(FakeOllamaClient):
    """Would call every input a phone; the local guard must keep accessories away."""

    def __init__(self):
        super().__init__()
        self.seen_filenames: list[str] = []

    def chat_record(self, *, input_record, **kwargs):
        self.seen_filenames.append(input_record["source_filename"])
        return super().chat_record(input_record=input_record, **kwargs)


class PermanentFailureClient:
    def __init__(self):
        self.calls = 0

    def chat_record(self, **kwargs):
        self.calls += 1
        raise OllamaError("HTTP 400: invalid request schema", kind="schema")


class TransientThenSuccessClient(FakeOllamaClient):
    def chat_record(self, *, input_record, **kwargs):
        if self.calls == 0:
            self.calls += 1
            raise OllamaError("temporary connection failure", kind="transport", transient=True)
        return super().chat_record(input_record=input_record, **kwargs)


class IdentityRepairClient(FakeOllamaClient):
    def __init__(self):
        super().__init__()
        self.repair_feedback: list[list[str]] = []
        self.previous_responses: list[dict] = []

    def chat_record(
        self,
        *,
        input_record,
        previous_response=None,
        validation_feedback=(),
        response_schema=None,
        **kwargs,
    ):
        self.calls += 1
        if previous_response is None:
            wrong = extraction_result_for_schema(input_record, response_schema)
            wrong["record"]["CompanyName"] = "Apple"
            wrong["record"]["MobileName"] = "iPhone 15"
            return ChatResult(wrong, {"eval_count": 3})
        self.previous_responses.append(dict(previous_response))
        self.repair_feedback.append(list(validation_feedback))
        return ChatResult(
            extraction_result_for_schema(input_record, response_schema),
            {"eval_count": 4},
        )


class OneSourceUnrepairableClient(FakeOllamaClient):
    def chat_record(self, *, input_record, response_schema=None, **kwargs):
        self.calls += 1
        result = extraction_result_for_schema(input_record, response_schema)
        if "aaa-unrepairable" in input_record["source_filename"]:
            result["record"]["CompanyName"] = "Apple"
            result["record"]["MobileName"] = "iPhone 15"
        return ChatResult(result, {"eval_count": 4})


class CanonicalFilenameDriftClient(FakeOllamaClient):
    def chat_record(self, *, input_record, response_schema=None, **kwargs):
        self.calls += 1
        record = extraction_record("Alcatel", "HC 800-40")
        result = {
            "is_mobile_device": True,
            "device_kind": "feature_phone",
            "identity_confidence": 0.99,
            "record": record,
        }
        return ChatResult(result, {"eval_count": 4})


class PreflightFailureClient:
    def require_model(self):
        return ["gemma3:1b"]

    def chat_record(self, **kwargs):
        raise OllamaError("schema conversion failed", kind="schema")


class JSONCAndSchemaTests(unittest.TestCase):
    def test_configuration_rejects_wrong_json_types(self):
        with self.assertRaises(ConfigurationError):
            Settings(batch_size="2").validate()  # type: ignore[arg-type]
        with self.assertRaises(ConfigurationError):
            Settings(strict_review=1).validate()  # type: ignore[arg-type]

    def test_jsonc_preserves_urls_comments_and_trailing_commas(self):
        value = parse_jsonc(
            '// heading\n{"URL":"https://example.com/a//b","items":[1,2,],/* block */}'
        )
        self.assertEqual(value["URL"], "https://example.com/a//b")
        self.assertEqual(value["items"], [1, 2])

    def test_nonfinite_json_numbers_are_rejected(self):
        with self.assertRaises(InputFileError):
            parse_jsonc('{"invalid": NaN}')
        with self.assertRaises(InputFileError):
            parse_jsonc('{"MobileName":"A","MobileName":"B"}')

    def test_supplied_template_v2_fixture_has_exact_supported_tree(self):
        template = read_template_jsonc(PROJECT / "tests/fixtures/template_v2.jsonc")
        validate_template_shape(template)
        require_valid(template, MOBILE_V2_SCHEMA)

    def test_ollama_contract_is_evidence_only_and_has_no_url_regex(self):
        self.assertNotIn("URL", EXTRACTION_RECORD_SCHEMA["properties"])
        self.assertNotIn("Year", EXTRACTION_RECORD_SCHEMA["properties"])
        self.assertNotIn("Month", EXTRACTION_RECORD_SCHEMA["properties"])
        self.assertNotIn("Day", EXTRACTION_RECORD_SCHEMA["properties"])
        encoded = json.dumps(batch_response_schema(2), separators=(",", ":"))
        self.assertNotIn('"pattern"', encoded)
        self.assertNotIn('"URL"', encoded)
        validate_ollama_schema_compatibility(batch_response_schema(2))
        singleton = json.dumps(single_response_schema(), separators=(",", ":"))
        self.assertNotIn('"input_id"', singleton)
        self.assertNotIn('"records"', singleton)
        validate_ollama_schema_compatibility(single_response_schema())
        classification = classification_response_schema()
        forced = mobile_extraction_response_schema()
        self.assertNotIn("record", classification["properties"])
        self.assertEqual(forced["properties"]["record"]["type"], "object")
        self.assertEqual(forced["properties"]["is_mobile_device"]["enum"], [True])
        self.assertNotIn("anyOf", forced["properties"]["record"])

    def test_unanchored_ollama_pattern_is_rejected_locally(self):
        with self.assertRaises(SchemaValidationError):
            validate_ollama_schema_compatibility({"type": "string", "pattern": "https?://"})

    def test_prompt_forbids_model_memory_defaults_and_scraped_instructions(self):
        prompt = (PROJECT / "filestorage/prompts/mobile_v2_system.txt").read_text(encoding="utf-8")
        self.assertIn("Unknown scalar values must be null", prompt)
        self.assertIn("Do not apply template defaults", prompt)
        self.assertIn("untrusted product data", prompt)
        self.assertNotIn("input_id", prompt)
        self.assertIn("not a records array", prompt)
        classification_prompt = (
            PROJECT / "filestorage/prompts/mobile_classification_system.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("CLASSIFY THE ITEM BEING SOLD", classification_prompt)
        self.assertIn("Compatible phone names", classification_prompt)

    def test_pipeline_applies_defaults_and_records_their_paths(self):
        evidence = extraction_record("Test", "Model")
        require_valid(evidence, EXTRACTION_RECORD_SCHEMA)
        result = finalize_record(
            evidence,
            resolved_url="https://example.test/__fake__/model?fake=1",
            site="example.test",
            settings=Settings(),
        )
        require_valid(result.record, MOBILE_V2_SCHEMA)
        self.assertEqual(result.record["Body"]["Dimensions"], {"DimensionA": 50, "DimensionB": 50, "DimensionC": 5})
        self.assertEqual(result.record["Year"], 2014)
        self.assertIn("$.Body.Dimensions.DimensionA", result.defaulted_fields)
        self.assertIn("$.Network.5G", result.defaulted_fields)

    def test_finalizer_derives_date_ratio_and_gsmarena_pkr(self):
        proposed = extraction_record("XIAOMI", "XIAOMI Redmi Note 14 4G")
        proposed["Announced"] = "2025, January 10"
        proposed["Status"] = "Available"
        proposed["Display"]["ResolutionA"] = 1080
        proposed["Display"]["ResolutionB"] = 2400
        proposed["Price"] = [172.99, 206.80, 129.99]
        result = finalize_record(
            proposed,
            resolved_url="https://www.gsmarena.com/xiaomi_redmi_note_14-1.php",
            site="gsmarena.com",
            settings=Settings(),
        )
        self.assertEqual(result.record["CompanyName"], "Xiaomi")
        self.assertEqual(result.record["MobileName"], "Redmi Note 14 4G")
        self.assertEqual((result.record["Year"], result.record["Month"], result.record["Day"]), (2025, "JAN", 10))
        self.assertEqual(result.record["Display"]["Ratio"], "20:9")
        self.assertEqual(result.record["Price"][-1], 47572.25)

    def test_finalizer_survives_malformed_model_values_and_still_emits_strict_json(self):
        rng = random.Random(20260818)
        pool = [
            None,
            True,
            False,
            -1,
            0,
            1,
            1.5,
            float("nan"),
            "",
            "N/A",
            "value",
            [],
            [None, "x", 3],
            {},
            {"unexpected": "value"},
        ]
        keys = list(EXTRACTION_RECORD_SCHEMA["properties"])
        for index in range(100):
            proposed = {key: rng.choice(pool) for key in keys}
            result = finalize_record(
                proposed,
                resolved_url=f"https://fuzz.invalid/__fake__/{index}?fake=1",
                site="fuzz.invalid",
                settings=Settings(),
            )
            require_valid(result.record, MOBILE_V2_SCHEMA)
            json.dumps(result.record, allow_nan=False)


class IdentityTests(unittest.TestCase):
    def test_mark_three_alias_can_match_gsmarena_roman_numeral(self):
        canonical = CanonicalRecord(7, "Sony", "Xperia 1 III")
        candidates = CandidateCatalog([canonical]).candidates(
            "Sony Xperia 1 Mark 3 12GB 256GB PTA Approved", 8
        )
        decision = decide_canonical_match(
            proposed_company="Sony",
            proposed_mobile_name="Xperia 1 Mark 3",
            llm_serial=7,
            llm_confidence=0.99,
            offered=candidates,
            minimum_confidence=0.92,
            minimum_similarity=0.72,
        )
        self.assertEqual(decision.accepted, canonical)

    def test_variant_conflict_is_rejected(self):
        canonical = CanonicalRecord(8, "Samsung", "Galaxy S24 Ultra")
        decision = decide_canonical_match(
            proposed_company="Samsung",
            proposed_mobile_name="Galaxy S24",
            llm_serial=8,
            llm_confidence=0.99,
            offered=[Candidate(canonical, 0.8)],
            minimum_confidence=0.92,
            minimum_similarity=0.50,
        )
        self.assertIsNone(decision.accepted)
        self.assertEqual(decision.reason, "identity_significant_variant_conflict")

    def test_adjacent_model_number_is_rejected(self):
        canonical = CanonicalRecord(9, "Samsung", "Galaxy S23")
        decision = decide_canonical_match(
            proposed_company="Samsung",
            proposed_mobile_name="Galaxy S24",
            llm_serial=9,
            llm_confidence=0.99,
            offered=[Candidate(canonical, 0.9)],
            minimum_confidence=0.92,
            minimum_similarity=0.50,
        )
        self.assertIsNone(decision.accepted)
        self.assertEqual(decision.reason, "model_number_conflict")

    def test_alphanumeric_suffix_conflict_is_rejected(self):
        canonical = CanonicalRecord(10, "Samsung", "Galaxy A15")
        decision = decide_canonical_match(
            proposed_company="Samsung",
            proposed_mobile_name="Galaxy A15s",
            llm_serial=10,
            llm_confidence=0.99,
            offered=[Candidate(canonical, 0.95)],
            minimum_confidence=0.92,
            minimum_similarity=0.50,
        )
        self.assertIsNone(decision.accepted)
        self.assertEqual(decision.reason, "model_token_conflict")

    def test_catalog_reports_duplicate_canonical_identity(self):
        catalog = CandidateCatalog(
            [CanonicalRecord(1, "Xiaomi", "Redmi Note 14 4G"), CanonicalRecord(2, "Xiaomi", "Redmi Note 14 4G")]
        )
        self.assertEqual([item.serial_number for item in catalog.duplicate_identity("xiaomi", "Redmi Note 14 4G")], [1, 2])


class SourceEvidenceTests(unittest.TestCase):
    def test_gsmarena_legacy_facts_override_model_omissions(self):
        proposed = extraction_record("Alcatel", "HC 800")
        raw = {
            "MobileName": "alcatel HC 800",
            "Network": {"2G": 1, "3G": 0, "4G": 0, "5G": 0},
            "Launch": {"Announced": "1997", "Status": "Discontinued"},
            "Body": {
                "Dimensions": "143 x 60 x 23 mm (5.63 x 2.36 x 0.91 in)",
                "Weight": "172 g (6.07 oz)",
                "Build": None,
                "SIM": "Mini-SIM",
                "Protection": None,
            },
            "Display": {"Type": "Alphanumeric", "Resolution": "4 x 16 chars"},
            "Platform": {"OS": None, "Chipset": None, "CPU": None, "GPU": None},
            "Memory": {"Card slot": "No", "Types": [], "Technology": None},
            "Main Camera": {"Specifications": [], "Features": None, "Video": []},
            "Selfie Camera": {"Specifications": [], "Video": []},
            "Sound": {"Loudspeaker": "No", "3.5mm jack": 0},
            "Features": {
                "WLAN": "No",
                "Bluetooth": "No",
                "Positioning": "No",
                "NFC": 0,
                "Infrared port": 0,
                "Radio": 0,
                "USB": "",
                "BackFingerPrint": 0,
                "SideFingerPrint": 0,
                "InDisplayFingerPrint": 0,
            },
            "Battery": {
                "Capacity": "Removable Li-Ion battery",
                "WirelessCharging": 0,
                "Charging": [],
            },
            "Colors": ["Black"],
            "Price": [],
        }
        merged = merge_source_evidence(proposed, raw)
        self.assertEqual(
            merged["Body"]["Dimensions"],
            {"DimensionA": 143, "DimensionB": 60, "DimensionC": 23},
        )
        self.assertEqual(merged["Body"]["Weight"], 172)
        self.assertEqual(
            (merged["Body"]["Normal-SIM"], merged["Body"]["Nano-SIM"], merged["Body"]["E-SIM"]),
            (1, 0, 0),
        )
        self.assertEqual(merged["Sound"], {"Loudspeaker": 0, "3.5mm jack": 0})
        self.assertEqual(merged["Features"]["Radio"], 0)
        self.assertEqual(merged["Colors"], ["Black"])
        self.assertIsNone(merged["Battery"]["Capacity"])

    def test_modern_legacy_strings_are_converted_without_erasing_llm_fallbacks(self):
        proposed = extraction_record("Apple", "iPhone 15")
        proposed["Platform"]["GPU"] = "model fallback"
        raw = {
            "Network": {"2G": 1, "3G": 1, "4G": 1, "5G": 1},
            "Launch": {"Announced": "2023-09-12", "Status": "Available"},
            "Body": {
                "Dimensions": "5.811 x 2.819 x 0.307 in",
                "Weight": "6.03 oz",
                "SIM": "Nano-SIM + eSIM",
                "Protection": "IP68 dust tight and water resistant",
            },
            "Display": {
                "Type": "AMOLED, 120Hz, 960Hz PWM, 1200 nits (HBM), 1800 nits (peak)",
                "Resolution": "1179 x 2556 pixels, 19.5:9 ratio (~461 ppi density)",
                "Protection": "Ceramic Shield glass",
            },
            "Platform": {
                "OS": "iOS 17",
                "Chipset": "Apple A16 Bionic (4 nm)",
                "CPU": "Hexa-core",
                "GPU": None,
            },
            "Memory": {
                "Card slot": "No",
                "Types": ["6GB RAM / 128GB, 256GB, 512GB"],
                "Technology": None,
            },
            "Main Camera": {
                "Specifications": ["48 MP"],
                "Features": "HDR",
                "Video": ["4K@24/25/30/60fps", "HDR"],
            },
            "Selfie Camera": {"Specifications": ["12 MP"], "Video": ["1080p@30fps"]},
            "Sound": {"Loudspeaker": "Yes, with stereo speakers", "3.5mm jack": 0},
            "Features": {
                "USB": "USB Type-C 2.0, DisplayPort",
                "Sensors": "Fingerprint (under display, optical)",
            },
            "Battery": {"Capacity": "3349 mAh", "WirelessCharging": 1, "Charging": ["15W wireless"]},
            "Colors": ["Black", "Blue"],
            "Price": [284000.0],
        }
        merged = merge_source_evidence(proposed, raw)
        self.assertAlmostEqual(merged["Body"]["Dimensions"]["DimensionA"], 147.5994)
        self.assertAlmostEqual(merged["Body"]["Weight"], 170.947624)
        self.assertEqual(merged["Display"]["Screen"], "AMOLED")
        self.assertEqual(merged["Display"]["Refresh-Rate"], 120)
        self.assertEqual(merged["Display"]["Brightness"], 1800)
        self.assertEqual((merged["Display"]["ResolutionA"], merged["Display"]["ResolutionB"]), (1179, 2556))
        self.assertEqual(merged["Display"]["Ratio"], "19.5:9")
        self.assertEqual(merged["Display"]["Pixel-Density"], 461)
        self.assertEqual(merged["Platform"]["Chipset"], "Apple A16 Bionic")
        self.assertEqual(merged["Platform"]["Chipset-Size"], 4)
        self.assertEqual(merged["Platform"]["GPU"], "model fallback")
        self.assertEqual(merged["Memory"]["Types"], [[128, 6], [256, 6], [512, 6]])
        self.assertEqual(
            merged["Main Camera"]["Video"],
            ["4K@24fps", "4K@25fps", "4K@30fps", "4K@60fps"],
        )
        self.assertEqual(merged["Features"]["USB-C"], 1)
        self.assertEqual(merged["Features"]["Micro-USB"], 0)
        self.assertEqual(merged["Features"]["InDisplayFingerPrint"], 1)
        self.assertEqual(merged["Battery"]["Capacity"], 3349)

    def test_catalogue_memory_notations_are_parsed(self):
        base = extraction_record("Acer", "Model")
        first = merge_source_evidence(base, {"Memory": {"Types": ["3 GB 16/32 GB"]}})
        self.assertEqual(first["Memory"]["Types"], [[16, 3], [32, 3]])
        second = merge_source_evidence(
            base,
            {"Memory": {"Types": ["128GB Built-in", "8GB RAM (+8GB of Extended RAM)"]}},
        )
        self.assertEqual(second["Memory"]["Types"], [[128, 8]])


class OllamaProtocolTests(unittest.TestCase):
    def test_nested_http_schema_error_is_unwrapped_and_classified(self):
        nested = json.dumps(
            {
                "error": json.dumps(
                    {"error": {"code": 400, "message": "JSON schema conversion failed: Pattern must start with '^' and end with '$'"}}
                )
            }
        )
        error = _http_error(400, nested, "Bad Request")
        self.assertEqual(error.kind, "schema")
        self.assertFalse(error.transient)
        self.assertFalse(error.splittable)
        self.assertIn("Pattern must start", str(error))

    def test_http_rate_limit_and_context_errors_have_distinct_retry_policy(self):
        rate = _http_error(429, '{"error":"busy"}', "Too Many Requests")
        context = _http_error(413, '{"error":"request too large"}', "Content Too Large")
        self.assertTrue(rate.transient)
        self.assertFalse(rate.splittable)
        self.assertFalse(context.transient)
        self.assertTrue(context.splittable)

    def test_chat_payload_is_singleton_and_python_owns_routing(self):
        settings = Settings(num_predict=4096)
        client = OllamaClient(settings)
        captured = {}

        def fake_request(method, endpoint, payload=None):
            captured.update(payload)
            return {"message": {"content": '{"ok":"yes"}'}, "done_reason": "stop"}

        client._request_json = fake_request  # type: ignore[method-assign]
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "string"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        client.chat_record(
            system_prompt="Return JSON",
            input_record={"input_id": "gsmarena.com:1", "source_record": {"MobileName": "Phone"}},
            response_schema=schema,
        )
        user_payload = json.loads(captured["messages"][1]["content"])
        self.assertEqual(
            user_payload["protocol_version"], "mobile-evidence-v3-classify-force-reconcile"
        )
        self.assertIn("URL", user_payload["target_template_v2_shape"])
        self.assertIn("Year", user_payload["target_template_v2_shape"])
        self.assertEqual(user_payload["routing"], "exactly_one_input_python_owns_source_id")
        self.assertNotIn("input_id", user_payload["input"])
        self.assertNotIn("output_schema", user_payload)
        self.assertEqual(captured["format"], schema)
        self.assertEqual(captured["options"]["num_predict"], 4096)

    def test_repair_call_returns_previous_json_and_validator_feedback_to_gemma(self):
        client = OllamaClient(Settings())
        captured = {}

        def fake_request(method, endpoint, payload=None):
            captured.update(payload)
            return {"message": {"content": '{"ok":"fixed"}'}, "done_reason": "stop"}

        client._request_json = fake_request  # type: ignore[method-assign]
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "string"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        client.chat_record(
            system_prompt="Return JSON",
            input_record={"input_id": "gsmarena.com:1", "source_record": {}},
            response_schema=schema,
            previous_response={"ok": "wrong"},
            validation_feedback=["identity does not match source"],
            attempt_number=2,
        )
        self.assertEqual([message["role"] for message in captured["messages"]], ["system", "user", "assistant", "user"])
        repair = json.loads(captured["messages"][3]["content"])
        self.assertEqual(repair["validation_errors"], ["identity does not match source"])
        self.assertEqual(json.loads(captured["messages"][2]["content"]), {"ok": "wrong"})


class ClassificationGuardTests(unittest.TestCase):
    def test_explicit_cable_and_real_log_accessories_are_rejected(self):
        cases = [
            (
                "USB-C charging cable accessory; this is not a phone or tablet",
                "preflight__usb-c-charging-cable-accessory.json",
                "obvious_accessory:charging_cable",
            ),
            (
                "45W/65W Super Fast Charger Dual Port USB-C USB-A PD QC adapter",
                "daraz__45w65w-n-68-super-fast-charger-dual-port-usb-c-usb-a-pd-30-qc-30.html.json",
                "obvious_accessory:charger",
            ),
            (
                "All mobile phone dustproof net stickers speaker mesh anti dust",
                "daraz__all-mobile-phone-dustproof-net-stickers-speaker-mesh.html.json",
                "obvious_accessory:dust_sticker",
            ),
            (
                "Wallet cover case compatible with Samsung Galaxy mobile phones",
                "daraz__wallet-cover-case-compatible-with-samsung-galaxy.json",
                "obvious_accessory:protective_accessory",
            ),
            (
                "65W fast charger with USB-C cable for Samsung phones",
                "daraz__65w-fast-charger-with-usb-c-cable.html.json",
                "obvious_accessory:charger",
            ),
        ]
        for raw_name, filename, expected in cases:
            with self.subTest(filename=filename):
                self.assertEqual(obvious_non_mobile_reason(raw_name, filename), expected)

    def test_phone_bundle_wording_is_not_rejected(self):
        cases = [
            (
                "Sony Xperia 1 Mark 3 RAM 12GB ROM 256GB phone only no box no charger",
                "daraz__sony-xperia-1-mark-3-phone-only-no-box-no-charger.html.json",
            ),
            (
                "Vivo Y20s 8GB RAM 128GB storage 5000mAh battery 13MP camera with box charger",
                "daraz__vivo-y20s-with-box-charger.html.json",
            ),
            (
                "Apple iPhone 15 phone only no charger",
                "daraz__apple-iphone-15-phone-only-no-charger.html.json",
            ),
            (
                "Samsung Galaxy A15 with 25W charger",
                "daraz__samsung-galaxy-a15-with-25w-charger.html.json",
            ),
        ]
        for raw_name, filename in cases:
            with self.subTest(filename=filename):
                self.assertIsNone(obvious_non_mobile_reason(raw_name, filename))

    def test_ambiguous_normal_phone_stays_with_llm(self):
        self.assertIsNone(
            obvious_non_mobile_reason(
                "Xiaomi Redmi Note 14 4G",
                "gsmarena__xiaomi_redmi_note_14_4g-1.php.json",
            )
        )


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "filestorage/mobiles/gsmarena.com").mkdir(parents=True)
        (self.root / "filestorage/mobiles/daraz.pk").mkdir(parents=True)
        (self.root / "filestorage/prompts").mkdir(parents=True)
        (self.root / "filestorage/template_v2.json").write_text(
            (PROJECT / "tests/fixtures/template_v2.jsonc").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (self.root / "filestorage/prompts/mobile_v2_system.txt").write_text(
            "Return JSON evidence only.", encoding="utf-8"
        )
        (self.root / "filestorage/prompts/mobile_classification_system.txt").write_text(
            "Classify one listing and return JSON only.", encoding="utf-8"
        )
        self._write_json(
            self.root / "filestorage/mobiles/gsmarena.com/gsmarena__sony_xperia_1_iii-1.php.json",
            {"MobileName": "Sony Xperia 1 III", "Price": []},
        )
        self._write_json(
            self.root / "filestorage/mobiles/daraz.pk/daraz__sony-xperia-1-mark-3-12gb-256gb-i1.html.json",
            {"MobileName": "Sony Xperia 1 Mark 3 - RAM 12GB - ROM 256GB"},
        )
        self._write_json(
            self.root / "filestorage/mobiles/daraz.pk/daraz__65w-phone-charger-i2.html.json",
            {"MobileName": "65W fast phone charger"},
        )
        self.paths = RepoPaths.from_root(self.root)
        self.settings = Settings(batch_size=2)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def _run_fake(self) -> tuple[object, FakeOllamaClient]:
        sources = discover_source_files(self.paths.source_root)
        fake = FakeOllamaClient()
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=self.settings,
                state=state,
                client=fake,
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            summary = organiser.run(sources=sources, sites=None, limit=None)
        return summary, fake

    def test_url_resolver_uses_exact_filename_routes(self):
        sources = discover_source_files(self.paths.source_root)
        resolver = URLResolver(self.paths)
        by_site = {source.site: source for source in sources if "charger" not in source.path.name}
        gsm = by_site["gsmarena.com"]
        daraz = by_site["daraz.pk"]
        self.assertEqual(
            resolver.resolve(gsm, read_source_json(gsm, 10000)).url,
            "https://www.gsmarena.com/sony_xperia_1_iii-1.php",
        )
        self.assertEqual(
            resolver.resolve(daraz, read_source_json(daraz, 10000)).url,
            "https://www.daraz.pk/products/sony-xperia-1-mark-3-12gb-256gb-i1.html",
        )

    def test_real_alcatel_filename_tails_reconstruct_exact_gsmarena_urls(self):
        expected = {
            "gsmarena__alcatel_hc_1000-39.php.json":
                "https://www.gsmarena.com/alcatel_hc_1000-39.php",
            "gsmarena__alcatel_hc_800-40.php.json":
                "https://www.gsmarena.com/alcatel_hc_800-40.php",
        }
        directory = self.root / "filestorage/mobiles/gsmarena.com"
        for filename in expected:
            self._write_json(directory / filename, {"MobileName": filename})
        resolver = URLResolver(self.paths)
        sources = {item.path.name: item for item in discover_source_files(self.paths.source_root)}
        for filename, url in expected.items():
            with self.subTest(filename=filename):
                source = sources[filename]
                resolved = resolver.resolve(source, read_source_json(source, 10000))
                self.assertEqual(resolved.url, url)
                self.assertFalse(resolved.is_fake)
                self.assertEqual(resolved.method, "filename")

    def test_nonreconstructable_site_url_is_marked_fake_not_guessed(self):
        directory = self.root / "filestorage/mobiles/mymobile.pk"
        directory.mkdir(parents=True)
        path = directory / "mymobile__apple-iphone-15.json"
        self._write_json(path, {"MobileName": "Apple iPhone 15"})
        source = next(
            item for item in discover_source_files(self.paths.source_root) if item.path == path
        )
        resolved = URLResolver(self.paths).resolve(source, read_source_json(source, 10000))
        self.assertTrue(resolved.is_fake)
        self.assertEqual(resolved.method, "generated_fake")
        self.assertIn("/__fake__/", resolved.url)
        self.assertIn("fake=1", resolved.url)

    def test_crawler_jsonl_metadata_recovers_exact_secondary_url(self):
        directory = self.root / "filestorage/mobiles/mega.pk"
        directory.mkdir(parents=True)
        product = directory / "mega__Apple-iPhone-15.html.json"
        self._write_json(product, {"MobileName": "Apple iPhone 15"})
        metadata = {
            "url": "https://www.mega.pk/mobiles_products/Apple-iPhone-15.html",
            "error": "historical retry",
        }
        (directory / "_failures.jsonl").write_text(json.dumps(metadata) + "\n", encoding="utf-8")
        source = next(
            item for item in discover_source_files(self.paths.source_root) if item.path == product
        )
        resolver = URLResolver(self.paths)
        resolver.build(["mega.pk"])
        resolved = resolver.resolve(source, read_source_json(source, 10000))
        self.assertFalse(resolved.is_fake)
        self.assertEqual(resolved.method, "manifest")
        self.assertEqual(resolved.url, metadata["url"])

    def test_sitemap_manifests_recover_filename_urls_for_every_secondary_site(self):
        cases = {
            "mega.pk": (
                "mega__Apple-iPhone-14-128GB-Storage-PTA-Approved.html.json",
                "https://www.mega.pk/mobiles_products/23647/Apple-iPhone-14-128GB-Storage-PTA-Approved.html",
            ),
            "mymobile.pk": (
                "mymobile__apple-iphone-15.json",
                "https://mymobile.pk/apple-iphone-15",
            ),
            "whatamobile.com.pk": (
                "whatamobile__acer-iconia-talk-s.json",
                "https://www.whatamobile.com.pk/product/acer-iconia-talk-s-price-in-pakistan",
            ),
            "whatmobile.com.pk": (
                "whatmobile__Dcode_Bold-4.json",
                "https://www.whatmobile.com.pk/Dcode_Bold-4",
            ),
        }
        manifest_dir = self.root / "filestorage/sitemap_mobile"
        manifest_dir.mkdir(parents=True)
        for site, (filename, url) in cases.items():
            directory = self.root / "filestorage/mobiles" / site
            directory.mkdir(parents=True, exist_ok=True)
            self._write_json(directory / filename, {"MobileName": filename})
            self._write_json(manifest_dir / f"{site}.json", {"urls": [url]})

        resolver = URLResolver(self.paths)
        resolver.build(cases)
        sources = {item.path.name: item for item in discover_source_files(self.paths.source_root)}
        for filename, expected in cases.values():
            with self.subTest(filename=filename):
                source = sources[filename]
                resolved = resolver.resolve(source, read_source_json(source, 10000))
                self.assertEqual(resolved.url, expected)
                self.assertFalse(resolved.is_fake)
                self.assertEqual(resolved.method, "manifest")

    def test_structured_output_preflight_checks_singleton_schema_and_local_guard(self):
        result = _structured_output_probe(ProbeClient(), self.paths, self.settings)
        self.assertTrue(result["ok"])
        self.assertEqual(result["records_checked"], 2)
        self.assertEqual(result["local_guards_checked"], 1)
        self.assertEqual(result["schemas"]["classification_runtime"], "passed")
        self.assertEqual(result["schemas"]["forced_extraction_runtime"], "passed")
        self.assertEqual(
            result["semantic_observations"]["explicit_accessory_local_guard"], "passed"
        )

    def test_forced_preflight_identity_drift_is_repaired_by_gemma(self):
        result = _structured_output_probe(IdentityDriftingProbeClient(), self.paths, self.settings)
        self.assertTrue(result["ok"])
        self.assertEqual(result["schemas"]["forced_extraction_runtime"], "passed")
        self.assertEqual(
            result["semantic_observations"]["forced_phone_identity"], "Alcatel HC 800"
        )
        self.assertEqual(len(result["repair_events"]["forced_extraction"]), 1)

    def test_run_preflight_failure_cannot_create_or_mutate_state(self):
        args = SimpleNamespace(
            limit=1,
            site=["gsmarena.com"],
            dry_run=False,
            retry_failed=False,
            reprocess_unmatched=False,
        )
        with patch("mobile_organiser.cli.OllamaClient", return_value=PreflightFailureClient()):
            with self.assertRaises(OllamaError):
                _run(self.paths, self.settings, args)
        self.assertFalse(self.paths.state_db.exists())

    def test_empty_output_audit_fails_honestly(self):
        capture = io.StringIO()
        with redirect_stdout(capture):
            code = _audit(self.paths, self.settings, include_review=True)
        report = json.loads(capture.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["checked"], 0)

    def test_permanent_schema_error_aborts_once_without_batch_split(self):
        sources = [source for source in discover_source_files(self.paths.source_root) if source.site == "daraz.pk"]
        failure = PermanentFailureClient()
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=self.settings,
                state=state,
                client=failure,
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: self.fail("permanent HTTP 400 must not sleep"),
            )
            with self.assertRaises(FatalPipelineError):
                organiser.run(sources=sources, sites={"daraz.pk"}, limit=None)
            self.assertEqual(failure.calls, 1)
            statuses = {row["status"]: row["count"] for row in state.stats()}
            self.assertEqual(statuses, {"rejected_non_mobile": 1, "request_rejected": 1})
            self.assertEqual(state.requeue_retryable({"daraz.pk"}), 1)

    def test_transient_failure_retries_while_all_model_calls_remain_singleton(self):
        self._write_json(
            self.root / "filestorage/mobiles/daraz.pk/daraz__sony-xperia-1-iii-8gb-128gb-i3.html.json",
            {"MobileName": "Sony Xperia 1 III - RAM 8GB - ROM 128GB"},
        )
        sources = [source for source in discover_source_files(self.paths.source_root) if source.site == "daraz.pk"]
        client = TransientThenSuccessClient()
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=self.settings,
                state=state,
                client=client,
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            summary = organiser.run(sources=sources, sites={"daraz.pk"}, limit=None)
        self.assertEqual(summary.unmatched, 2)
        self.assertEqual(summary.rejected_non_mobile, 1)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(client.calls, 5)

    def test_wrong_gsmarena_identity_is_sent_back_to_gemma_and_repaired(self):
        source = next(
            source
            for source in discover_source_files(self.paths.source_root)
            if source.site == "gsmarena.com"
        )
        client = IdentityRepairClient()
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=self.settings,
                state=state,
                client=client,
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            summary = organiser.run(sources=[source], sites={"gsmarena.com"}, limit=1)
        self.assertEqual(summary.completed, 1)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(client.calls, 2)
        self.assertEqual(len(client.previous_responses), 1)
        self.assertTrue(
            any("does not match the GSMArena source identity" in message for message in client.repair_feedback[0])
        )
        output = json.loads(
            self.root.joinpath(
                "filestorage/mobiles_organised/gsmarena.com/00000001.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual((output["CompanyName"], output["MobileName"]), ("Sony", "Xperia 1 III"))

    def test_gsmarena_source_title_removes_model_filename_page_id_drift(self):
        path = (
            self.root
            / "filestorage/mobiles/gsmarena.com/gsmarena__alcatel_hc_800-40.php.json"
        )
        self._write_json(path, {"MobileName": "alcatel HC 800"})
        source = next(
            item for item in discover_source_files(self.paths.source_root) if item.path == path
        )
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=self.settings,
                state=state,
                client=CanonicalFilenameDriftClient(),
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            summary = organiser.run(sources=[source], sites={"gsmarena.com"}, limit=1)
        self.assertEqual(summary.completed, 1)
        output = json.loads(
            self.root.joinpath(
                "filestorage/mobiles_organised/gsmarena.com/00000001.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual((output["CompanyName"], output["MobileName"]), ("Alcatel", "HC 800"))
        self.assertEqual(
            output["URL"], "https://www.gsmarena.com/alcatel_hc_800-40.php"
        )

    def test_unrepairable_record_fails_alone_and_next_phone_still_completes(self):
        self._write_json(
            self.root
            / "filestorage/mobiles/gsmarena.com/gsmarena__aaa-unrepairable-2.php.json",
            {"MobileName": "Sony Xperia 1 III"},
        )
        sources = [
            source
            for source in discover_source_files(self.paths.source_root)
            if source.site == "gsmarena.com"
        ]
        settings = Settings(max_request_attempts=2)
        client = OneSourceUnrepairableClient()
        with StateStore(self.paths, settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=settings,
                state=state,
                client=client,
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            summary = organiser.run(sources=sources, sites={"gsmarena.com"}, limit=None)
            statuses = {row["status"]: row["count"] for row in state.stats()}
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.completed, 1)
        self.assertEqual(client.calls, 3)
        self.assertEqual(statuses, {"completed": 1, "invalid_llm_output": 1})
        self.assertTrue(
            self.root.joinpath(
                "filestorage/mobiles_organised/gsmarena.com/00000002.json"
            ).is_file()
        )

    def test_obvious_accessory_never_reaches_a_model_that_would_misclassify_it(self):
        sources = [
            source
            for source in discover_source_files(self.paths.source_root)
            if source.site == "daraz.pk"
        ]
        client = AccessoryBlindClient()
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=self.settings,
                state=state,
                client=client,
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            summary = organiser.run(sources=sources, sites={"daraz.pk"}, limit=None)
            detail = state.connection.execute(
                "SELECT detail FROM attempts WHERE outcome='rejected_non_mobile'"
            ).fetchone()["detail"]
        self.assertEqual(summary.unmatched, 1)
        self.assertEqual(summary.rejected_non_mobile, 1)
        self.assertEqual(client.calls, 2)
        self.assertFalse(any("charger" in name.casefold() for name in client.seen_filenames))
        self.assertEqual(detail, "obvious_accessory:charger")

    def test_single_source_larger_than_context_budget_is_not_silently_truncated(self):
        oversized = self.root / "filestorage/mobiles/daraz.pk/daraz__oversized-phone-i9.html.json"
        self._write_json(oversized, {"MobileName": "Sony Xperia", "description": "x" * 12000})
        source = next(
            item for item in discover_source_files(self.paths.source_root) if item.path == oversized
        )
        settings = Settings(batch_size=1, num_ctx=1024, num_predict=512)
        client = FakeOllamaClient()
        with StateStore(self.paths, settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=settings,
                state=state,
                client=client,
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            summary = organiser.run(sources=[source], sites={"daraz.pk"}, limit=None)
            statuses = {row["status"]: row["count"] for row in state.stats()}
        self.assertEqual(summary.failed, 1)
        self.assertEqual(client.calls, 0)
        self.assertEqual(statuses, {"invalid_input": 1})

    def test_end_to_end_canonical_names_serials_history_and_rerun(self):
        sources = discover_source_files(self.paths.source_root)
        fake = FakeOllamaClient()
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=self.settings,
                state=state,
                client=fake,
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            first = organiser.run(sources=sources, sites=None, limit=None)
            self.assertEqual(first.completed, 2)
            self.assertEqual(first.rejected_non_mobile, 1)
            gsm_output = self.root / "filestorage/mobiles_organised/gsmarena.com/00000001.json"
            daraz_output = self.root / "filestorage/mobiles_organised/daraz.pk/00000002.json"
            self.assertTrue(gsm_output.is_file())
            self.assertTrue(daraz_output.is_file())
            daraz_value = json.loads(daraz_output.read_text(encoding="utf-8"))
            self.assertEqual((daraz_value["CompanyName"], daraz_value["MobileName"]), ("Sony", "Xperia 1 III"))
            self.assertFalse(self.root.joinpath("filestorage/mobiles_organised/daraz.pk/00000001.json").exists())

            second = organiser.run(sources=discover_source_files(self.paths.source_root), sites=None, limit=None)
            self.assertEqual(second.selected, 0)

            phone_source = self.root / "filestorage/mobiles/daraz.pk/daraz__sony-xperia-1-mark-3-12gb-256gb-i1.html.json"
            self._write_json(phone_source, {"MobileName": "Sony Xperia 1 Mark 3", "Price": [99999]})
            third = organiser.run(sources=discover_source_files(self.paths.source_root), sites=None, limit=None)
            self.assertEqual(third.selected, 1)
            self.assertTrue(daraz_output.is_file())
            self.assertFalse(self.root.joinpath("filestorage/mobiles_organised/daraz.pk/00000003.json").exists())
            history = list(
                self.root.glob("filestorage/mobiles_organised/.state/history/daraz.pk/00000002/*.json")
            )
            self.assertEqual(len(history), 1)

    def test_duplicate_gsmarena_identity_is_quarantined(self):
        self._write_json(
            self.root / "filestorage/mobiles/gsmarena.com/gsmarena__duplicate_sony-2.php.json",
            {"MobileName": "Sony Xperia 1 III"},
        )
        sources = [source for source in discover_source_files(self.paths.source_root) if source.site == "gsmarena.com"]
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=self.settings,
                state=state,
                client=FakeOllamaClient(),
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            summary = organiser.run(sources=sources, sites={"gsmarena.com"}, limit=None)
        self.assertEqual(summary.completed, 1)
        self.assertEqual(summary.review_required, 1)
        self.assertTrue(self.root.joinpath("filestorage/mobiles_organised/_review/gsmarena.com/00000002.json").is_file())

    def test_review_approval_archives_quarantine_file_and_blocks_stale_duplicate(self):
        self._write_json(
            self.root / "filestorage/mobiles/gsmarena.com/gsmarena__duplicate_sony-2.php.json",
            {"MobileName": "Sony Xperia 1 III"},
        )
        sources = [source for source in discover_source_files(self.paths.source_root) if source.site == "gsmarena.com"]
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            organiser = MobileOrganiser(
                paths=self.paths,
                settings=self.settings,
                state=state,
                client=FakeOllamaClient(),
                system_prompt="strict",
                progress=lambda _: None,
                sleeper=lambda _: None,
            )
            organiser.run(sources=sources, sites={"gsmarena.com"}, limit=None)
        review = self.root / "filestorage/mobiles_organised/_review/gsmarena.com/00000002.json"
        args = SimpleNamespace(site="gsmarena.com", serial=2, canonical_serial=None, yes=True)
        with self.assertRaises(InputFileError) as duplicate_error:
            _approve_review(self.paths, self.settings, args)
        self.assertIn("duplicates GSMArena serial 1", str(duplicate_error.exception))

        value = json.loads(review.read_text(encoding="utf-8"))
        value["MobileName"] = "Xperia 1 III Regional"
        review.write_text(json.dumps(value), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(_approve_review(self.paths, self.settings, args), 0)
        self.assertFalse(review.exists())
        self.assertTrue(self.root.joinpath("filestorage/mobiles_organised/gsmarena.com/00000002.json").is_file())
        archived = list(
            self.root.glob("filestorage/mobiles_organised/.state/history/gsmarena.com/00000002/*approved-review*.json")
        )
        self.assertEqual(len(archived), 1)

    def test_audit_verifies_state_hash_and_exact_canonical_identity(self):
        self._run_fake()
        capture = io.StringIO()
        with redirect_stdout(capture):
            code = _audit(self.paths, self.settings, include_review=True)
        self.assertEqual(code, 0, capture.getvalue())
        report = json.loads(capture.getvalue())
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 2)

        target = self.root / "filestorage/mobiles_organised/daraz.pk/00000002.json"
        value = json.loads(target.read_text(encoding="utf-8"))
        value["MobileName"] = "Xperia 1 IV"
        target.write_text(json.dumps(value), encoding="utf-8")
        capture = io.StringIO()
        with redirect_stdout(capture):
            code = _audit(self.paths, self.settings, include_review=True)
        self.assertEqual(code, 1)
        issues = json.loads(capture.getvalue())["issues"]
        self.assertTrue(any("hash differs" in issue for issue in issues))
        self.assertTrue(any("exact canonical" in issue for issue in issues))

    def test_interrupted_processing_is_recovered_without_renumbering(self):
        sources = discover_source_files(self.paths.source_root)
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            state.register_sources(sources)
            rows = state.pending_rows(sites={"gsmarena.com"}, canonical_site="gsmarena.com", limit=1)
            state.mark_processing([rows[0].source_rel])
            serial = rows[0].serial_number
        with StateStore(self.paths, self.settings.output_filename_digits) as state:
            self.assertEqual(state.recover_interrupted(), 1)
            recovered = state.pending_rows(sites={"gsmarena.com"}, canonical_site="gsmarena.com", limit=1)
            self.assertEqual(recovered[0].serial_number, serial)


class CommandLineTests(unittest.TestCase):
    def test_version_works_without_subcommand_and_has_build_fingerprint(self):
        completed = subprocess.run(
            [sys.executable, str(PROJECT / "filestorage/organise_mobiles.py"), "--version"],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(completed.stdout.strip(), f"mobile-organiser {__version__} (build {BUILD_ID})")


if __name__ == "__main__":
    unittest.main()
