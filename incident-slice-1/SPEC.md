# Incident slice 1: synthetic contract freeze and implementation handoff

**Goal:** Freeze only a synthetic observation → durable incident/desired/outbox and independent durable spool boundary.
**Architecture:** Two independent Python modules with separate SQLite files; no shared database and no additional service. The incident module owns the reducer; the spool owns allocation/retry, never incident policy.
**Tech Stack:** Python standard library only, SQLite WAL/foreign_keys=ON/synchronous=FULL/busy_timeout=5000, local temporary files. Future test transport is explicit synthetic mode, literal `127.0.0.1` or `::1` only, never wildcard or LAN binding.

## Status and authority

Freeze ID: **incident-slice-1-r1**. This is a frozen **synthetic development profile**, not acceptance of production security or initial-active behavior. `incident-slice-1/SHA256SUMS` pins this document and all contract artifacts (excluding itself and bytecode). A modification requires a new reviewed revision and regenerated manifest, not a silent overwrite during implementation. No production wire compatibility is promised for this profile.

Reviewed sources: `incident-platform-contracts.md`, `incident-platform-implementation.md`, `incident-dashboard-security.md`, and ADR-011. The requested literal `docs/plans/implementation.md` does not exist; the actual implementation document was located and read, not renamed. No existing author document is changed. ADR-011's separate agent/incident ownership is preserved.

**Quiet-before-trigger is a provisional synthetic policy requiring explicit user acceptance before any pilot.** Initial active is not treated as safe; it is active/unarmed with a visible baseline warning and may represent a missed real event. No security policy is promoted to Accepted. Identity provider, accounts, ACLs, service credentials, real TLS, token bypass closure, media rooms/revocation and production transport remain undecided/out of scope.

Reconciliation, not silent global decisions:

| Disagreement/ambiguity | Slice decision and boundary |
|---|---|
| Candidate initial-active default vs pending user tradeoff | Exercise quiet-before-trigger synthetically only; pilot blocked pending user decision. |
| Candidate ACK lacks camera/generation/payload binding | Add required producer/camera/generation/SHA256 fields in this profile; keep original identity/sequence fields. Both owners use these fixtures. Do not call this a compatible change to a deployed API. |
| Raw byte vs semantic duplicate identity | Hash canonical UTF-8 JSON as specified below; spool persists those exact canonical bytes. Whitespace/key order alone is not conflict. |
| Initial desired version | Internal idle sentinel version 0; first start is 1. Sentinel is not the proposed public publisher API. |
| Candidate health/gap and capacity eviction | Not implemented here; reject non-observation types. Hard admission backpressure, no eviction, fabricated gap or sequence skip. |
| `/api/v1` vs `/v1`, resolve_harmless vs mark_harmless | Defer browser routes and all commands; neither spelling is frozen here. |
| Read receipts in dashboard vs notification service | Defer; recommend notification authority from candidate contracts, requiring later cross-owner review. |
| Token TTL, room epoch, auth provider and actor checks | No selection in this slice. No authentication claim from a trusted test argument. |

The parent can dispatch the two module tasks against this revision. If it wants different ACK identity, session invalidation, canonicalization or capacity behavior, stop and revise this contract before dispatch; do not let lanes choose separately.

## 1. Envelope and strict validation

Normative executable shape validation is `incident-slice-1/contract.py`; `fixtures.json` marks all samples `synthetic:true` outside the wire envelope. Schema version is integer 1; only `detector.observation` is accepted. All fields are required, no extra keys at any object level. Bounds/types are literal; booleans are not integers. Body limit 65536 UTF-8 bytes; reject duplicate JSON keys, invalid UTF-8, BOM, NaN/Infinity, surrogates, floating-point numbers and malformed dates. UUIDs use canonical lowercase hyphenated non-nil form. IDs use ASCII `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`. Timestamps use UTC `YYYY-MM-DDTHH:MM:SS[.ffffff]Z`, 1–6 optional fractional digits and valid calendar dates. No URLs, credentials, arbitrary metadata or synthetic flag on the wire.

Envelope keys exactly:

```
schema_version, event_id, event_type, producer_id, camera_id,
assignment_generation, sequence, source_session_id, source_sequence,
source_event_id, occurred_at, received_at, detector, observation
```

`detector={id,kind}` with kind motion|sound|person (person added 2026-10-22 for on-camera people detection; r1 fixtures unchanged). `observation={state,semantics,freshness,clock_quality}` with state active|quiet|unknown, semantics transition|initialization|resync, freshness live|replay|uncertain, clock_quality trusted|skewed|unknown. `occurred_at` may be null. `source_sequence` is null or integer 1..MAX; `source_event_id` null or bounded ID. These source fields are evidence only, not authoritative ordering. `MAX=9007199254740991`; generation 1..MAX; event sequence 1..MAX-1. MAX is an exhausted next-sequence sentinel: fail allocation/ingest, never wrap. This explicit restriction avoids an unrepresentable next-sequence ACK.

`decode_event(payload: bytes) -> dict` validates then returns the parsed object. `canonical_bytes(obj: dict) -> bytes` is `json.dumps(sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode('utf-8')`; call validation first. `event_sha256(event: dict) -> str` is lowercase SHA256 of canonical bytes. `ContractError(code, *, expected_sequence=None)` exposes `.code` and `.expected_sequence`; it is a validation error, not an HTTP response.

## 2. Ordering, fencing and duplicate identity

Assignments are explicit immutable configuration: `{camera_id: {producer_id: str, assignment_generation: int}}`. Both modules persist and verify this map at startup; mismatch against existing DB fails startup `assignment_mismatch`. Unknown camera/wrong trusted producer fails `unauthorized`; correct producer but wrong generation fails `fenced`. Never learn assignments from an envelope. No automatic generation replacement API, DB restore or reset; parent must separately authorize a migration/new generation if needed. Ordinary restart retains sequence, receipts, reducer and spool. New source session changes neither assignment nor sequence.

Incident transaction order: decode → verify trusted producer and configured camera/generation → BEGIN IMMEDIATE → check current persisted assignment → dedupe both `(producer_id,event_id)` and `(producer_id,camera_id,generation,sequence)` → check expected sequence → reduce/write → COMMIT → return ACK. Validate/auth-context check even before returning duplicate. Any collision where canonical payload differs is `idempotency_conflict`; same sequence with different event_id also conflicts. Exact known duplicate returns original receipt fields, with disposition changed to duplicate, even if newer events have committed. Otherwise lower unknown sequence is stale_sequence; higher is sequence_gap with expected_sequence. Conflict takes precedence over order errors. Detector ID cannot change kind within a camera: detector_kind_conflict, with no write. Failed requests never consume sequence.

At first event of a different source_session_id, invalidate all detector latches for that camera (unknown/unarmed, warning=false) before applying that event; leave open incident and desired unchanged. Persist last session. The synthetic producer must never reuse a retired session ID for fresh observations; exact old event retries remain valid dedupe and never reset state. Session IDs are opaque, not ordered or proof of trusted source freshness. Source replay ambiguity is not solved by this profile.

## 3. Reducer truth table (only observation events)

Default detector: state unknown, armed false, baseline_active false. No timer. Qualifying freshness means `freshness=live`; clock_quality concerns source time and does not change synthetic freshness. The fake adapter explicitly asserts a current quiet baseline; this is not proof a real adapter can do so.

| Input | Result |
|---|---|
| Any replay/uncertain observation, or state unknown | Set detector unknown/unarmed; clear baseline_active; no incident mutation. |
| Live quiet, any semantics | Quiet/armed; clear baseline_active; do not resolve incident. |
| Live active, initialization or resync | Active/unarmed, baseline_active=true; no incident, even if previously armed. |
| Live active transition, prior quiet AND armed | Active/unarmed, baseline_active=false; one qualifying activation. |
| Live active transition otherwise | Active/unarmed; set baseline_active=true if prior state was not active, otherwise retain warning; no qualifying activation. |

A qualifying activation opens one incident if absent, otherwise increments the same open incident's version and detection_count. First open version/count 1; sorted unique detection_types and triggering_detector_ids accumulate qualifying activations only. Times use event received_at: first_detection_at is opening receipt, last_detection_at is maximum so far (compare parsed UTC times, not mixed-fraction strings). Source time is retained in inbox, never used to order. Repeated active assertions and duplicates do not increment counts. Unknown/reconnect never closes an incident. A quiet then fresh transition can increment count even for the same detector. Multiple detectors/cameras remain isolated. Commands/resolution/re-arm-after-resolution are deferred, not partially implemented. (2026-10-22: the incident service now implements mark-harmless per incident-platform-contracts.md rules 4 and 6 in its schema v2; the slice-1 reducer and these fixtures are unchanged.)

Internal incident projection exactly matches the candidate example keys: schema_version, incident_id, camera_id, state='open', version, first_detection_at, last_detection_at, time_basis='agent_received', detection_types, detection_count, triggering_detector_ids, resolved_at=null, resolved_by=null, resolution=null. ID source is injectable. IDs/timestamps must validate under this profile.

## 4. Atomic authority and durable ACK

One local SQLite file, one logical writer/module; concurrent calls serialize via BEGIN IMMEDIATE (do not bypass SQLite constraints). Unique partial index enforces one open incident/camera. Persist schema_migrations/version/checksum; incompatible schema/checksum fails startup, never recreates DB. Keep inbox/hash/receipt and outbox indefinitely for this synthetic run; no GC. Storage failure rolls back; no success object before COMMIT. Database errors propagate as sqlite3.Error for the later adapter to map to unavailable; no blanket swallowing or success fallback.

An accepted observation atomically persists inbox envelope/hash/receipt, expected sequence, session and detector state, optional incident mutation, optional desired state change, and optional outbox row. First activation sets desired publishing=true/version 1/incident_id atomically with incident.opened. Later qualifying activations produce incident.updated but do not bump desired version. Quiet/nonqualifying observations persist inbox/reducer only. Outbox delivery is not part of this transaction or this slice.

Internal desired shape: `{camera_id,desired_version,publishing,incident_id}`; idle `{...,0,false,null}` exists after camera configuration. Internal outbox shape: `{cursor,event_id,type,camera_id,incident}` with global increasing positive cursor, new UUID event_id, type incident.opened|incident.updated, and full incident projection. These are internal read models, NOT the full public publisher/feed schemas (epochs, rooms, consumer ACKs are deferred).

ACK keys exactly:

```
{schema_version:1, event_id, producer_id, camera_id, assignment_generation,
 payload_sha256, disposition:'accepted'|'duplicate', durable:true,
 accepted_sequence, next_expected_sequence}
```

accepted_sequence equals the envelope sequence; next_expected_sequence is that sequence+1 **at original commit**, not the camera's current head on a later replay. No gaps in this profile. `validate_ack(ack: dict, event: dict) -> None` rejects any malformed or mismatching field. This helper does not authenticate a peer. Durable means configured local FULL commit, not replicated HA. After lost response, the same event is safe to replay; the spool never treats a timeout as evidence of no commit.

## 5. Spool/retry and bounded backpressure

Spool DB is separate from incident DB. `enqueue` accepts a validated full envelope **template** with `producer_id`, `camera_id`, `assignment_generation`, `sequence` and `event_id` omitted; it does not take a caller-selected sequence or event ID. Other fields are as section 1. Method arguments supply camera, generation and source_session_id is in template. Allocate event UUID, next per-camera sequence and exact canonical payload in one transaction. On failure allocate nothing. Persist hash/bytes/attempts/next_attempt_at/quarantine code. Never mutate an enqueued event body or reuse its identity for altered content.

Default limits: 10000 pending rows/camera; 32 MiB canonical payload bytes/camera and 256 MiB global; configurable smaller in tests. Count quarantined rows toward limits. These bound admitted payloads, NOT actual SQLite/WAL filesystem size; disk exhaustion remains a separate error. At capacity fail `capacity` with no write/sequence allocation and preserve every existing row. Suspend synthetic acquisition rather than inventing durable loss/gaps. Automatic eviction and gap synthesis are out of scope; explicitly not a production continuous-acquisition buffer policy.

Per camera, only lowest pending sequence is eligible. Quarantined head blocks only that camera. Pick due heads using lexicographic camera round-robin, persisting the last selected camera; initial pointer before first camera. One caller synchronously dispatches returned work (no parallel threads/sender implementation in this batch). One unresolved head/camera: later rows cannot overtake, including after restart. Reclaiming a due head represents retry of the same event, not new allocation.

`claim_due(now: float) -> dict|None` uses finite UTC Unix seconds from an injected/test clock, marks an attempt and persists its next retry BEFORE returning payload. attempts increments from 0 to 1. Backoff after attempt n: uniform jitter in `[0.5*cap,cap]`, cap=`min(60,2**min(n-1,6))` seconds; injected `jitter(low,high)` must return finite in-range value. This is the slice's explicit jitter choice around the candidate 1–60s cap, not a production SLA. Claim returns `{payload: bytes, attempts: int, next_attempt_at: float}`. All fields survive process restart; repeated timeout attempts continue indefinitely within queue limits, never regenerate envelope/ID. Caller may retry only after next_attempt_at; no wall-clock rollback compensation beyond waiting until stored deadline.

`record_failure(event_id, code, *, permanent)` persists bounded code (ASCII ID format). Permanent failures quarantine; transient leaves the scheduled retry unchanged. Network/timeouts/408/429/5xx are transient. Schema, assignment/auth, kind and idempotency conflicts quarantine; sequence_gap/stale_sequence also quarantine for explicit operator investigation (no silent re-sequence). Invalid/mismatched ACK is not dequeue permission: `acknowledge` returns false and leaves pending retry. Exceptions from storage must propagate, not return a misleading success.

`acknowledge(ack: dict) -> bool` finds only the matching camera head/event, validates all identity/hash/sequence fields and durable literal true, then deletes exactly that row in a committed transaction. Accepted and duplicate work identically. Unknown/already removed event returns false; malformed/mismatching ACK false; no other row removed. It cannot authenticate transport: future loopback harness must verify its configured fake peer before calling. HTTP errors are not ACKs. No real credentials or authentication provider selected here.

## 6. Exact independent module interfaces

Shared contract module is the frozen `contract.py` in this repository, exposed read-only with `PYTHONPATH=../contracts/incident-slice-1`. Both lanes `import contract as frozen`; do not vendor/edit it independently. Parent may later package it deliberately. Tests receive fixture root through `INCIDENT_SLICE_CONTRACT_DIR`, defaulting to that same absolute directory. Runtime modules use no cross-lane imports.

**Incident** (`incident_service/store.py`, optional pure `policy.py`):

```python
Store(db_path, *, assignments: dict, clock: Callable[[], str],
      new_id: Callable[[], str], before_commit: Callable[[], None] | None = None)
store.apply_event(payload: bytes, *, trusted_producer: str) -> dict  # ACK
store.snapshot(camera_id: str) -> dict
store.outbox(after: int = 0) -> list[dict]
store.close() -> None
```

Snapshot exact keys: `camera_id,next_expected_sequence,source_session_id,detectors,incident,desired`. Initial source_session_id=null, incident=null. Detectors sorted by id: `{id,kind,state,armed,baseline_active}`. Desired/incident shapes above. outbox returns all cursor>after in order, consistent read, no write. snapshot and outbox separately are not an atomic feed bootstrap. `clock` returns valid UTC timestamp for internal accepted_at; new_id produces unique valid UUIDs. before_commit runs after all writes but before COMMIT for a new ingest only; raising rolls back everything and propagates. It is a test seam, no HTTP flag. Initialize schema/config atomically, but do not invoke this hook for initialization or duplicate reads.

**Spool** (`camera_agent/spool.py`):

```python
Spool(db_path, *, assignments: dict, new_id: Callable[[], str],
      jitter: Callable[[float, float], float],
      max_rows_per_camera: int = 10000,
      max_bytes_per_camera: int = 33554432, max_bytes_total: int = 268435456)
spool.enqueue(camera_id: str, generation: int, template: dict, *, now: float) -> bytes
spool.claim_due(*, now: float) -> dict | None
spool.record_failure(event_id: str, code: str, *, permanent: bool) -> None
spool.acknowledge(ack: dict) -> bool
spool.pending(camera_id: str) -> list[dict]
spool.close() -> None
```

pending returns sequence-sorted `{payload:bytes,attempts:int,next_attempt_at:float,quarantine_code:str|None}`. Fresh enqueue attempts=0, next_attempt_at=now. Unknown failure event raises `ContractError('unknown_event')`. Invalid args raise `ContractError('invalid_argument')`; validate limits positive strict ints, now finite nonnegative real not bool, map/ID/generation shape, template omissions/extras. Module business errors use frozen ContractError with exact code. Constructor mismatch is assignment_mismatch; forbidden camera/producer unauthorized; wrong supplied generation fenced. Allocation at MAX is sequence_exhausted. `close` releases SQLite handles; reopened object must recover all state. No context manager requirement. No DB/network access occurs at import time.

## 8. Contract verification and limitations

From the repository root:

```
python3 -B incident-slice-1/validate_fixtures.py
python3 -B -m unittest discover -s contracts/incident-slice-1 -p 'test_contract.py' -v
sha256sum --check incident-slice-1/SHA256SUMS
```

`scenarios.json` is a normative static behavior oracle with event fixture references and expected state summaries; validating its JSON/references is NOT executing an incident reducer or spool. Invalid collision envelopes are individually schema-valid; their conflicts are contextual and belong in module tests. Fixture validation proves only strict shapes, ACK binding, canonicalization and reference consistency. Module execution, SQLite crash durability, full disk, authenticated real-process handoff, production security and real camera/media proof remain future gates.
