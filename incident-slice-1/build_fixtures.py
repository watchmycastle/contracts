"""Reproducible SYNTHETIC fixture authoring; never runs a reducer or SQLite."""
from copy import deepcopy
import json
from pathlib import Path
import contract as c

ROOT = Path(__file__).resolve().parent


def build():
    events = {}
    serial = 0

    def event(name, seq, state, *, camera="camera-demo-a", kind="motion",
              semantics="transition", freshness="live", session=900, **changes):
        nonlocal serial
        serial += 1
        value = {
            "schema_version": 1,
            "event_id": f"00000000-0000-4000-8000-{serial:012d}",
            "event_type": "detector.observation", "producer_id": "synthetic-agent",
            "camera_id": camera, "assignment_generation": 1, "sequence": seq,
            "source_session_id": f"00000000-0000-4000-8000-{session:012d}",
            "source_sequence": None, "source_event_id": None, "occurred_at": None,
            "received_at": f"2026-10-15T00:00:{serial:02d}Z",
            "detector": {"id": kind + "-main", "kind": kind},
            "observation": {"state": state, "semantics": semantics,
                            "freshness": freshness, "clock_quality": "unknown"},
        }
        value.update(changes)
        c.validate_event(value)
        events[name] = value
        return value

    event("initial_active", 1, "active", semantics="initialization")
    event("quiet_baseline", 2, "quiet", semantics="initialization")
    event("motion_trigger", 3, "active")
    event("repeated_active", 4, "active")
    event("sound_baseline", 5, "quiet", kind="sound", semantics="resync")
    event("sound_trigger", 6, "active", kind="sound")
    event("quiet_does_not_resolve", 7, "quiet")
    event("replay_invalidates", 8, "quiet", freshness="replay")
    event("unarmed_active", 9, "active")
    event("quiet_again", 10, "quiet")
    event("motion_again", 11, "active", received_at="2026-10-15T00:00:01Z")
    event("b_quiet", 1, "quiet", camera="camera-demo-b", semantics="initialization")
    event("b_active", 2, "active", camera="camera-demo-b")
    event("fresh_quiet", 1, "quiet")
    event("uncertain_quiet", 2, "quiet", freshness="uncertain")
    event("active_after_uncertain", 3, "active")
    event("session_active", 2, "active", session=901)
    event("session_quiet", 3, "quiet", session=901, semantics="resync")
    event("session_trigger", 4, "active", session=901)
    event("unknown", 2, "unknown")
    event("initial_active_after_quiet", 2, "active", semantics="initialization")
    event("resync_active_after_quiet", 2, "active", semantics="resync")
    event("sequence_gap", 4, "active")
    event("fenced", 1, "quiet", assignment_generation=2)
    event("kind_conflict", 2, "quiet", detector={"id": "motion-main", "kind": "sound"})
    event("tuple_conflict", 1, "quiet")
    conflict = deepcopy(events["fresh_quiet"])
    conflict["observation"]["state"] = "active"
    events["id_conflict"] = conflict
    event("source_metadata", 1, "quiet", source_sequence=42, source_event_id="source-42",
          occurred_at="2026-10-14T23:59:59.123456Z", received_at="2026-10-15T00:00:00.1Z")
    event("last_sequence", c.MAX - 1, "quiet", assignment_generation=c.MAX)

    invalid = []

    def bad(name, path, value=None, *, delete=False, code="invalid_schema"):
        obj = deepcopy(events["fresh_quiet"])
        node = obj
        for key in path[:-1]:
            node = node[key]
        if delete:
            del node[path[-1]]
        else:
            node[path[-1]] = value
        invalid.append({"name": name, "expected_error": code, "event": obj})

    for name, value in (("unknown_major", 2), ("boolean_version", True)):
        bad(name, ["schema_version"], value, code="unsupported_schema")
    bad("deferred_health", ["event_type"], "camera.health", code="unsupported_schema")
    bad("deferred_gap", ["event_type"], "camera.gap", code="unsupported_schema")
    bad("missing_time", ["received_at"], delete=True)
    bad("extra_url", ["rtsp_url"], "forbidden-extra-field")
    bad("extra_credential", ["password"], "not-a-real-secret")
    bad("synthetic_wire_field", ["synthetic"], True)
    bad("extra_detector_field", ["detector", "label"], "forbidden")
    bad("extra_observation_field", ["observation", "trusted"], True)
    bad("missing_freshness", ["observation", "freshness"], delete=True)
    bad("bad_uuid", ["event_id"], "not-a-uuid")
    bad("nil_uuid", ["event_id"], "00000000-0000-0000-0000-000000000000")
    bad("uppercase_uuid", ["source_session_id"], "AAAAAAAA-0000-4000-8000-000000000001")
    bad("camera_not_id", ["camera_id"], "camera/a")
    bad("camera_too_long", ["camera_id"], "a" * 65)
    bad("producer_unicode", ["producer_id"], "agent-\u00e9")
    bad("generation_zero", ["assignment_generation"], 0)
    bad("generation_bool", ["assignment_generation"], True)
    bad("generation_overflow", ["assignment_generation"], c.MAX + 1)
    bad("sequence_zero", ["sequence"], 0)
    bad("sequence_negative", ["sequence"], -1)
    bad("sequence_string", ["sequence"], "1")
    bad("sequence_boolean", ["sequence"], True)
    bad("sequence_exhausted_sentinel", ["sequence"], c.MAX)
    bad("source_sequence_float", ["source_sequence"], 1.5, code="invalid_json")
    bad("source_id_unbounded", ["source_event_id"], "x" * 65)
    bad("invalid_calendar", ["received_at"], "2026-02-30T00:00:00Z")
    bad("non_utc", ["received_at"], "2026-10-15T00:00:00+00:00")
    bad("leap_second", ["occurred_at"], "2026-10-15T00:00:60Z")
    bad("too_many_fraction_digits", ["received_at"], "2026-10-15T00:00:00.1234567Z")
    bad("bad_kind", ["detector", "kind"], "vehicle")
    bad("bad_state", ["observation", "state"], "off")
    bad("bad_semantics", ["observation", "semantics"], "heartbeat")
    bad("bad_freshness", ["observation", "freshness"], "fresh")
    bad("bad_clock", ["observation", "clock_quality"], "good")

    def ack(name, disposition="accepted"):
        e = events[name]
        return {"schema_version": 1, **{key: e[key] for key in
                ("event_id", "producer_id", "camera_id", "assignment_generation")},
                "payload_sha256": c.event_sha256(e), "disposition": disposition,
                "durable": True, "accepted_sequence": e["sequence"],
                "next_expected_sequence": e["sequence"] + 1}

    acks = {"valid": [{"event": name, "ack": ack(name, disposition)}
                      for name, disposition in (("fresh_quiet", "accepted"),
                                                ("fresh_quiet", "duplicate"),
                                                ("motion_trigger", "accepted"),
                                                ("last_sequence", "duplicate"))],
            "invalid": []}
    changes = {"event_id": events["b_quiet"]["event_id"], "producer_id": "wrong-agent",
               "camera_id": "camera-demo-b", "assignment_generation": 2,
               "payload_sha256": "0" * 64, "durable": False,
               "accepted_sequence": 2, "next_expected_sequence": 3,
               "schema_version": 2, "disposition": "queued"}
    for key, value in changes.items():
        receipt = ack("fresh_quiet")
        receipt[key] = value
        acks["invalid"].append({"name": "wrong_" + key, "event": "fresh_quiet", "ack": receipt})
    for name, key, value in (("integer_durable", "durable", 1),
                             ("bool_generation", "assignment_generation", True),
                             ("bool_sequence", "accepted_sequence", True)):
        receipt = ack("fresh_quiet")
        receipt[key] = value
        acks["invalid"].append({"name": name, "event": "fresh_quiet", "ack": receipt})
    receipt = ack("fresh_quiet")
    del receipt["payload_sha256"]
    acks["invalid"].append({"name": "missing_hash", "event": "fresh_quiet", "ack": receipt})
    receipt = ack("fresh_quiet")
    receipt["extra"] = "forbidden"
    acks["invalid"].append({"name": "extra_field", "event": "fresh_quiet", "ack": receipt})

    # Explicit handwritten expected results, not outputs of an implementation.
    scenarios = {"synthetic": True, "revision": c.REVISION, "scenarios": [
        {"name": "initial-active-grouping", "steps": [
            {"event": "initial_active", "count": 0, "outbox_count": 0, "baseline_active": True},
            {"event": "quiet_baseline", "count": 0, "outbox_count": 0, "armed": True},
            {"event": "motion_trigger", "count": 1, "outbox_count": 1, "desired_version": 1},
            {"event": "repeated_active", "count": 1, "outbox_count": 1},
            {"event": "sound_baseline", "count": 1, "outbox_count": 1},
            {"event": "sound_trigger", "count": 2, "outbox_count": 2,
             "detection_types": ["motion", "sound"]},
            {"event": "quiet_does_not_resolve", "count": 2, "outbox_count": 2},
            {"event": "replay_invalidates", "count": 2, "outbox_count": 2, "armed": False},
            {"event": "unarmed_active", "count": 2, "outbox_count": 2},
            {"event": "quiet_again", "count": 2, "outbox_count": 2},
            {"event": "motion_again", "count": 3, "outbox_count": 3,
             "last_detection_at": events["sound_trigger"]["received_at"]},
            {"event": "motion_trigger", "disposition": "duplicate", "count": 3,
             "outbox_count": 3, "ack_next_expected_sequence": 4, "camera_next_sequence": 12},
        ]},
        {"name": "uncertain-cannot-arm", "steps": [
            {"event": "fresh_quiet", "count": 0, "armed": True},
            {"event": "uncertain_quiet", "count": 0, "armed": False},
            {"event": "active_after_uncertain", "count": 0, "baseline_active": True},
        ]},
        {"name": "new-session-invalidates", "steps": [
            {"event": "fresh_quiet", "count": 0, "armed": True},
            {"event": "session_active", "count": 0, "baseline_active": True},
            {"event": "session_quiet", "count": 0, "armed": True},
            {"event": "session_trigger", "count": 1, "outbox_count": 1},
        ]},
        {"name": "contextual-errors-no-effects", "steps": [
            {"event": "fresh_quiet", "count": 0, "camera_next_sequence": 2},
            {"event": "id_conflict", "error": "idempotency_conflict"},
            {"event": "tuple_conflict", "error": "idempotency_conflict"},
            {"event": "sequence_gap", "error": "sequence_gap", "expected_sequence": 2},
            {"event": "fenced", "error": "fenced"},
            {"event": "kind_conflict", "error": "detector_kind_conflict"},
            {"event": "fresh_quiet", "disposition": "duplicate", "camera_next_sequence": 2},
        ]},
        {"name": "camera-isolation", "steps": [
            {"event": "fresh_quiet", "count": 0, "outbox_count": 0},
            {"event": "b_quiet", "count": 0, "outbox_count": 0},
            {"event": "b_active", "count": 1, "outbox_count": 1, "desired_version": 1},
            {"event": "initial_active_after_quiet", "count": 0, "outbox_count": 1},
        ]},
        {"name": "unknown-is-not-clear", "steps": [
            {"event": "fresh_quiet", "count": 0, "armed": True},
            {"event": "unknown", "count": 0, "armed": False},
            {"event": "active_after_uncertain", "count": 0},
        ]},
        {"name": "resync-active-is-not-trigger", "steps": [
            {"event": "fresh_quiet", "count": 0, "armed": True},
            {"event": "resync_active_after_quiet", "count": 0, "baseline_active": True},
        ]},
    ]}
    manifest = {"synthetic": True, "revision": c.REVISION,
                "files": {"valid_events": "valid-events.json", "invalid_events": "invalid-events.json",
                          "acks": "acks.json", "scenarios": "scenarios.json"},
                "expected_counts": {"valid_events": len(events), "invalid_events": len(invalid),
                                    "valid_acks": len(acks["valid"]), "invalid_acks": len(acks["invalid"]),
                                    "scenarios": len(scenarios["scenarios"])}}
    return {"valid-events.json": events, "invalid-events.json": invalid,
            "acks.json": acks, "scenarios.json": scenarios, "fixtures.json": manifest}


if __name__ == "__main__":
    for filename, value in build().items():
        path = ROOT / filename
        if path.exists():
            raise SystemExit("Refusing overwrite; reviewed revision required: " + filename)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Wrote explicitly synthetic contract fixtures; no application executed.")
