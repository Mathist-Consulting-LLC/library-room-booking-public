"""Injected LibCal mechanics extracted from calendar f789ee72c255679fa4420122fc2c519c0010f93d.

No network client, credentials store, application policy or durable claims.
See docs/libcal.md for transport and caller authority contracts.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import html as html_lib
import json
import re
from threading import Lock
from typing import Callable
from types import MappingProxyType
from urllib.parse import urljoin, urlsplit, urlencode, parse_qs
from zoneinfo import ZoneInfo

from . import (AvailabilityRequest, BookingRequest, Dependencies, Interval, Location,
               Room, OperationResult, Outcome, capabilities, evidence_matches)


@dataclass(frozen=True)
class Response:
    status: int
    url: str
    body: str = field(repr=False)
    reference: str = "transport-response"
    headers: object = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class LibCalResult(OperationResult):
    detail: str = ""
    reference: str | None = None
    preparation_attempted: bool = False
    submission_attempted: bool = False


@dataclass(frozen=True)
class Resource:
    room: Room
    name: str
    capacity: int
    group_id: str


@dataclass(frozen=True)
class DiscoveryResult:
    outcome: Outcome
    location: Location
    resources: tuple[Resource, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class PreparedBooking:
    request: BookingRequest
    _dependencies: Dependencies = field(repr=False)
    _payload: tuple[tuple[str, str], ...] = field(repr=False)
    _owner: object = field(repr=False)
    _lock: object = field(default_factory=Lock, repr=False, compare=False)
    _used: list = field(default_factory=list, repr=False, compare=False)


class _Failure(Exception):
    def __init__(self, detail, outcome=Outcome.FAILED_BEFORE_SUBMIT):
        self.detail, self.outcome = detail, outcome


def _origin(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password or parts.fragment:
        raise ValueError("Expected HTTPS URL without credentials or fragment")
    return f"https://{parts.netloc}"


def _config(deps):
    config = deps.configuration
    base = config["base_url"]
    if base.rstrip("/") != _origin(base):
        raise ValueError("base_url must be an origin")
    page = urljoin(base, config["availability_path"])
    if _origin(page) != _origin(base):
        raise ValueError("Availability URL must use configured origin")
    for key in ("location_id", "group_id"):
        if not str(config[key]).isdigit() or int(config[key]) <= 0:
            raise ValueError("Expected positive provider ID: " + key)
    return config, base.rstrip("/"), page


def _check_request(request, deps):
    config, _, _ = _config(deps)
    if (request.room.location.provider != config["provider"]
            or request.room.location.location_id != str(config["location_id"])
            or request.interval.timezone != config["timezone"]):
        raise ValueError("Request does not match caller configuration")
    if not request.room.room_id.isdigit() or int(request.room.room_id) <= 0:
        raise ValueError("Expected positive resource ID")
    return config


def _exchange(deps, method, path, pairs=(), *, auth=False, redirects=0):
    config, base, page = _config(deps)
    url = urljoin(base, path)
    allowed = {_origin(base)}
    if auth:
        allowed.update(config.get("auth_origins", ()))
    if _origin(url) not in allowed:
        raise _Failure("Authentication origin is not caller-approved", Outcome.AUTHENTICATION_REQUIRED)
    headers = {"User-Agent": "library-room-booking/0.0.0.dev1", "Referer": page}
    body = None
    if method == "POST":
        headers.update({"Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest"})
        body = urlencode(pairs).encode("utf-8")
    # Transport owns session/cookies, deadlines, size bounds and redirect prevention.
    response = deps.transport(method=method, url=url, headers=headers, body=body)
    if type(response) is not Response or type(response.body) is not str:
        raise _Failure("Malformed transport response")
    if auth and response.status in (301, 302, 303) and redirects < 3:
        target = response.headers.get("Location")
        if type(target) is not str or not target:
            raise _Failure("Authentication redirect has no target", Outcome.AUTHENTICATION_REQUIRED)
        return _exchange(deps, "GET", urljoin(url, target), auth=True, redirects=redirects+1)
    if _origin(response.url) != _origin(url) or urlsplit(response.url).path != urlsplit(url).path:
        raise _Failure("Unexpected redirect; authentication or provider flow changed", Outcome.AUTHENTICATION_REQUIRED)
    if response.status in (401, 403):
        raise _Failure("Provider requires authentication", Outcome.AUTHENTICATION_REQUIRED)
    if response.status != 200:
        raise _Failure("Provider returned HTTP " + str(response.status))
    return response


def _json_response(deps, path, pairs):
    response = _exchange(deps, "POST", path, pairs)
    try:
        data = json.loads(response.body)
    except (ValueError, TypeError):
        raise _Failure("Malformed provider JSON") from None
    if type(data) is not dict:
        raise _Failure("Expected provider JSON object")
    return data, response


def _wall(value, zone):
    return value.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M:%S")


def _provider_instant(value, zone):
    # LibCal sends naive wall times. Refuse ambiguous folds and nonexistent times.
    naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    tz = ZoneInfo(zone)
    options = {naive.replace(tzinfo=tz, fold=f).astimezone(timezone.utc) for f in (0, 1)
               if naive.replace(tzinfo=tz, fold=f).astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == naive}
    if len(options) != 1:
        raise _Failure("Provider wall time is ambiguous or nonexistent")
    return options.pop()


def _window(request, config):
    start, end = request.interval.bounds()
    zone = request.interval.timezone
    return [("lid", str(config["location_id"])), ("gid", str(config["group_id"])),
            ("start", start.astimezone(ZoneInfo(zone)).date().isoformat()),
            ("end", (end.astimezone(ZoneInfo(zone)).date() + timedelta(days=1)).isoformat())]


def _pending_payload(booking):
    return {key: booking[key] for key in ("id", "eid", "seat_id", "gid", "lid", "start", "end", "checksum")}


def _nested(pending):
    return [(f"bookings[0][{key}]", str(value)) for key, value in _pending_payload(pending).items()]


def _pending(data, request, config, *, require_end=False):
    bookings = data.get("bookings")
    if type(bookings) is not list or len(bookings) != 1 or type(bookings[0]) is not dict:
        raise _Failure("Expected one exact pending booking")
    pending = bookings[0]
    for key in ("id", "eid", "seat_id", "gid", "lid", "start", "end", "checksum"):
        if key not in pending or type(pending[key]) not in (str, int) or str(pending[key]) == "":
            raise _Failure("Missing pending booking field: " + key)
    start, end = request.interval.bounds()
    if (str(pending["eid"]) != request.room.room_id or str(pending["lid"]) != str(config["location_id"])
            or str(pending["gid"]) != str(config["group_id"]) or str(pending["seat_id"]) != "0"
            or _provider_instant(str(pending["start"]), request.interval.timezone) != start
            or (require_end and _provider_instant(str(pending["end"]), request.interval.timezone) != end)):
        raise _Failure("Pending booking identity or interval mismatch")
    return pending


@dataclass(frozen=True)
class _LibCalFormControl:
    name: str
    value: str
    input_type: str
    required: bool
    disabled: bool
    concealed: bool
    honeypot: bool
    checked: bool


class _LibCalFormParser(HTMLParser):
    _void_tags = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    _honeypot_classes = {"slc-hi", "s-input-hp"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.controls: list[_LibCalFormControl] = []
        self._stack: list[tuple[str, bool, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_tag(tag, attrs, push=tag.lower() not in self._void_tags)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_tag(tag, attrs, push=False)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                return

    def _handle_tag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        push: bool,
    ) -> None:
        tag = tag.lower()
        attributes = {key.lower(): (value or "") for key, value in attrs}
        parent_concealed = self._stack[-1][1] if self._stack else False
        parent_honeypot = self._stack[-1][2] if self._stack else False
        style = re.sub(r"\s+", "", attributes.get("style", "").lower())
        classes = set(attributes.get("class", "").lower().split())
        concealed = parent_concealed or (
            "hidden" in attributes
            or attributes.get("aria-hidden", "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        honeypot = parent_honeypot or bool(classes & self._honeypot_classes)
        if tag in {"input", "select", "textarea"}:
            input_type = attributes.get("type", "text").lower() if tag == "input" else tag
            name = attributes.get("name", "")
            if name:
                self.controls.append(_LibCalFormControl(
                    name=name,
                    value=attributes.get("value", ""),
                    input_type=input_type,
                    required="required" in attributes,
                    disabled="disabled" in attributes,
                    concealed=concealed or input_type == "hidden",
                    honeypot=honeypot,
                    checked="checked" in attributes,
                ))
        if push:
            self._stack.append((tag, concealed, honeypot))


def _form_controls(form_html: str) -> list[_LibCalFormControl]:
    parser = _LibCalFormParser()
    parser.feed(form_html)
    parser.close()
    return parser.controls


def _form_field_names(form_html: str) -> list[str]:
    return [control.name for control in _form_controls(form_html)]


def _required_form_field_names(form_html: str) -> list[str]:
    return [
        control.name for control in _form_controls(form_html)
        if control.required
        and not control.disabled
        and not control.concealed
        and not control.honeypot
    ]


def _honeypot_field_names(form_html: str) -> list[str]:
    names = [control.name for control in _form_controls(form_html) if control.honeypot]
    for match in re.finditer(
        r"<div[^>]+(?:slc-hi|s-input-hp)[^>]*>.*?</div>\s*<script>.*?removeChild\(element\).*?</script>",
        form_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        names.extend(_form_field_names(match.group(0)))
    return names


def _known_required_form_fields() -> set[str]:
    return {
        "fname",
        "lname",
        "email",
        "q1314",
        "phone-number",
        "nick",
        "q3240",
        "q26893",
        "q26895",
        "q26896",
        "q26898",
        "terms",
        "q9176",
    }


def _known_honeypot_field_names() -> set[str]:
    return {"Address", "DOB", "E-mail", "Feedback", "Name", "Question", "URL", "Zip"}


def _input_value(form_html: str, name: str) -> str:
    for tag in re.findall(r"<input\b[^>]*>", form_html, flags=re.IGNORECASE):
        if _tag_attr(tag, "name") == name:
            return _tag_attr(tag, "value")
    return ""


def _tag_attr(tag: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1", tag, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return ""
    return html_lib.unescape(match.group(2))


def _generic_confirmation_words() -> set[str]:
    return {"booked", "booking", "confirmed", "submitted", "success", "successful"}


def _clean_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html_lib.unescape(without_tags).split())



def _authenticate(deps, redirect):
    config, _, _ = _config(deps)
    if not config.get("auth_origins"):
        raise _Failure("Authentication required; no caller-approved login origins", Outcome.AUTHENTICATION_REQUIRED)
    response = _exchange(deps, "GET", redirect, auth=True)
    action = re.search(r"<form\b[^>]*\baction=[\"']([^\"']+)", response.body, re.I)
    controls = _form_controls(response.body)
    names = {c.name for c in controls}
    if not action or not {"username", "password"} <= names:
        raise _Failure("Authentication form changed", Outcome.AUTHENTICATION_REQUIRED)
    action_url = urljoin(response.url, html_lib.unescape(action[1]))
    # Validate action before asking the caller for credentials.
    if _origin(action_url) not in {_origin(config["base_url"]), *config["auth_origins"]}:
        raise _Failure("Authentication action origin is not caller-approved", Outcome.AUTHENTICATION_REQUIRED)
    credentials = deps.credentials()
    if (not isinstance(credentials, dict) or any(type(credentials.get(k)) is not str or not credentials[k]
                                               for k in ("username", "password"))):
        raise _Failure("Caller authentication credentials unavailable", Outcome.AUTHENTICATION_REQUIRED)
    payload = [(c.name, c.value) for c in controls if not c.disabled and c.input_type == "hidden"
               and c.name not in {"username", "password"}]
    payload.extend((key, credentials[key]) for key in ("username", "password"))
    response = _exchange(deps, "POST", action_url, payload, auth=True)
    if not _input_value(response.body, "session") or re.search(r"name=[\"']password[\"']", response.body, re.I):
        raise _Failure("Authentication did not return a booking-details session", Outcome.AUTHENTICATION_REQUIRED)
    if _origin(response.url) != _origin(config["base_url"]):
        raise _Failure("Booking-details form came from a foreign origin", Outcome.AUTHENTICATION_REQUIRED)
    return response.body


def _parse_libcal_booking_method(page):
    match = re.search(r"\bbookingMethod\s*:\s*(\d+)", page)
    return int(match[1]) if match else 11


def _form_payload(form_html, pending, deps, method):
    controls = _form_controls(form_html)
    if not controls or not _input_value(form_html, "session"):
        raise _Failure("Booking-details form has no session; authentication or markup changed")
    required = set(_required_form_field_names(form_html))
    traps = set(_honeypot_field_names(form_html)) | _known_honeypot_field_names()
    selects = {c.name for c in controls if c.input_type == "select"
               and not c.disabled and not c.concealed and c.name not in traps}
    if selects:
        raise _Failure("Unsupported select fields: " + ", ".join(sorted(selects)))
    # Caller deliberately supplies attendance, event answers and consent. No app policy.
    values = dict(deps.configuration.get("form_values", {}))
    contact = deps.contact
    values.update({"fname": contact.get("first_name", ""), "lname": contact.get("last_name", ""),
                   "email": contact.get("email", ""), "q1314": contact.get("phone", ""),
                   "phone-number": contact.get("phone", ""), "q26896": contact.get("phone", "")})
    unsupported = required - _known_required_form_fields() - traps
    if unsupported:
        raise _Failure("Unsupported required fields: " + ", ".join(sorted(unsupported)))
    missing = [name for name in required - traps if type(values.get(name)) is not str or not values[name].strip()]
    if missing:
        raise _Failure("Missing required patron fields: " + ", ".join(sorted(missing)))
    for control in controls:
        if control.name in required - traps and control.input_type in {"radio", "checkbox"}:
            choices = {c.value for c in controls if c.name == control.name and not c.disabled}
            if values[control.name] not in choices:
                raise _Failure("Invalid required choice: " + control.name)
    protocol = {"bookings", "returnUrl", "pickupHolds", "method"}
    payload = [(c.name, c.value) for c in controls if c.name not in protocol | required | traps
               and not c.disabled and (c.input_type == "hidden" or c.checked or c.name == "session")]
    provided = {name for name, _ in payload}
    for control in controls:
        if control.name in required - traps - provided:
            payload.append((control.name, values[control.name]))
            provided.add(control.name)
    _, _, page = _config(deps)
    return payload + [("bookings", json.dumps([_pending_payload(pending)], separators=(",", ":"))),
                      ("returnUrl", page), ("pickupHolds", ""), ("method", str(method))]


class LibCalAdapter:
    """One caller session per Dependencies. Caller owns cross-process attempt claims.

    claim_submission(request) must atomically deny any already possible submission.
    It is invoked immediately before the submit transport, after preparation.
    """
    capabilities = capabilities(discovery="supported", availability="supported", booking="supported")
    operation_effects = MappingProxyType({"discovery": "read", "availability": "read", "preparation": "write", "booking": "write"})

    def __init__(self, *, claim_submission: Callable[[BookingRequest], bool]):
        self._claim = claim_submission

    def discover(self, location, dependencies):
        deps = dependencies
        config, _, page = _config(deps)
        if location != Location(config["provider"], str(config["location_id"]), config["timezone"]):
            raise ValueError("Discovery location does not match configuration")
        try:
            body = _exchange(deps, "GET", page).body
            # Public landing pages may link the actual resource grid. Follow one
            # same-origin link bound to this exact location and configured group.
            if not re.search(r"resources\.push|\bresources\s*=", body):
                for raw in re.findall(r"href=[\"']([^\"']+)", body, re.I):
                    target = urlsplit(urljoin(page, html_lib.unescape(raw)))
                    if (target.scheme == urlsplit(page).scheme and target.netloc == urlsplit(page).netloc
                            and target.path == "/r/new/availability"
                            and parse_qs(target.query).get("lid") == [str(config["location_id"])]):
                        path = target.path + "?" + urlencode({"lid":config["location_id"], "gid":config["group_id"]})
                        body = _exchange(deps, "GET", path).body
                        break
            blocks = re.findall(r"resources\.push\(\s*\{(.*?)\}\s*\);", body, re.S)
            for array in re.findall(r"\b(?:var|let|const)\s+resources\s*=\s*\[(.*?)\]\s*;", body, re.S):
                blocks.extend(re.findall(r"\{([^{}]*)\}", array, re.S))
            resources = {}
            for block in blocks:
                def number(key):
                    match = re.search(r"\b" + key + r"\s*:\s*(\d+)", block)
                    return int(match[1]) if match else None
                if number("lid") != int(config["location_id"]) or number("gid") != int(config["group_id"]):
                    continue
                name = re.search(r'\btitle\s*:\s*"((?:\\.|[^"\\])*)"', block)
                eid, capacity = number("eid"), number("capacity")
                if not name or not eid or capacity is None:
                    raise _Failure("Malformed provider resource")
                resource = Resource(Room(location, str(eid)), html_lib.unescape(json.loads('"'+name[1]+'"')), capacity, str(config["group_id"]))
                if str(eid) in resources and resources[str(eid)] != resource:
                    raise _Failure("Conflicting provider resource identity")
                resources[str(eid)] = resource
            if not resources:
                raise _Failure("Unrecognized resources markup; supply verified location/group configuration")
            return DiscoveryResult(Outcome.AVAILABLE, location, tuple(resources.values()))
        except _Failure as exc:
            return DiscoveryResult(exc.outcome, location, detail=exc.detail)
        except Exception:
            return DiscoveryResult(Outcome.FAILED_BEFORE_SUBMIT, location, detail="Discovery transport or parsing failed")

    def _slots(self, request, deps):
        config = _check_request(request, deps)
        _, _, page = _config(deps)
        _exchange(deps, "GET", page)  # caller transport retains cookies
        data, _ = _json_response(deps, "/spaces/availability/grid", _window(request, config) + [
            ("eid", request.room.room_id), ("seat", "0"), ("seatId", "0"), ("zone", "0"),
            ("filters", ""), ("bookings", "[]"), ("pageIndex", "0"), ("pageSize", "100")])
        if type(data.get("slots")) is not list:
            raise _Failure("Unrecognized availability schedule")
        rows = []
        for slot in data["slots"]:
            if type(slot) is not dict:
                raise _Failure("Malformed slot")
            if str(slot.get("itemId")) != request.room.room_id:
                continue
            try:
                start = _provider_instant(slot["start"], request.interval.timezone)
                end = _provider_instant(slot["end"], request.interval.timezone)
                if end <= start:
                    raise ValueError("Invalid slot interval")
                classes = slot.get("className") or []
                if type(classes) is str:
                    classes = classes.split()
                if type(classes) is not list or any(type(c) is not str for c in classes):
                    raise ValueError("Invalid slot classes")
                rows.append((start, end, classes, slot.get("checksum")))
            except (ValueError, KeyError, TypeError):
                raise _Failure("Malformed slot interval or status") from None
        return rows, data.get("windowEnd") is True

    def _availability(self, request, deps):
        rows, window_end = self._slots(request, deps)
        start, end = request.interval.bounds()
        red = {"s-lc-eq-checkout", "s-lc-eq-r-unavailable", "s-lc-eq-r-padding",
               "s-lc-eq-unavailable", "s-lc-eq-period-booked"}
        if any(s < end and e > start and red.intersection(c) for s, e, c, _ in rows):
            return LibCalResult(Outcome.UNAVAILABLE, request, detail="Explicit unavailable/padding slot"), rows
        cursor = start
        while cursor < end:
            ends = [e for s, e, c, _ in rows if s == cursor and not c]
            if not ends:
                outcome = Outcome.DEFERRED if window_end else Outcome.FAILED_BEFORE_SUBMIT
                return LibCalResult(outcome, request, detail="Booking window closed" if window_end else "Incomplete or unrecognized slot coverage"), rows
            cursor = max(ends)
        return LibCalResult(Outcome.AVAILABLE, request, slots=(request.interval,)), rows

    def availability(self, request, dependencies):
        _check_request(request, dependencies)
        try:
            return self._availability(request, dependencies)[0]
        except _Failure as exc:
            return LibCalResult(exc.outcome, request, detail=exc.detail)
        except Exception:
            return LibCalResult(Outcome.FAILED_BEFORE_SUBMIT, request, detail="Availability transport or parsing failed")

    def prepare(self, request, dependencies):
        """WRITE-CAPABLE: can create/update temporary holds. Never use in monitors."""
        if type(request) is not BookingRequest:
            raise ValueError("Expected booking request")
        deps = replace(dependencies, configuration=MappingProxyType({**dependencies.configuration,
            "form_values": MappingProxyType(dict(dependencies.configuration.get("form_values", {}))),
            "auth_origins": tuple(dependencies.configuration.get("auth_origins", ()))}),
            contact=MappingProxyType(dict(dependencies.contact)))
        config = _check_request(request, deps)
        holding = False
        try:
            result, rows = self._availability(request, deps)
            if result.outcome is not Outcome.AVAILABLE:
                return result
            start, end = request.interval.bounds()
            zone = request.interval.timezone
            # The provider protocol cannot encode an ambiguous or missing local time.
            for value in (start, end):
                if _provider_instant(_wall(value, zone), zone) != value:
                    raise _Failure("Provider cannot encode this interval")
            checksums = {checksum for s, _, classes, checksum in rows if s == start and not classes and type(checksum) is str and checksum}
            if len(checksums) != 1:
                raise _Failure("Missing or conflicting start checksum")
            _, _, page = _config(deps)
            markup = _exchange(deps, "GET", page).body
            method = _parse_libcal_booking_method(markup)
            holding = True  # set before transport: a timeout may still leave a hold
            data, _ = _json_response(deps, "/spaces/availability/booking/add", [
                ("add[eid]", request.room.room_id), ("add[seat_id]", "0"), ("add[gid]", str(config["group_id"])),
                ("add[lid]", str(config["location_id"])), ("add[start]", _wall(start, zone)),
                ("add[checksum]", next(iter(checksums))), *_window(request, config), ("bookings", "[]")])
            pending = _pending(data, request, config)
            if str(pending["end"]) != _wall(end, zone):
                options, checksums = pending.get("options"), pending.get("optionChecksums")
                if type(options) is not list or type(checksums) is not list or options.count(_wall(end, zone)) != 1:
                    raise _Failure("Requested end time is not offered")
                index = options.index(_wall(end, zone))
                if index >= len(checksums) or type(checksums[index]) is not str or not checksums[index]:
                    raise _Failure("Missing requested end checksum")
                data, _ = _json_response(deps, "/spaces/availability/booking/add", [
                    ("update[id]", str(pending["id"])), ("update[checksum]", checksums[index]),
                    ("update[end]", _wall(end, zone)), *_window(request, config), *_nested(pending)])
                updated = _pending(data, request, config, require_end=True)
                if str(updated["id"]) != str(pending["id"]):
                    raise _Failure("Pending booking identity changed during end update")
                pending = {**updated, "id": pending["id"]}
            data, _ = _json_response(deps, "/ajax/space/times", [
                ("patron", ""), ("patronHash", ""), ("returnUrl", page), ("method", str(method)), *_nested(pending)])
            if data.get("redirect"):
                data = {"html": _authenticate(deps, data["redirect"])}
            if type(data.get("html")) is not str:
                raise _Failure("Unrecognized booking-details form")
            payload = _form_payload(data["html"], pending, deps, method)
            return PreparedBooking(request, deps, tuple(payload), self)
        except _Failure as exc:
            return LibCalResult(exc.outcome, request, detail=exc.detail, preparation_attempted=holding)
        except Exception:
            return LibCalResult(Outcome.FAILED_BEFORE_SUBMIT, request, detail="Preparation transport or parsing failed; a temporary hold may remain" if holding else "Preparation transport or parsing failed", preparation_attempted=holding)

    def submit(self, prepared):
        if type(prepared) is not PreparedBooking or prepared._owner is not self:
            raise ValueError("Prepared booking belongs to another adapter")
        request, deps = prepared.request, prepared._dependencies
        _, base, _ = _config(deps)
        with prepared._lock:
            if prepared._used:
                return LibCalResult(Outcome.UNKNOWN_AFTER_SUBMIT, request, detail="Prepared attempt already consumed; reconcile caller claim", expected_origin=base, preparation_attempted=True)
            prepared._used.append(True)
        try:
            claimed = self._claim(request)
        except Exception:
            return LibCalResult(Outcome.FAILED_BEFORE_SUBMIT, request, detail="Caller claim failed; no submit sent", preparation_attempted=True)
        if claimed is not True:
            return LibCalResult(Outcome.UNKNOWN_AFTER_SUBMIT, request, detail="Caller denied duplicate or unresolved attempt; no submit sent", expected_origin=base, preparation_attempted=True)
        # Retain the receipt before status, redirect or body validation can fail.
        response_reference = None
        def submit_transport(**kwargs):
            nonlocal response_reference
            response = deps.transport(**kwargs)
            if type(response) is Response:
                response_reference = response.reference
            return response
        # Every exception from here is uncertain, including HTTP/auth and malformed JSON.
        try:
            data, response = _json_response(replace(deps, transport=submit_transport), "/ajax/space/book", prepared._payload)
            if data.get("error"):
                return LibCalResult(Outcome.REJECTED, request, detail="Provider explicitly rejected booking; caller reconciles before retry", expected_origin=base, reference=response.reference, preparation_attempted=True, submission_attempted=True)
            markup = data.get("html")
            if type(markup) is not str or not markup.strip():
                raise _Failure("Missing submission receipt")
            # Remove URL capabilities; conflicting explicit identifiers remain unverified.
            text = re.sub(r"<[^>]+>", " ", markup)
            ids = set()
            for pattern in (r"\bBooking_[A-Z0-9-]+\b", r"(?:confirmation(?:\s+(?:code|number|id))?|reference(?:\s+(?:code|number|id))?|booking\s+(?:id|number))\s*[:#]\s*([A-Z0-9][A-Z0-9_-]{3,})"):
                for match in re.finditer(pattern, html_lib.unescape(text), re.I):
                    candidate = match.group(1) if match.lastindex else match.group(0)
                    if candidate.lower() not in _generic_confirmation_words():
                        ids.add(candidate)
            booking_id = next(iter(ids)) if len(ids) == 1 else None
            matches = [e for e in deps.evidence if evidence_matches(e, request, booking_id, base)]
            # Conflicting or multiple caller receipts are never silently selected.
            exact = len(deps.evidence) == 1 and len(matches) == 1
            outcome = Outcome.CONFIRMED if exact else Outcome.PENDING_CONFIRMATION
            if not booking_id and not re.search(r"\b(submitted|confirmed|success(?:ful)?|booked)\b", _clean_html(markup), re.I):
                outcome = Outcome.UNKNOWN_AFTER_SUBMIT
            return LibCalResult(outcome, request, booking_id=booking_id, evidence=matches[0] if exact else None,
                                expected_origin=base, reference=response.reference,
                                detail="Exact caller evidence verified" if exact else "Caller must reconcile exact reservation identity and origin",
                                preparation_attempted=True, submission_attempted=True)
        except Exception:
            return LibCalResult(Outcome.UNKNOWN_AFTER_SUBMIT, request, detail="Submission may have succeeded; reconcile without replay", expected_origin=base, reference=response_reference, preparation_attempted=True, submission_attempted=True)

    def book(self, request, dependencies):
        prepared = self.prepare(request, dependencies)
        return self.submit(prepared) if type(prepared) is PreparedBooking else prepared
