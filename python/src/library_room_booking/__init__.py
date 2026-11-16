"""Provider-neutral contracts. Optional adapters live in separate modules; callers own authority."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Mapping, Protocol
from zoneinfo import ZoneInfo


class Outcome(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    MANUAL_ONLY = "manual_only"
    AUTHENTICATION_REQUIRED = "authentication_required"
    DEFERRED = "deferred"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED_BEFORE_SUBMIT = "failed_before_submit"
    UNKNOWN_AFTER_SUBMIT = "unknown_after_submit"


OPERATIONS = ("discovery", "availability", "booking", "confirmation", "modification", "cancellation")
SUPPORT = ("supported", "unsupported", "manual_only", "authentication_required")


def _text(value):
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError("Expected nonempty exact identity.")
    return value


def instant(value: str, zone: str) -> datetime:
    """Require an explicit offset valid in the named zone; reject DST gaps."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != parsed.astimezone(ZoneInfo(zone)).utcoffset():
        raise ValueError("Offset does not match timezone.")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class Location:
    provider: str
    location_id: str
    timezone: str

    def __post_init__(self):
        _text(self.provider)
        _text(self.location_id)
        ZoneInfo(self.timezone)


@dataclass(frozen=True)
class Room:
    location: Location
    room_id: str

    def __post_init__(self):
        if type(self.location) is not Location:
            raise ValueError("Expected location.")
        _text(self.room_id)


@dataclass(frozen=True)
class Interval:
    start: str
    end: str
    timezone: str

    def __post_init__(self):
        if instant(self.start, self.timezone) >= instant(self.end, self.timezone):
            raise ValueError("Expected positive interval.")

    def bounds(self):
        return instant(self.start, self.timezone), instant(self.end, self.timezone)


def buffered_interval(interval: Interval, setup_minutes: int, cleanup_minutes: int):
    """Elapsed UTC bounds; no hidden local-time arithmetic or application policy."""
    if any(type(x) is not int or x < 0 for x in (setup_minutes, cleanup_minutes)):
        raise ValueError("Expected nonnegative whole minutes.")
    start, end = interval.bounds()
    return start - timedelta(minutes=setup_minutes), end + timedelta(minutes=cleanup_minutes)


def within_window(interval: Interval, window: Interval, *, setup_minutes=0, cleanup_minutes=0):
    start, end = buffered_interval(interval, setup_minutes, cleanup_minutes)
    opens, closes = window.bounds()
    return opens <= start and end <= closes


@dataclass(frozen=True)
class AvailabilityRequest:
    room: Room
    interval: Interval

    def __post_init__(self):
        if type(self.room) is not Room or type(self.interval) is not Interval:
            raise ValueError("Expected room and interval.")
        if self.room.location.timezone != self.interval.timezone:
            raise ValueError("Use location timezone.")


@dataclass(frozen=True)
class BookingRequest(AvailabilityRequest):
    attempt_id: str

    def __post_init__(self):
        super().__post_init__()
        _text(self.attempt_id)


@dataclass(frozen=True)
class ConfirmationEvidence:
    request: BookingRequest
    booking_id: str
    origin: str
    reference: str
    verified: bool

    def __post_init__(self):
        if type(self.request) is not BookingRequest or type(self.verified) is not bool:
            raise ValueError("Expected booking request and verification flag.")
        for value in (self.booking_id, self.origin, self.reference):
            _text(value)


def evidence_matches(evidence, request, booking_id, expected_origin):
    """Exact binding only; caller verifies origin authenticity and retains proof."""
    return (type(evidence) is ConfirmationEvidence and evidence.verified
            and evidence.request == request and evidence.booking_id == booking_id
            and evidence.origin == expected_origin)


@dataclass(frozen=True)
class OperationResult:
    outcome: Outcome
    request: AvailabilityRequest
    slots: tuple[Interval, ...] = ()
    booking_id: str | None = None
    evidence: ConfirmationEvidence | None = None
    expected_origin: str | None = None

    def __post_init__(self):
        if type(self.outcome) is not Outcome or not isinstance(self.request, AvailabilityRequest):
            raise ValueError("Expected explicit outcome and request.")
        if type(self.slots) is not tuple or any(type(x) is not Interval for x in self.slots):
            raise ValueError("Expected immutable intervals.")
        for slot in self.slots:
            if slot.timezone != self.request.interval.timezone or not within_window(slot, self.request.interval):
                raise ValueError("Slot outside requested window.")
        if self.slots and self.outcome is not Outcome.AVAILABLE:
            raise ValueError("Slots require available outcome.")
        if self.outcome is Outcome.CONFIRMED and (
            type(self.request) is not BookingRequest or not self.expected_origin
            or not evidence_matches(self.evidence, self.request, self.booking_id, self.expected_origin)
        ):
            raise ValueError("Confirmation requires exact verified evidence.")


def capabilities(**operations) -> Mapping[str, str]:
    """Omitted operations fail closed; manual support is per operation."""
    from types import MappingProxyType
    if set(operations) - set(OPERATIONS) or any(x not in SUPPORT for x in operations.values()):
        raise ValueError("Invalid operation capability.")
    return MappingProxyType({name: operations.get(name, "unsupported") for name in OPERATIONS})


@dataclass(frozen=True)
class Dependencies:
    transport: Callable = field(repr=False)
    credentials: Callable = field(repr=False)
    clock: Callable[[], datetime] = field(repr=False)
    contact: Mapping = field(repr=False)
    configuration: Mapping = field(repr=False)
    evidence: tuple[ConfirmationEvidence, ...] = field(default=(), repr=False)


class Provider(Protocol):
    """No registry, default client, retries or durable state implied."""
    capabilities: Mapping[str, str]

    def availability(self, request: AvailabilityRequest, dependencies: Dependencies) -> OperationResult: ...
    def book(self, request: BookingRequest, dependencies: Dependencies) -> OperationResult: ...
