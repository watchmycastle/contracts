"""Contract/fixture/signature checks ONLY. No listeners or application execution."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "incident-slice-1"))
import contract as frozen
import transport_oracle as oracle


class TransportContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = json.loads((HERE / "fixtures.json").read_text())
        cls.records = [json.loads(line) for line in (HERE / "synthetic.jsonl").read_bytes().splitlines()]
        cls.event = dict(cls.records[0]["template"], producer_id="producer-a", camera_id="camera-a",
                         assignment_generation=1, sequence=1,
                         event_id="00000000-0000-4000-8000-000000000001")
        cls.ack = {"schema_version": 1, "event_id": cls.event["event_id"], "producer_id": "producer-a",
                   "camera_id": "camera-a", "assignment_generation": 1,
                   "payload_sha256": frozen.event_sha256(cls.event), "disposition": "accepted",
                   "durable": True, "accepted_sequence": 1, "next_expected_sequence": 2}

    def test_valid_config_fixtures(self):
        for role in ("receiver", "sender"):
            oracle.validate_config(role, self.fixtures[role + "_config"])
            assignments = self.fixtures["assignments" if role == "receiver" else "sender_assignments"]
            oracle.validate_credentials(role, self.fixtures[role + "_credentials"], assignments)

    def test_config_rejects_omissions_extras_types_and_collisions(self):
        for role in ("receiver", "sender"):
            base = self.fixtures[role + "_config"]
            for key in base:
                value = copy.deepcopy(base); del value[key]
                with self.subTest(role=role, missing=key), self.assertRaises(oracle.OracleError):
                    oracle.validate_config(role, value)
            for key, bad in [("synthetic", False), ("synthetic", 1), ("schema_version", True),
                             ("db_path", ":memory:"), ("db_path", "file:/x"),
                             ("db_path", "relative.db"), ("db_path", "/"),
                             ("db_path", "/x\x00"), ("db_path", "/x\ud800"),
                             ("db_path", base["assignments_path"]), ("token", "do-not-accept")]:
                value = dict(base, **{key: bad})
                with self.subTest(role=role, key=key, bad=repr(bad)), self.assertRaises(oracle.OracleError):
                    oracle.validate_config(role, value)
        for host in ("localhost", "::1", "0.0.0.0", "127.1", "127.0.0.1 "):
            with self.subTest(host=host), self.assertRaises(oracle.OracleError):
                oracle.validate_config("receiver", dict(self.fixtures["receiver_config"], listen_host=host))
        for port in (True, -1, 65536, "0", 0.0):
            with self.subTest(port=port), self.assertRaises(oracle.OracleError):
                oracle.validate_config("receiver", dict(self.fixtures["receiver_config"], listen_port=port))

    def test_origin_restriction(self):
        for origin in self.fixtures["invalid_origins"]:
            with self.subTest(origin=origin), self.assertRaises(oracle.OracleError):
                oracle.origin_port(origin)
        self.assertEqual(oracle.origin_port("http://127.0.0.1:1"), 1)
        self.assertEqual(oracle.origin_port("http://127.0.0.1:65535"), 65535)

    def test_json_file_strictness(self):
        for data in (b'\xef\xbb\xbf{}', b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":1.0}',
                     b'{"x":Infinity}', b'\xff', b'{' + b' ' * 65536 + b'}'):
            with self.subTest(data=data[:30]), self.assertRaises(oracle.OracleError):
                oracle.strict_json(data)

    def test_credentials_do_not_learn_assignments(self):
        base = self.fixtures["receiver_credentials"]
        for identity in ({"producer_id": "producer-b", "camera_ids": ["camera-a"]},
                         {"producer_id": "producer-a", "camera_ids": ["absent"]},
                         {"producer_id": "producer-a", "camera_ids": []},
                         {"producer_id": "producer-a", "camera_ids": ["camera-a", "camera-a"]},
                         {"producer_id": "producer-a", "camera_ids": [True]}):
            value = copy.deepcopy(base); value["tokens"]["slice2-dummy-a-not-secret"] = identity
            with self.subTest(identity=identity), self.assertRaises(oracle.OracleError):
                oracle.validate_credentials("receiver", value, self.fixtures["assignments"])
        for token in ("real-token", "slice2-dummy-", "slice2-dummy-\n", "slice2-dummy-" + "x" * 65):
            value = dict(self.fixtures["sender_credentials"], token=token)
            with self.subTest(token=token), self.assertRaises(oracle.OracleError):
                oracle.validate_credentials("sender", value, self.fixtures["sender_assignments"])
        with self.assertRaises(oracle.OracleError):
            oracle.validate_credentials("sender", self.fixtures["sender_credentials"], self.fixtures["assignments"])

    def test_auth_identity_and_scope(self):
        credentials = self.fixtures["receiver_credentials"]
        header = "Bearer slice2-dummy-a-not-secret"
        identity = oracle.authenticate([header], credentials)
        self.assertEqual(oracle.authorize(identity, self.event), "producer-a")
        for values in ([], [header, header], ["Bearer slice2-dummy-wrong"], [header + " "],
                       [header.lower()], ["Basic abc"], ["Bearer \ud800"]):
            with self.subTest(values=values), self.assertRaisesRegex(oracle.OracleError, "unauthenticated"):
                oracle.authenticate(values, credentials)
        for event in (dict(self.event, producer_id="producer-b"), dict(self.event, camera_id="camera-b")):
            with self.assertRaisesRegex(oracle.OracleError, "unauthorized"):
                oracle.authorize(identity, event)

    def test_template_fixture_shapes(self):
        self.assertEqual(len(self.records), self.fixtures["expected_fixture_lines"])
        self.assertLessEqual((HERE / "synthetic.jsonl").stat().st_size, 1048576)
        for record in self.records:
            oracle.fixture_record(record, self.fixtures["sender_assignments"])
            self.assertLessEqual(len(frozen.canonical_bytes(record)) + 1, 65536)
        for key, bad in (("synthetic", False), ("assignment_generation", True), ("camera_id", "camera-b")):
            with self.subTest(key=key), self.assertRaisesRegex(oracle.OracleError, "invalid_fixture"):
                oracle.fixture_record(dict(self.records[0], **{key: bad}), self.fixtures["sender_assignments"])
        record = copy.deepcopy(self.records[0]); record["template"]["event_id"] = self.event["event_id"]
        with self.assertRaises(oracle.OracleError):
            oracle.fixture_record(record, self.fixtures["sender_assignments"])

    def test_error_map_roundtrip_and_size(self):
        fixture_map = json.loads((HERE / "http-cases.json").read_text())["error_status"]
        self.assertEqual(oracle.ERROR_STATUS, fixture_map)
        for code, status in fixture_map.items():
            body = oracle.error_body(code, 1 if code == "sequence_gap" else None)
            payload = frozen.canonical_bytes(body)
            self.assertLessEqual(len(payload), oracle.RESPONSE_LIMIT)
            self.assertEqual(oracle.known_error(status, payload), code)
            self.assertEqual(set(body), {"schema_version", "error"})
            action, actual_code = oracle.classify_response(status, payload, self.event)
            self.assertEqual(actual_code, code)
            self.assertEqual(action, "retry" if status == 408 or status >= 500 else "quarantine")
        with self.assertRaises(oracle.OracleError):
            oracle.error_body("sequence_gap", True)
        with self.assertRaises(oracle.OracleError):
            oracle.error_body("unknown")

    def test_errors_never_echo_untrusted_text(self):
        body = {"schema_version": 1, "error": {"code": "do-not-echo-secret"}}
        self.assertEqual(oracle.classify_response(400, frozen.canonical_bytes(body), self.event),
                         ("quarantine", "http_rejected"))
        for extra in ({"details": "secret"}, {"expected_sequence": None}):
            body = oracle.error_body("bad_request"); body["error"].update(extra)
            self.assertIsNone(oracle.known_error(400, frozen.canonical_bytes(body)))
        body = oracle.error_body("bad_request"); body["schema_version"] = True
        self.assertIsNone(oracle.known_error(400, frozen.canonical_bytes(body)))

    def test_ack_is_slice1_unchanged(self):
        for disposition in ("accepted", "duplicate"):
            ack = dict(self.ack, disposition=disposition)
            frozen.validate_ack(ack, self.event)
            self.assertEqual(set(ack), frozen.ACK_KEYS)
            self.assertEqual(oracle.classify_response(200, frozen.canonical_bytes(ack), self.event), ("ack", None))
        for key, bad in (("event_id", "00000000-0000-4000-8000-000000000002"),
                         ("producer_id", "producer-b"), ("camera_id", "camera-b"),
                         ("assignment_generation", 2), ("payload_sha256", "0" * 64),
                         ("durable", False), ("durable", 1), ("accepted_sequence", 2),
                         ("next_expected_sequence", 3), ("schema_version", True),
                         ("disposition", "maybe"), ("extra", "x")):
            with self.subTest(key=key, bad=bad):
                payload = frozen.canonical_bytes(dict(self.ack, **{key: bad}))
                self.assertEqual(oracle.classify_response(200, payload, self.event), ("retry", "invalid_ack"))

    def test_status_and_frame_precede_ack(self):
        payload = frozen.canonical_bytes(self.ack)
        for status in (201, 204, 400, 401, 403, 409, 422):
            self.assertEqual(oracle.classify_response(status, payload, self.event), ("quarantine", "http_rejected"))
        for status in (408, 429, 500, 503, 599):
            self.assertEqual(oracle.classify_response(status, payload, self.event), ("retry", "http_transient"))
        for status in (301, 302, 303, 307, 308):
            self.assertEqual(oracle.classify_response(status, payload, self.event), ("quarantine", "redirect_refused"))
        self.assertEqual(oracle.classify_response(100, payload, self.event), ("retry", "invalid_response"))
        for status in (200, 302, 400, 503):
            self.assertEqual(oracle.classify_response(status, payload, self.event, framing_ok=False),
                             ("retry", "invalid_response"))
        for payload in (b"", b" " * 4097):
            self.assertEqual(oracle.classify_response(200, payload, self.event), ("retry", "invalid_response"))
        payload = frozen.canonical_bytes(self.ack)
        duplicate = b'{"durable":false,' + payload[1:]
        self.assertEqual(oracle.classify_response(200, duplicate, self.event), ("retry", "invalid_ack"))

    def test_ready_shape_is_nonleaky(self):
        for role in ("receiver", "sender"):
            value = {"event": "ready", "role": role, "synthetic": True}
            if role == "receiver": value.update(host="127.0.0.1", port=12345)
            oracle.validate_ready(role, value)
            with self.assertRaises(oracle.OracleError):
                oracle.validate_ready(role, dict(value, db_path="/secret"))
        for port in (0, True, 65536):
            with self.assertRaises(oracle.OracleError):
                oracle.validate_ready("receiver", {"event": "ready", "role": "receiver", "synthetic": True,
                                                   "host": "127.0.0.1", "port": port})

    def test_static_http_vectors_and_acceptance_names(self):
        spec = json.loads((HERE / "http-cases.json").read_text())
        self.assertTrue(spec["synthetic"])
        self.assertEqual(len(spec["cases"]), spec["expected_case_count"])
        self.assertEqual(len({c["name"] for c in spec["cases"]}), len(spec["cases"]))
        for case in spec["cases"]:
            self.assertEqual(oracle.ERROR_STATUS[case["code"]], case["status"])
        plan = (HERE / "SPEC.md").read_text()
        for name in self.fixtures["acceptance_scenarios"]:
            self.assertIn('`' + name + '`', plan)



if __name__ == "__main__":
    unittest.main()
