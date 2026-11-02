# incident-slice-1-r1 — synthetic-only frozen profile

Normative lifecycle/interfaces/handoff: [SPEC.md](SPEC.md).
Normative executable shape/ACK validation: `contract.py` (Python standard library only).
No service, sender, SQLite implementation, camera adapter or network listener is included.

**Quiet-before-trigger is provisional synthetic policy, not production acceptance. Explicit user choice is required before pilot.** The strengthened ACK and internal projections are this profile's contracts, not globally accepted production APIs. Real security choices remain blocked/deferred.

## Artifacts

- `fixtures.json`: synthetic marker, revision, file index and exact expected counts.
- `valid-events.json`: named schema-valid envelopes. Some are intentionally contextual conflicts and are NOT valid new accepts after every history.
- `invalid-events.json`: named invalid envelopes with expected validator error code. These are valid JSON documents containing semantically invalid events (one float is invalid at strict decoding).
- `acks.json`: accepted/duplicate receipts and wrong-identity/schema/durability/hash examples.
- `scenarios.json`: static handwritten reducer/ordering oracles, not computed application results.
- `build_fixtures.py`: deterministic authoring source; refuses overwriting existing fixture files. Tests compare its in-memory output to checked-in JSON. Do not regenerate a frozen revision casually.
- `validate_fixtures.py`: validates every envelope/ACK and scenario shape/reference/count.
- `test_contract.py`: unittest coverage of canonicalization, bounds, JSON pitfalls, timestamp validation, fixtures and SHA256 integrity/coverage.
- `SHA256SUMS`: paths relative to this folder; covers every file in it, including `SPEC.md`, excluding itself and Python bytecode. Hashes detect drift, not signer identity or trusted provenance.

## Scenario notation

Every named scenario starts a fresh incident store with camera-demo-a and camera-demo-b both assigned producer synthetic-agent, generation 1. Steps default to successful accepted ingest. `event` references valid-events.json; `disposition=duplicate` expects duplicate, `error` expects ContractError and zero mutation. A fresh store starts each next_expected_sequence at 1.

All expectations are **assertions for future module tests**, not proof of executed behavior. Fields are selected post-step assertions:

- `count`: open incident detection_count for this event's camera, or 0 if absent; for count>0 incident.version=count in this command-free profile.
- `outbox_count`: global outbox row count across both cameras.
- `armed`, `baseline_active`: state of this event's detector.
- `desired_version`: this camera's internal desired_version.
- `detection_types`, `last_detection_at`: current open incident fields.
- `camera_next_sequence`: persisted camera next_expected_sequence.
- `ack_next_expected_sequence`: returned original receipt value; it can lag camera_next_sequence on replay.
- `expected_sequence`: error attribute for an order gap.

Open incident identity remains stable within a scenario; desired stays true/version 1 once opened. Error steps leave ALL authority state unchanged. Scenario tests also assert absence of cross-camera effects. Source-session restart must invalidate every existing detector latch, not merely the event's detector (add that multi-detector case in the store implementation tests).

## Verify from the repository root

```sh
python3 -B incident-slice-1/validate_fixtures.py
python3 -B -m unittest discover -s contracts/incident-slice-1 -p 'test_contract.py' -v
sha256sum --check incident-slice-1/SHA256SUMS
```

No third-party schema engine or install is needed. This is a deliberately restricted JSON validator, not a claim to implement JSON Schema. Machine checks do not execute the reducer, prove SQLite durability, authenticate a peer or prove camera capability. Two later independent bounded Claude tasks are in section 7 of the normative plan; they must not edit frozen artifacts.
