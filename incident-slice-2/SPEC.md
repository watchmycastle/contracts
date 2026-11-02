# Incident slice 2 transport implementation plan

**Goal:** Connect the approved Store and Spool through two explicit synthetic, authenticated, IPv4-loopback-only Python processes without changing slice 1.
**Architecture:** The receiver derives trusted identity from a dummy credential file and calls Store; the sender delivers persisted canonical Spool bytes and removes a head only after a matching durable ACK. Independent SQLite files and independent entry points; no camera, browser, deployment or production authentication.
**Tech Stack:** Python standard library, HTTP/1.1 with connection close, existing SQLite modules, frozen slice-1 `contract` on PYTHONPATH.

## 0. Freeze gate, authority and boundaries

Proposed freeze ID **incident-slice-2-r1**, pending parent review before any coding. `incident-slice-2/SHA256SUMS` pins this document and every slice-2 artifact except itself/bytecode. Parent acceptance makes these exact bytes the lane contract; any subsequent change requires reviewed revision and regenerated manifest. Slice-1 manifest remains authoritative and untouched. `baseline.json` records read-only source hashes, not a replacement slice-1 freeze.

Read actual `incident-slice-1/SPEC.md`, `incident-platform-implementation.md`, sibling `incident_service/store.py`, and sibling `camera_agent/spool.py`. Both currently use `check_same_thread=False` plus RLock, but this transport deliberately uses one main-thread DB owner and serial requests/sends; no reliance on that implementation detail. `Store.apply_event(payload, *, trusted_producer)` authenticates assignments itself and returns only after commit. `Spool.claim_due(*, now)` persists attempts/deadlines before returning; `acknowledge` validates binding. Neither module performs HTTP or authenticates a peer.

This revision narrows candidate Phase 1 transport only. It does NOT modify reducers, ACKs, assignment persistence, migration checks, initial-active policy, quarantine/backoff, or add production security. No GET snapshot/outbox, health route, control endpoint, debug HTTP route, TLS selection, web login, proxy discovery, ONVIF, media, notification or LAN binding. IPv6 deferred. Dummy bearer authentication proves a synthetic request-identity boundary, not server cryptographic identity or protection from hostile local users. Loopback is not mutual authentication. Local test files and the configured origin must be harness-controlled; production use remains prohibited.

## 1. Exact CLI, configuration and file formats

Commands from the respective repository, with slice-1 directory on PYTHONPATH:

```
python3 -B -m incident_service --synthetic --config /absolute/receiver.json
python3 -B -m camera_agent --synthetic --config /absolute/sender.json seed
python3 -B -m camera_agent --synthetic --config /absolute/sender.json run
```

`--synthetic` and config `synthetic:true` are BOTH mandatory. Only these options/subcommands and `--help` exist; no host/URL/token overrides, environment fallback, reset, production mode or fault-injection options. Config paths are absolute. Unknown arguments fail before DB/listener creation. `seed` is an offline finite preparation command, not a third service; `run` never seeds/reseeds and never reads the fixture. Run can restart against an existing spool even when the fixture is absent. The receiver is started before writing the sender's fixed origin from readiness; runtime never follows a readiness file or changes origin.

All config/credential/assignment JSON: strict UTF-8 JSON objects, no BOM, duplicate keys, nonfinite or floating numbers; exact keys and strict types (bool is not int), at most 65536 bytes/file. All path values are absolute nonempty filesystem paths, no NUL, no `:memory:` or SQLite URI; parent directory must already exist. Resolve paths before comparing aliases; DB must not resolve to any input file. No path/exception text printed on failure. Input files are regular local files, not URLs. Harness writes private temporary config/credentials mode 0600 under TMPDIR. This is fixture hygiene, not a credential-management design.

Receiver config exact keys:

```json
{"schema_version":1,"synthetic":true,"db_path":"/absolute/incident.sqlite","assignments_path":"/absolute/assignments.json","fake_credentials_path":"/absolute/receiver-credentials.json","listen_host":"127.0.0.1","listen_port":0}
```

Sender config exact keys:

```json
{"schema_version":1,"synthetic":true,"db_path":"/absolute/spool.sqlite","assignments_path":"/absolute/assignments.json","fake_credentials_path":"/absolute/sender-credential.json","fixture_path":"/absolute/synthetic.jsonl","origin":"http://127.0.0.1:12345"}
```

`listen_host` must equal literal `127.0.0.1`; port strict int 0..65535 (0 requests ephemeral). Sender origin must match exactly `http://127.0.0.1:<decimal-port>` with port 1..65535, no leading zeros, slash, userinfo, query, fragment, escape, alternate IP form, hostname, TLS scheme or whitespace. No DNS resolution of user-supplied hosts. Fixed path is `/v1/observations`. Do not use `urllib` default proxy/redirect handlers: use `http.client.HTTPConnection('127.0.0.1', parsed_port, timeout=2)` directly. `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, lowercase equivalents and `NO_PROXY` have no effect. No request-target, Host, Location or fixture data can override destination.

Assignment file is exactly the slice-1 nonempty camera map, e.g. `{"camera-a":{"producer_id":"producer-a","assignment_generation":1},"camera-b":{"producer_id":"producer-b","assignment_generation":1}}`. Receiver loads complete map; a sender loads only assignments for its one producer. Store/Spool receive those exact maps and must reject persisted mismatch; never silently reset/change generation. Harness uses separate producer spool DBs for multi-producer negative cases, or one producer with multiple cameras for fairness.

Receiver dummy credential file exact shape:

```json
{"schema_version":1,"synthetic":true,"tokens":{"slice2-dummy-a-not-secret":{"producer_id":"producer-a","camera_ids":["camera-a"]},"slice2-dummy-b-not-secret":{"producer_id":"producer-b","camera_ids":["camera-b"]}}}
```

Sender dummy credential file exact shape:

```json
{"schema_version":1,"synthetic":true,"token":"slice2-dummy-a-not-secret","producer_id":"producer-a"}
```

Token grammar for this profile ONLY: `slice2-dummy-[A-Za-z0-9_-]{1,64}`. This intentionally refuses real credentials and proves nothing about production token strength. Tokens map to one trusted producer plus nonempty, unique camera list. Every listed camera must exist in receiver assignments and have that producer; invalid mapping fails startup. Multiple dummy tokens may map to the same assignment; no automatic rotation. Sender's producer must match every sender assignment. Token appears only in file and Authorization header, never command line, environment, stdout/stderr, exception, request logging, readiness or error response. Do not load actual service credentials.

Fixture format: UTF-8 JSONL, 1..1000 nonblank lines, file <=1048576 bytes, each line <=65536 bytes including newline. Each line exactly `{synthetic:true,camera_id,assignment_generation,template}`; `template` is slice-1 enqueue template with the five assigned/allocated fields omitted. It contains source_session_id/timestamps; never regenerate those on retry. No URL or credential fields. Validate the entire fixture and assignments before creating a spool. `seed` requires db_path not to exist, reserves it with exclusive creation, then uses public Spool.enqueue in line order at time.time(). No idempotent reseed promise: partial seed failure retains the DB and exits nonzero; do not delete/recreate it. Parent investigates a partial seed rather than retrying seed blindly. Seed count successful output exactly `{"event":"seeded","synthetic":true,"count":N}`. Run requires an existing DB; Store receiver may initialize a new DB. Existing empty/incompatible spool is rejected by its module or run checks, not treated as permission to reseed. Default slice-1 capacity limits stay unchanged.

## 2. Readiness, lifecycle and narrow Python interfaces

New module exports (public for lane tests only; not a shared application framework): each adapter also defines `TransportError(code: str)` with `.code`, whose str() is only that allowlisted CLI fatal code. Config/credential/assignment file read/shape/alias failures -> invalid_config; fixture read/shape failures -> invalid_fixture; exclusive-create collision -> seed_exists. Normalize startup Store/Spool assignment/schema/storage exceptions to the CLI codes below; unknown errors -> internal_error. Entry points catch these safe adapter errors and never stringify arbitrary exceptions. `load_config` validates the config JSON/shape and lexical paths; `run`/`seed` validate filesystem prerequisites and referenced inputs before their side effects. No error class is shared across application repositories.

New module exports:

```
# incident_service/http_api.py
load_config(path: str) -> dict  # validated config; load files separately inside run
run(config: dict, *, ready: Callable[[dict], None], stop: Callable[[], bool]) -> None
# camera_agent/sender.py
load_config(path: str) -> dict
seed(config: dict) -> int  # number committed, only new DB
run(config: dict, *, ready: Callable[[dict], None], stop: Callable[[], bool]) -> None
```

`run` validates referenced runtime files before DB mutation/listening (sender run explicitly excludes fixture_path), owns and closes its Store/Spool; callers provide validated configs. Sender run checks via a separate short-lived read-only SQLite connection that the preexisting file has a schema_migrations table before constructing Spool; otherwise CLI schema_incompatible. Close that inspection connection first, then let Spool perform all authoritative schema/assignment checks. This prevents its constructor from silently initializing an unseeded empty file; never duplicate or bypass its full verifier. Ready called once after DB/schema/assignment checks and (receiver) successful bind. No import-time I/O, signal handlers or listeners. `__main__.py` defines `main(argv=None)->int` and installs SIGTERM/SIGINT handlers that only set a stop flag; it serializes callback values as one flushed compact JSON stdout line. On sender no connection is required for ready: it means initialized sender, NOT connected/ACKed. Normal run stdout contains only readiness; no event bodies, tokens or per-attempt logs.

Receiver readiness exactly `{"event":"ready","role":"receiver","synthetic":true,"host":"127.0.0.1","port":<actual 1..65535>}`. Sender readiness exactly `{"event":"ready","role":"sender","synthetic":true}`. Neither includes DB paths, assignments, identity, tokens or URLs. Harness drains both pipes concurrently, requires a line <=1024 bytes within 10 monotonic seconds, verifies shape/port and child liveness, and fails early if child exits. No sleep-only readiness. Capture only sanitized bounded output (<=64 KiB/child) and scan it for fixture tokens and malicious marker strings.

Use serial `HTTPServer`, NOT `ThreadingHTTPServer`; create/use/close Store on main thread. Set server accept poll timeout <=0.2s, loop `handle_request()` while not stopped. Sender uses one main thread for Spool and synchronous HTTP, polling stop <=0.2s between attempts. DB transactions never span a network operation. A per-connection watchdog may close/shutdown ONLY its socket, never access SQLite, and is cancelled/joined at end of request. Do not call `HTTPServer.shutdown()` from its serving thread (deadlock); close listener in finally. Any test that uses a server thread creates/uses/closes its Store within that same thread.

SIGINT/SIGTERM: stop accepting/claiming new work; finish or time out current work; close client sockets/listener then DB in finally; exit 0. No dequeue on interrupted/unknown response. Harness allows 15 seconds then kills/reaps as cleanup failure. SIGKILL recovery is tested separately: same DB, no repair/delete, WAL handled by existing modules. There is one live owner per DB; do not open a second Store/Spool for inspection until child is stopped/reaped. Read-only SQLite observations by acceptance harness may use independent read connections during execution; never use internal application connection attributes or modify live state.

CLI fatal stderr exactly one JSON line `{"event":"fatal","code":CODE}`, no traceback or source text. Exit 2 for `invalid_config`, `invalid_fixture`, `seed_exists`; exit 1 for `storage_unavailable`, `assignment_mismatch`, `schema_incompatible`, `bind_failed`, `internal_error`; normal seed/run or graceful stop exit 0. Store `schema_mismatch` and Spool `schema_incompatible` normalize to CLI `schema_incompatible`. Runtime SQLite failure in sender is fatal, preserving pending rows; don't catch and continue as apparent success. Receiver request storage failures have HTTP mapping below; startup failures never emit readiness. Argparse usage/help must not echo argument values (especially an accidentally provided token); unknown arguments produce only invalid_config.

## 3. Frozen HTTP ingress and error precedence

HTTP/1.1 origin-form only, one request per TCP connection, `Connection: close` on every response; no keepalive/pipelining, chunked transfer, content compression, Expect/100, websocket, CONNECT tunnel or redirects. Request line <=2048 bytes including CRLF; total header section <=8192 bytes including CRLF, <=32 fields, each line <=2048 bytes. Reject folded headers. Implement explicit aggregate bounds (stdlib defaults alone do not meet these values). Socket idle timeout 2 seconds and absolute accepted-connection I/O deadline 10 monotonic seconds, including header/body/write; watchdog closes socket at deadline. Partial EOF/framing failure must never call Store. A deadline may drop an already-committed ACK; retry remains safe. Do not promise cancellation/rollback of an already-running commit.

Validation precedence below is normative when enough bytes are available; parser/deadline failures can precede higher-level checks. On unavailable/closed socket, silent close rather than a response is allowed; never falsely ACK. No HTML/default server banners, Python versions, paths, traceback or echoed client input; override stdlib error and logging defaults, including parse failures and unsupported methods. HEAD sends no body but error headers/Content-Length represent the error JSON. All other error bodies are compact JSON as below. No health exception.

1. Safely parse bounded request line/headers: malformed request/version, folded header -> 400 `bad_request`; request-line/header limit -> 431 `headers_too_large`; timeout -> 408 `request_timeout` if writable, otherwise close. Accept only HTTP/1.1.
2. Target must equal `/v1/observations` byte-for-byte (no query, trailing slash, absolute-form, encoded alternatives): otherwise 404 `not_found`. At this exact path method must be POST: otherwise 405 `method_not_allowed`, `Allow: POST`. This includes GET/HEAD/OPTIONS/PUT/DELETE/TRACE/CONNECT/unknown verbs; never serve snapshots/control.
3. Exactly one Host header must equal `127.0.0.1:<actual listener port>`; otherwise 400 `bad_request`. No forwarded-header trust. Presence of Transfer-Encoding, Content-Encoding, Expect, duplicated Host/Content-Type, or malformed framing -> 400 `bad_request`. Exactly one Content-Length required: absent -> 411 `length_required`; duplicate/comma/sign/whitespace-in-value/nondecimal or zero -> 400 `bad_request`. Header surrounding OWS is stripped by parsing; numeric grammar `[0-9]+`; >65536 -> 413 `oversized`. Leading zeros are accepted for Content-Length, unlike origin port. Do not read past declared length; close after response, never parse surplus bytes as another request.
4. Content-Type must be exactly `application/json` (after header OWS stripping); absent/parameterized/case-changed/other -> 415 `unsupported_media_type`.
5. Exactly one Authorization header, exact `Bearer <token>` syntax and known dummy token, checked against file-loaded map using constant-time comparison -> otherwise 401 `unauthenticated`; include `WWW-Authenticate: Bearer`. No body decode/Store call before successful auth. Identity headers (`X-Producer-ID`, `X-Camera-ID`, etc.) are ignored, never trusted. Unknown headers cannot alter routing/identity. Missing key with valid headers and malformed body yields 401.
6. Read exactly declared bytes within deadlines; short EOF -> 400 `bad_request` if writable; idle/absolute timeout as above. Decode via frozen.decode_event: invalid JSON ->400 `invalid_json`; unsupported version/type ->422 `unsupported_schema`; invalid envelope ->422 `invalid_schema`; oversized ->413 `oversized`.
7. Authorize token's camera allowlist and require event.producer_id == token's trusted producer, otherwise 403 `unauthorized`; do not infer identity from body/header. Call `store.apply_event(raw_body, trusted_producer=token_producer)`; Store repeats assignment/generation checks, including duplicate retries. Credential file is read once, not reloaded while serving.
8. Return 200 with Store ACK unchanged, only after successful return. Store business mappings below; do not catch unknown exceptions as success. Broken-pipe after commit is not rollback or fatal server error.

All responses: `Content-Type: application/json`, exact Content-Length, `Connection: close`; optional Date permitted, no Server banner. Success object has exactly slice-1 ACK fields, no transport wrapper. Response body <=4096 bytes. Errors exactly `{"schema_version":1,"error":{"code":CODE}}`; only `sequence_gap` adds `expected_sequence` inside `error`, from validated Store ContractError. No identity, event IDs, request bytes, token, path, exception message or arbitrary detail. Successful ACK intentionally contains slice-1 identity binding; do not log it.

| HTTP | Frozen code(s) | Sender decision |
|---|---|---|
| 400 | bad_request, invalid_json | quarantine |
| 401 | unauthenticated | quarantine |
| 403 | unauthorized, fenced | quarantine |
| 404 | not_found | quarantine |
| 405 | method_not_allowed | quarantine |
| 408 | request_timeout | retry |
| 409 | idempotency_conflict, sequence_gap, stale_sequence, detector_kind_conflict, sequence_exhausted | quarantine |
| 411 | length_required | quarantine |
| 413 | oversized | quarantine |
| 415 | unsupported_media_type | quarantine |
| 422 | unsupported_schema, invalid_schema | quarantine |
| 431 | headers_too_large | quarantine |
| 503 | storage_unavailable | retry |
| 500 | internal_error | retry |

`sqlite3.Error` ->503 storage_unavailable; Store assignment_mismatch/schema_mismatch or unexpected ContractError/exception at request time ->500 internal_error (no repr/str). `unauthorized`/`fenced` preserve codes. `429` and any other 5xx are sender transient even though receiver does not currently generate them. Errorcode/status map is duplicated as normative machine-readable fixture; tests check consistency. Errors never contain durable/ACK fields.

## 4. Sender behavior and response guard

For each due head, send returned `payload` bytes EXACTLY, without JSON reserialization, ID regeneration or template reread. Construct fixed POST, Host, Authorization, application/json, exact Content-Length and close. Use one fresh direct HTTPConnection per attempt; close in finally. `time.time()` supplies Spool timing, random.uniform jitter constructor; IDs str(uuid.uuid4()), receiver clock valid UTC Z. No monkeypatch/backoff override CLI. Poll claim_due at <=0.2s; the Spool is the sole retry deadline authority, no immediate retry loop. A quarantined head blocks only its camera.

Per-socket idle timeout 2s; absolute attempt deadline 10s including connect, response headers/body (watchdog may close socket, never touch Spool). Response status line <=2048 bytes; headers same 8192/32/2048 limits as requests, folded/duplicated framing rejected. Bounded header parser or explicit parser override required; defaults do not establish the aggregate guard. Require exactly one positive decimal Content-Length <=4096, one exact application/json Content-Type, no Transfer-Encoding or Content-Encoding. Read exactly that body, no unbounded read(); EOF/timeout before declared body is ambiguous failure. Do not accept 1xx/interim responses as ACK, and do not wait unboundedly for more responses. No redirects of any kind, even to another loopback port; don't transmit token to Location.

Outcome precedence: network/timeout/EOF/header/framing/body-limit failure first -> transient local code `transport_error`, `request_timeout` or `invalid_response` respectively. For a fully framed response, 408/429/5xx -> transient `http_transient` regardless of body; 3xx -> permanent `redirect_refused` (no follow); other non-200 -> permanent `http_rejected`. If a non-200 body is a valid exact frozen error for its status, use its frozen code instead of generic code; never persist remote free text as failure code. Only HTTP 200 may be an ACK. Strict decode via frozen.decode_json then frozen.validate_ack(ack,event) (duplicate JSON keys, oversized/wrong fields rejected), then `spool.acknowledge(ack)`. Invalid/mismatching 200 ACK or acknowledge false -> transient `invalid_ack`, preserve row/deadline. A valid ACK is the only deletion permission; a matching ACK in 201/204/400/500 must NOT dequeue. On accepted or duplicate ACK true, continue fair claiming. For all other outcomes call record_failure(event_id, safe_code, permanent=decision), using event_id from decoded persisted payload. Spool exceptions propagate to CLI fatal, not fake transport success.

## 5. Read-only contract artifacts and verification limits

`transport_oracle.py` is a pure test oracle: config shape, token-map shape, origin restriction, frozen error/status and response classification. It is NOT an HTTP listener/client, config file loader or substitute service implementation. Lanes may import it in tests via explicit slice-2 PYTHONPATH; runtime modules must not import it. Runtime uses only frozen slice-1 `contract`; no cross-lane imports. `fixtures.json` and `synthetic.jsonl` contain dummy examples, negative vectors and scenario names. `test_transport_contract.py` exercises oracle and checks actual public method signatures with AST, not app execution. A green result proves contract consistency only, NOT real HTTP/auth/timeouts/SQLite process recovery. Parent's real-process tests are a separate gate.

From the repository root:

```
python3 -B -m unittest discover -s contracts/incident-slice-2 -p 'test_transport_contract.py' -v
sha256sum --check incident-slice-1/SHA256SUMS
sha256sum --check incident-slice-2/SHA256SUMS
```

## 7. Independent real-process acceptance design (NOT executed by fixture tests)

Later command, only once files implemented and parent re-pins manifest:

```
python3 -B incident-slice-2/acceptance_processes.py --receiver-repo /absolute/approved/incident-worktree --sender-repo /absolute/approved/agent-worktree
```

Harness uses sys.executable -B -m entry points, explicit cwd/PYTHONPATH, isolated TMPDIR temporary directories and separate incident/spool DBs, writes only dummy tokens and fixtures, starts processes with no shell, bounds readiness 10s/scenarios 30s (except retry backoff scenario 75s), checks return codes and reaps all children. Never touches live camera/network/LAN or real credentials. Inspect schema/source baseline and slice-1/slice-2 hashes before run. Save sanitized evidence outside frozen artifacts; preserve previous evidence rather than overwrite.

Required scenarios, independently named in fixtures:

1. `happy_restart`: seed quiet then activation; run real sender/receiver; wait bounded read-only SQLite observation for expected commit and spool deletion, stop/reap both, reopen via public APIs. Assert inbox=2, next=3, one open incident/version/count=1, desired true/version=1 and one opened outbox row. Restart both on SAME DB/config; no reseed; state/IDs/outbox unchanged.
2. `lost_ack_after_commit`: harness-owned one-shot TCP/HTTP relay bound literal127.0.0.1:0, configured upstream receiver literal address. Sender's fixed origin is relay for entire run/restart. Relay forwards exact body/Authorization, rewrites Host to upstream actual port, reads a FULL valid 200 ACK upstream and validates its hash/event identity, records a synchronization marker to harness memory, then drops downstream socket WITHOUT forwarding any ACK bytes. This proves Store returned after commit before loss. No debug endpoint, query/header flag, app hook, monkeypatch or external fault toggle. Relay behavior fixed at construction in harness only. Stop/kill sender immediately after marker and BEFORE scheduled retry; verify pending same canonical bytes with attempts/deadline via read-only DB. If retry races, fail/retry whole isolated scenario, never count a weaker run as pass. SIGKILL receiver and sender, reap both; reopen Store offline to confirm commit/outbox; close handles; restart both on same DB and receiver same explicitly selected old port (or stable relay upstream updated by harness before sender restart; sender origin unchanged). Relay now passes ACKs; duplicate response identical receipt except disposition; queue deletes only after matching ACK, incident/outbox unchanged. Use active event after already-ACKed quiet so loss would otherwise double-activate. Record before/after payload hash, receipt and row counts without token.
3. `auth_and_assignment`: raw socket valid framing missing/wrong/duplicate key ->401; valid key A with camera B ->403; forged body producer and X-Producer-ID cannot gain trust; correct camera but wrong generation ->403 fenced, including retries. Invalid credential map fails before readiness/DB mutation. Compare all authority rows before/after rejected requests (no sequence consume).
4. `conflict_order`: after one commit send changed canonical body same event_id ->409 idempotency_conflict; new ID same sequence ->same; future sequence ->409 sequence_gap with expected; exact old retry after newer commit ->duplicate original receipt. Because slice 1 retains every contiguous prior sequence, an unknown stale tuple cannot arise through ordinary valid ingestion: an occupied old tuple conflicts first. Assert that precedence in real HTTP; test stale_sequence mapping with a test-only fake Store in receiver unit tests, not by deleting production inbox rows or pretending an unreachable request is a subprocess case. Unchanged state on rejects; detector kind conflict ->409. Fixture construction uses slice-1 events and real allocation, never handwaves a schema-invalid collision.
5. `request_boundaries`: valid auth + invalid JSON/duplicate keys/unsupported schema; absent/duplicate/negative/zero/oversized Content-Length, chunked, compressed, Expect, parameterized type, invalid Host, absolute target/query/wrong method; header aggregate/line/count limits; incomplete body idle timeout and trickled headers absolute timeout. Verify no Store mutation and no HTML/banner/secret/marker leaks. GET snapshots/control never work; no unauth health data. Close may replace a response only for malformed/closed/timed-out sockets as specified.
6. `ack_and_egress`: harness fake peer returns wrong ID/camera/generation/hash/sequence/next/durable, duplicate JSON keys, truncated/oversized/slow responses, valid ACK in 201/500, 302 Location to second listener. Persisted row remains, due-time not bypassed; redirect quarantines; second listener gets zero requests/tokens. Set proxy env to trap listener for subprocess and prove zero connections. Origin rejects localhost, LAN, 127.1, integer IP, userinfo, slash/query and non-http before connection. HTTP 200 matching accepted and duplicate each remove exactly one head.
7. `quarantine_fairness`: one producer/two cameras, deterministic bad response A quarantines head while B delivers; attempts/deadlines/quarantine survive SIGKILL/restart without altered payload. Transient 408/429/503 doesn't quarantine. Use bounded assertions from observed persisted deadline; no monkeypatch production timing.
8. `startup_shutdown_storage`: mismatched persisted assignments/schema fail readiness without repair; missing synthetic flag, malformed config/path collisions, bind error emit only safe fatal line; SIGTERM with idle and slow client completes within15s and releases port/handles. Real read-lock/write contention on disposable DB yields503 without false ACK (release lock afterwards). Unit before_commit exception is rollback evidence only, not disk-full or power-loss evidence.

Parent acceptance gate: all named scenarios execute against both unmodified real modules/entry points and pass with source hashes/actual commands/results and cleanup. Fixture/oracle tests alone never satisfy this. No claim of real camera events, media publication, HA/power-loss/disk-full durability, production credential/TLS security, web identity or a deployed service. Parent reviews this freeze before coding begins.
