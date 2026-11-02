"""Pure slice-2 contract oracle. NO service, sockets, persistence or file I/O.

Test-only imports; application runtime must not import this module.
"""
import hmac
import re
from pathlib import PurePosixPath

import contract as frozen

REVISION = "incident-slice-2-r1"
REQUEST_LIMIT = 65536
RESPONSE_LIMIT = 4096
HEADER_LIMIT = 8192
HEADER_COUNT = 32
LINE_LIMIT = 2048
TOKEN = re.compile(r"slice2-dummy-[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
ORIGIN = re.compile(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})\Z", re.ASCII)
ERROR_STATUS = {
    "bad_request": 400, "invalid_json": 400,
    "unauthenticated": 401, "unauthorized": 403, "fenced": 403,
    "not_found": 404, "method_not_allowed": 405, "request_timeout": 408,
    "idempotency_conflict": 409, "sequence_gap": 409, "stale_sequence": 409,
    "detector_kind_conflict": 409, "sequence_exhausted": 409,
    "length_required": 411, "oversized": 413, "unsupported_media_type": 415,
    "unsupported_schema": 422, "invalid_schema": 422, "headers_too_large": 431,
    "storage_unavailable": 503, "internal_error": 500,
}
COMMON = {"schema_version", "synthetic", "db_path", "assignments_path", "fake_credentials_path"}
CONFIG_KEYS = {
    "receiver": COMMON | {"listen_host", "listen_port"},
    "sender": COMMON | {"fixture_path", "origin"},
}


class OracleError(ValueError):
    """Safe fixed code, never include rejected input."""


def need(ok, code="invalid_config"):
    if not ok:
        raise OracleError(code)


def exact(value, keys):
    need(type(value) is dict and set(value) == set(keys))


def strict_json(payload):
    try:
        return frozen.decode_json(payload)
    except frozen.ContractError:
        raise OracleError("invalid_config") from None


def origin_port(value):
    match = ORIGIN.fullmatch(value) if type(value) is str else None
    need(match is not None)
    port = int(match.group(1))
    need(port <= 65535)
    return port


def path_shape(value):
    need(type(value) is str and value.startswith("/") and "\x00" not in value)
    need(not any(0xD800 <= ord(c) <= 0xDFFF for c in value))
    need(str(PurePosixPath(value)) != "/")


def validate_config(role, value):
    need(role in CONFIG_KEYS)
    exact(value, CONFIG_KEYS[role])
    need(type(value["schema_version"]) is int and value["schema_version"] == 1)
    need(value["synthetic"] is True)
    paths = ["db_path", "assignments_path", "fake_credentials_path"]
    if role == "receiver":
        need(value["listen_host"] == "127.0.0.1")
        need(type(value["listen_port"]) is int and 0 <= value["listen_port"] <= 65535)
    else:
        origin_port(value["origin"])
        paths.append("fixture_path")
    for key in paths:
        path_shape(value[key])
    # Lexical aliases only here. Runtime additionally resolves symlinks and checks
    # existence, regular files, parents, and DB collisions before opening a DB.
    db = str(PurePosixPath(value["db_path"]))
    need(all(db != str(PurePosixPath(value[p])) for p in paths if p != "db_path"))
    return value


def validate_assignments(value):
    need(type(value) is dict and bool(value))
    try:
        for camera, assignment in value.items():
            frozen.identifier(camera)
            frozen.exact_keys(assignment, ("producer_id", "assignment_generation"))
            frozen.identifier(assignment["producer_id"])
            frozen.integer(assignment["assignment_generation"])
    except frozen.ContractError:
        raise OracleError("invalid_config") from None
    return value


def validate_credentials(role, value, assignments):
    validate_assignments(assignments)
    need(role in CONFIG_KEYS)
    keys = {"schema_version", "synthetic"}
    exact(value, keys | ({"tokens"} if role == "receiver" else {"token", "producer_id"}))
    need(type(value["schema_version"]) is int and value["schema_version"] == 1)
    need(value["synthetic"] is True)
    if role == "sender":
        token = value["token"]
        need(type(token) is str and TOKEN.fullmatch(token) is not None)
        need(all(a["producer_id"] == value["producer_id"] for a in assignments.values()))
    else:
        tokens = value["tokens"]
        need(type(tokens) is dict and bool(tokens))
        for token, identity in tokens.items():
            need(type(token) is str and TOKEN.fullmatch(token) is not None)
            exact(identity, {"producer_id", "camera_ids"})
            cameras = identity["camera_ids"]
            need(type(cameras) is list and bool(cameras))
            need(all(type(c) is str for c in cameras))
            need(len(set(cameras)) == len(cameras))
            need(all(c in assignments and assignments[c]["producer_id"] == identity["producer_id"]
                     for c in cameras))
    return value


def authenticate(values, credentials):
    """Authorization values after HTTP parser OWS stripping, preserving repeats."""
    if len(values) != 1 or type(values[0]) is not str:
        raise OracleError("unauthenticated")
    value = values[0]
    if not value.startswith("Bearer ") or TOKEN.fullmatch(value[7:]) is None:
        raise OracleError("unauthenticated")
    result = None
    for token, identity in credentials["tokens"].items():
        if hmac.compare_digest(value[7:], token):
            result = identity
    if result is None:
        raise OracleError("unauthenticated")
    return result


def authorize(identity, event):
    need(event["camera_id"] in identity["camera_ids"] and
         event["producer_id"] == identity["producer_id"], "unauthorized")
    return identity["producer_id"]  # Store still verifies assignment/generation


def fixture_record(value, assignments):
    try:
        exact(value, {"synthetic", "camera_id", "assignment_generation", "template"})
        need(value["synthetic"] is True)
        camera, generation = value["camera_id"], value["assignment_generation"]
        need(type(camera) is str and camera in assignments)
        need(type(generation) is int and generation == assignments[camera]["assignment_generation"])
        template = value["template"]
        omitted = {"event_id", "producer_id", "camera_id", "assignment_generation", "sequence"}
        exact(template, frozen.EVENT_KEYS - omitted)
        event = dict(template, camera_id=camera, assignment_generation=generation,
                     producer_id=assignments[camera]["producer_id"], sequence=1,
                     event_id="00000000-0000-4000-8000-000000000001")
        frozen.validate_event(event)
    except (OracleError, frozen.ContractError):
        raise OracleError("invalid_fixture") from None
    return value


def error_body(code, expected_sequence=None):
    need(code in ERROR_STATUS, "invalid_error")
    error = {"code": code}
    if code == "sequence_gap":
        try:
            frozen.integer(expected_sequence)
        except frozen.ContractError:
            raise OracleError("invalid_error") from None
        error["expected_sequence"] = expected_sequence
    else:
        need(expected_sequence is None, "invalid_error")
    return {"schema_version": 1, "error": error}


def known_error(status, payload):
    try:
        value = frozen.decode_json(payload)
        frozen.exact_keys(value, {"schema_version", "error"})
        need(type(value["schema_version"]) is int and value["schema_version"] == 1)
        err = value["error"]
        need(type(err) is dict and type(err.get("code")) is str)
        code = err["code"]
        need(ERROR_STATUS.get(code) == status)
        need(value == error_body(code, err.get("expected_sequence")))
        # Equality alone accepts True as 1 in the nested expected sequence;
        # error_body enforces its exact integer type first.
        return code
    except (OracleError, frozen.ContractError):
        return None


def classify_response(status, payload, event, *, framing_ok=True):
    """Returns (action, safe_code); 'ack' still requires Spool.acknowledge True.

    Caller establishes bounded headers, idle/absolute deadlines, exact length,
    media type, no TE/encoding before framing_ok. No network proof here.
    """
    if not framing_ok or type(payload) is not bytes or not 0 < len(payload) <= RESPONSE_LIMIT:
        return "retry", "invalid_response"
    if status == 200:
        try:
            ack = frozen.decode_json(payload)
            frozen.validate_ack(ack, event)
        except frozen.ContractError:
            return "retry", "invalid_ack"
        return "ack", None
    code = known_error(status, payload)
    if status in (408, 429) or 500 <= status <= 599:
        return "retry", code or "http_transient"
    if 300 <= status <= 399:
        return "quarantine", "redirect_refused"
    if 100 <= status <= 199:
        return "retry", "invalid_response"
    return "quarantine", code or "http_rejected"


def validate_ready(role, value):
    exact(value, {"event", "role", "synthetic"} | ({"host", "port"} if role == "receiver" else set()))
    need(role in CONFIG_KEYS and value["role"] == role and value["event"] == "ready")
    need(value["synthetic"] is True)
    if role == "receiver":
        need(value["host"] == "127.0.0.1")
        need(type(value["port"]) is int and 1 <= value["port"] <= 65535)
    need(len(frozen.canonical_bytes(value)) + 1 <= 1024)
    return value
