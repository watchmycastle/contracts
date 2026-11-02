"""Contract tests only. No incident/spool implementation is imported."""
from copy import deepcopy
import hashlib
import json
import unittest

import contract as c
import build_fixtures
import validate_fixtures as fixtures


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.events = fixtures.load("valid-events.json")
        self.event = self.events["fresh_quiet"]
        self.raw = c.canonical_bytes(self.event)

    def test_all_fixture_shapes_ack_bindings_and_oracle_references(self):
        self.assertEqual(fixtures.check(), fixtures.load("fixtures.json")["expected_counts"])

    def test_reproducible_synthetic_fixture_authoring(self):
        for name, data in build_fixtures.build().items():
            with self.subTest(name=name):
                self.assertEqual(data, fixtures.load(name))

    def test_canonical_hash_ignores_whitespace_and_key_order(self):
        rearranged = dict(reversed(list(self.event.items())))
        parsed = c.decode_event(json.dumps(rearranged, indent=4).encode())
        self.assertEqual(c.event_sha256(parsed), hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(c.canonical_bytes(parsed), self.raw)

    def test_canonical_hash_detects_changed_identity_payload(self):
        self.assertEqual(self.event["event_id"], self.events["id_conflict"]["event_id"])
        self.assertNotEqual(c.event_sha256(self.event), c.event_sha256(self.events["id_conflict"]))
        self.assertEqual(self.event["sequence"], self.events["tuple_conflict"]["sequence"])
        self.assertNotEqual(self.event["event_id"], self.events["tuple_conflict"]["event_id"])

    def test_reject_duplicate_keys_including_nested(self):
        duplicate = self.raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        nested = self.raw.replace(b'"kind":"motion"', b'"kind":"motion","kind":"sound"')
        for value in (duplicate, nested):
            with self.subTest(value=value):
                with self.assertRaises(c.ContractError) as caught:
                    c.decode_event(value)
                self.assertEqual(caught.exception.code, "invalid_json")

    def test_person_detector_kind_is_accepted_and_others_rejected(self):
        person = dict(self.event, detector={"id": "people", "kind": "person"})
        c.validate_event(person)
        self.assertEqual(c.decode_event(c.canonical_bytes(person))["detector"]["kind"], "person")
        for kind in ("vehicle", "Person", "", None):
            with self.subTest(kind=kind), self.assertRaises(c.ContractError):
                c.validate_event(dict(self.event, detector={"id": "people", "kind": kind}))

    def test_reject_raw_non_json_and_unsupported_numeric_values(self):
        raw_cases = [b'\xef\xbb\xbf' + self.raw, b'\xff', b'{', b'[]', b'null',
                     self.raw.replace(b'"sequence":1', b'"sequence":1.0'),
                     self.raw.replace(b'"sequence":1', b'"sequence":1e0'),
                     self.raw.replace(b'"sequence":1', b'"sequence":NaN'),
                     self.raw.replace(b'"sequence":1', b'"sequence":Infinity'),
                     self.raw.replace(b'"camera-demo-a"', b'"\\ud800"')]
        for raw in raw_cases:
            with self.subTest(raw=raw):
                with self.assertRaises(c.ContractError):
                    c.decode_event(raw)

    def test_body_limit_counts_raw_bytes(self):
        padded = self.raw + b' ' * (c.BODY_LIMIT - len(self.raw))
        self.assertEqual(c.decode_event(padded), self.event)
        with self.assertRaises(c.ContractError) as caught:
            c.decode_event(padded + b' ')
        self.assertEqual(caught.exception.code, "oversized")

    def test_bounds_bool_and_float_are_not_integers(self):
        for field in ("schema_version", "sequence", "assignment_generation", "source_sequence"):
            for value in (True, False, 1.0):
                event = deepcopy(self.event)
                event[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(c.ContractError):
                        c.validate_event(event)

    def test_timestamp_precision_calendar_and_timezone(self):
        for value in ("2024-02-29T00:00:00Z", "2026-10-15T00:00:00.000001Z"):
            c.timestamp(value)
        for value in ("2026-02-29T00:00:00Z", "2026-10-15T24:00:00Z",
                      "2026-10-15T00:00:00z", "2026-10-15 00:00:00Z"):
            with self.subTest(value=value):
                with self.assertRaises(c.ContractError):
                    c.timestamp(value)

    def test_original_ack_next_sequence_is_not_current_camera_head(self):
        ack = next(x["ack"] for x in fixtures.load("acks.json")["valid"]
                   if x["event"] == "motion_trigger")
        c.validate_ack(ack, self.events["motion_trigger"])
        altered = dict(ack, next_expected_sequence=12)
        with self.assertRaises(c.ContractError):
            c.validate_ack(altered, self.events["motion_trigger"])

    def test_manifest_exact_coverage_and_hashes(self):
        root = fixtures.ROOT
        manifest = fixtures.ROOT / "SHA256SUMS"
        listed = {}
        for line in manifest.read_text().splitlines():
            digest, path = line.split("  ", 1)
            self.assertNotIn(path, listed)
            self.assertEqual(hashlib.sha256((root / path).read_bytes()).hexdigest(), digest, path)
            listed[path] = digest
        expected = {str(p.relative_to(root)) for p in fixtures.ROOT.rglob("*")
                    if p.is_file() and p.name != "SHA256SUMS" and "__pycache__" not in p.parts}
        self.assertEqual(set(listed), expected)


if __name__ == "__main__":
    unittest.main()
