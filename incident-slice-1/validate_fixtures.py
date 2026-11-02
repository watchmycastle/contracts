"""Validate frozen fixture shapes/bindings/references, not application behavior."""
import json
from pathlib import Path
import contract as c

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def check():
    manifest = load("fixtures.json")
    assert manifest["synthetic"] is True
    assert manifest["revision"] == c.REVISION
    for file in manifest["files"].values():
        assert Path(file).name == file and (ROOT / file).is_file()
    events = load(manifest["files"]["valid_events"])
    invalid = load(manifest["files"]["invalid_events"])
    acks = load(manifest["files"]["acks"])
    traces = load(manifest["files"]["scenarios"])
    assert traces["synthetic"] is True and traces["revision"] == c.REVISION
    counts = {"valid_events": len(events), "invalid_events": len(invalid),
              "valid_acks": len(acks["valid"]), "invalid_acks": len(acks["invalid"]),
              "scenarios": len(traces["scenarios"])}
    assert counts == manifest["expected_counts"], (counts, manifest["expected_counts"])
    for name, event in events.items():
        c.identifier(name)
        assert c.decode_event(c.canonical_bytes(event)) == event, name
    assert len({x["name"] for x in invalid}) == len(invalid)
    for item in invalid:
        try:
            c.decode_event(c.canonical_bytes(item["event"]))
        except c.ContractError as error:
            assert error.code == item["expected_error"], (item["name"], error.code)
        else:
            raise AssertionError("Invalid event accepted: " + item["name"])
    for item in acks["valid"]:
        c.validate_ack(item["ack"], events[item["event"]])
    assert len({x["name"] for x in acks["invalid"]}) == len(acks["invalid"])
    for item in acks["invalid"]:
        try:
            c.validate_ack(item["ack"], events[item["event"]])
        except c.ContractError:
            pass
        else:
            raise AssertionError("Invalid ACK accepted: " + item["name"])
    allowed = {"event", "count", "outbox_count", "baseline_active", "armed", "desired_version",
               "detection_types", "last_detection_at", "disposition", "ack_next_expected_sequence",
               "camera_next_sequence", "error", "expected_sequence"}
    assert len({x["name"] for x in traces["scenarios"]}) == len(traces["scenarios"])
    for trace in traces["scenarios"]:
        c.exact_keys(trace, {"name", "steps"})
        assert trace["steps"]
        for step in trace["steps"]:
            assert set(step) <= allowed and step["event"] in events
            for key in ("count", "outbox_count", "desired_version"):
                if key in step:
                    c.integer(step[key], low=0)
            for key in ("ack_next_expected_sequence", "camera_next_sequence", "expected_sequence"):
                if key in step:
                    c.integer(step[key])
            for key in ("armed", "baseline_active"):
                if key in step:
                    assert type(step[key]) is bool
            if "last_detection_at" in step:
                c.timestamp(step["last_detection_at"])
            if "detection_types" in step:
                assert step["detection_types"] == sorted(set(step["detection_types"]))
                for kind in step["detection_types"]:
                    c.member(kind, ("motion", "sound", "person"))
            if "disposition" in step:
                c.member(step["disposition"], ("accepted", "duplicate"))
            if "error" in step:
                c.member(step["error"], ("idempotency_conflict", "sequence_gap", "fenced",
                                         "detector_kind_conflict", "stale_sequence"))
    return counts


if __name__ == "__main__":
    print(json.dumps({"result": "PASS", "revision": c.REVISION, "synthetic": True,
                      "checked": check(), "application_behavior_executed": False}, sort_keys=True))
