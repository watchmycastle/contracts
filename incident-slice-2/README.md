# incident-slice-2-r1 — synthetic transport freeze candidate

Parent review is required before implementation. Normative plan: `incident-slice-2/SPEC.md` in this repository. Slice 1 stays frozen; this slice adds no service code.

Files:
- `transport_oracle.py`: pure test-only config/credential/ACK classification oracle; runtime imports prohibited.
- `fixtures.json`: dummy configs/credentials, assignment maps, invalid origins, named later acceptance scenarios. `/absolute/...` values are illustrative and must be replaced by harness-owned temporary paths.
- `synthetic.jsonl`: two enqueue templates (quiet then active), no caller-selected event IDs or sequences. Use sender-only assignments from fixtures.
- `http-cases.json`: static request mutations and expected error/status vectors. These are NOT an executed HTTP test.
- `test_transport_contract.py`: fixture/oracle tests plus read-only AST signature/source-hash checks against actual sibling modules. No listener, child service, Store or Spool execution.
- `SHA256SUMS`: pins this plan and every slice-2 artifact except this manifest and bytecode.

Run from the repository root:

```
python3 -B -m unittest discover -s contracts/incident-slice-2 -p 'test_transport_contract.py' -v
sha256sum --check incident-slice-1/SHA256SUMS
sha256sum --check incident-slice-2/SHA256SUMS
```


No implementation acceptance from these commands: socket parsing, strict deadlines, real authentication before ingest, redirects/proxy suppression, lost-after-commit response and SIGKILL/restart must be independently exercised against real entry points after coding. The planned harness is not present in this revision and must be added in a later parent-reviewed manifest revision; no claimed subprocess result here.

No production token values, camera access, production security, deployment, remote creation or pushes. Fixtures intentionally use restricted `slice2-dummy-*` tokens. Public methods/ACK remain exactly slice 1.
