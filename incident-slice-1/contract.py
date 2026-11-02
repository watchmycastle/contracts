"""incident-slice-1-r1: strict synthetic contract validation, NOT a service."""
import datetime as dt
import hashlib
import json
import re
import uuid

REVISION = "incident-slice-1-r1"
MAX = 9007199254740991
BODY_LIMIT = 65536
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?Z\Z", re.ASCII)
EVENT_KEYS = frozenset("schema_version event_id event_type producer_id camera_id assignment_generation sequence source_session_id source_sequence source_event_id occurred_at received_at detector observation".split())
ACK_KEYS = frozenset("schema_version event_id producer_id camera_id assignment_generation payload_sha256 disposition durable accepted_sequence next_expected_sequence".split())


class ContractError(ValueError):
    def __init__(self, code, *, expected_sequence=None):
        self.code = code
        self.expected_sequence = expected_sequence
        super().__init__(code)


def require(condition, code="invalid_schema"):
    if not condition:
        raise ContractError(code)


def exact_keys(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def integer(value, low=1, high=MAX):
    require(type(value) is int and low <= value <= high)


def identifier(value):
    require(type(value) is str and ID.fullmatch(value) is not None)


def uuid_id(value):
    require(type(value) is str)
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise ContractError("invalid_schema") from None
    require(str(parsed) == value and parsed.int != 0)


def timestamp(value):
    require(type(value) is str and TIME.fullmatch(value) is not None)
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError("invalid_schema") from None


def member(value, choices):
    require(type(value) is str and value in choices)


def canonical_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ContractError("invalid_schema") from None


def event_sha256(event):
    return hashlib.sha256(canonical_bytes(event)).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "invalid_json")
        result[key] = value
    return result


def _no_number(value):
    raise ContractError("invalid_json")


def decode_json(payload):
    require(type(payload) is bytes, "invalid_json")
    require(len(payload) <= BODY_LIMIT, "oversized")
    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_float=_no_number, parse_constant=_no_number)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError("invalid_json") from None


def validate_event(event):
    require(type(event) is dict)
    require(type(event.get("schema_version")) is int and event["schema_version"] == 1,
            "unsupported_schema")
    require(event.get("event_type") == "detector.observation", "unsupported_schema")
    exact_keys(event, EVENT_KEYS)
    uuid_id(event["event_id"])
    uuid_id(event["source_session_id"])
    identifier(event["producer_id"])
    identifier(event["camera_id"])
    integer(event["assignment_generation"])
    integer(event["sequence"], high=MAX - 1)
    if event["source_sequence"] is not None:
        integer(event["source_sequence"])
    if event["source_event_id"] is not None:
        identifier(event["source_event_id"])
    if event["occurred_at"] is not None:
        timestamp(event["occurred_at"])
    timestamp(event["received_at"])
    detector = event["detector"]
    exact_keys(detector, {"id", "kind"})
    identifier(detector["id"])
    member(detector["kind"], ("motion", "sound", "person"))  # person: r2, Reolink PeopleDetect
    observation = event["observation"]
    exact_keys(observation, {"state", "semantics", "freshness", "clock_quality"})
    member(observation["state"], ("active", "quiet", "unknown"))
    member(observation["semantics"], ("transition", "initialization", "resync"))
    member(observation["freshness"], ("live", "replay", "uncertain"))
    member(observation["clock_quality"], ("trusted", "skewed", "unknown"))
    require(len(canonical_bytes(event)) <= BODY_LIMIT, "oversized")


def decode_event(payload):
    event = decode_json(payload)
    validate_event(event)
    return event


def validate_ack(ack, event):
    validate_event(event)
    exact_keys(ack, ACK_KEYS)
    require(type(ack["schema_version"]) is int and ack["schema_version"] == 1)
    require(ack["durable"] is True)
    member(ack["disposition"], ("accepted", "duplicate"))
    uuid_id(ack["event_id"])
    identifier(ack["producer_id"])
    identifier(ack["camera_id"])
    integer(ack["assignment_generation"])
    integer(ack["accepted_sequence"], high=MAX - 1)
    integer(ack["next_expected_sequence"], low=2)
    require(type(ack["payload_sha256"]) is str and
            re.fullmatch(r"[0-9a-f]{64}", ack["payload_sha256"]) is not None)
    for key in ("event_id", "producer_id", "camera_id", "assignment_generation"):
        require(ack[key] == event[key], "ack_mismatch")
    require(ack["payload_sha256"] == event_sha256(event), "ack_mismatch")
    require(ack["accepted_sequence"] == event["sequence"], "ack_mismatch")
    require(ack["next_expected_sequence"] == event["sequence"] + 1, "ack_mismatch")
