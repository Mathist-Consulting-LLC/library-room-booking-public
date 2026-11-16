"""Pure receipt evidence and injected single-booking cancellation; see docs/evidence.md."""
from __future__ import annotations
import base64
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parseaddr
from html.parser import HTMLParser
import html
import json
import re
import urllib.parse
from zoneinfo import ZoneInfo
from . import BookingRequest, ConfirmationEvidence, Interval, evidence_matches
from .libcal import _exchange, _check_request, _origin

def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", value)).strip()


def _cancel_endpoint(page_html: str, origin: str) -> str | None:
    matches = set(re.findall(r'["\'](/ajax/equipment/cancel/[A-Za-z0-9_-]{6,})["\']', page_html, re.I))
    if len(matches) != 1:
        return None
    endpoint = urllib.parse.urljoin(origin, next(iter(matches)))
    parsed = urllib.parse.urlsplit(endpoint)
    expected = urllib.parse.urlsplit(origin)
    if parsed.scheme != "https" or parsed.netloc.lower() != expected.netloc.lower():
        return None
    return endpoint


def _single_cancel_endpoint(page_html: str, origin: str, confirmation: str) -> str | None:
    """Return the page-authored endpoint for one exact booking, never cancel-all."""
    group_endpoint = _cancel_endpoint(page_html, origin)
    if not group_endpoint or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", str(confirmation)):
        return None
    if _exact_booking_content(page_html, str(confirmation)) is None:
        return None
    group_path = urllib.parse.urlsplit(group_endpoint).path.rstrip("/")
    authored_single = re.compile(
        rf'["\']{re.escape(group_path + "/")}["\']\s*\+\s*bookingId\b', re.I
    )
    if not authored_single.search(page_html):
        return None
    endpoint = urllib.parse.urljoin(origin, group_path + "/" + urllib.parse.quote(str(confirmation), safe=""))
    parsed = urllib.parse.urlsplit(endpoint)
    expected = urllib.parse.urlsplit(origin)
    return endpoint if parsed.scheme == "https" and parsed.netloc.lower() == expected.netloc.lower() else None


def _page_identity_markers(page_html: str) -> tuple[set[str], set[str], set[str]]:
    decoded = html.unescape(page_html)
    booking_ids = set(re.findall(
        r'\bid\s*=\s*["\']?booking_([A-Za-z0-9_-]+)', decoded, re.I
    ))
    single_ids = set(re.findall(
        r'\bid\s*=\s*["\']?s-lc-cancel-confirm-single-([A-Za-z0-9_-]+)', decoded, re.I
    ))
    endpoints = set(re.findall(
        r'["\'](/ajax/equipment/cancel/[A-Za-z0-9_-]{6,})["\']', decoded, re.I
    ))
    return booking_ids, single_ids, endpoints


def _page_has_ambiguous_identity(page_html: str) -> bool:
    booking_ids, single_ids, endpoints = _page_identity_markers(page_html)
    identities = booking_ids | single_ids
    return (len(identities) > 1 or len(endpoints) > 1
            or bool(booking_ids and single_ids and booking_ids != single_ids))


def _page_identity_matches_confirmation(page_html: str, confirmation: str) -> bool:
    booking_ids, single_ids, _ = _page_identity_markers(page_html)
    identities = booking_ids | single_ids
    return not identities or identities == {str(confirmation)}


def _page_state(page_html: str, origin: str) -> tuple[str, str | None]:
    if _page_has_ambiguous_identity(page_html):
        return "unknown", None
    booking_ids, single_ids, endpoints = _page_identity_markers(page_html)
    endpoint = _cancel_endpoint(page_html, origin)
    text = _clean_text(page_html).lower()
    if endpoint and ("cancel all bookings" in text or "cancel booking" in text):
        return "active", endpoint
    # Terminal text is authoritative only inside one exact booking container,
    # after active controls and endpoints are gone. Identity-less page prose
    # cannot prove which mailbox-backed reservation was cancelled.
    if len(booking_ids) == 1 and not single_ids and not endpoints:
        confirmation = next(iter(booking_ids))
        exact = _exact_booking_content(page_html, confirmation)
        # The parser already decoded HTML. Preserve all of that text and
        # require one complete statement; conditional/corrective prose cannot
        # establish a terminal state by containing a cancellation substring.
        cancelled_text = re.sub(r"\s+", " ", exact[0]).strip() if exact is not None else ""
        terminal = (
            r"no (?:active )?(?:bookings?|reservations?) (?:were )?found",
            r"could not find (?:the )?(?:bookings?|reservations?)",
            r"(?:bookings?|reservations?) (?:(?:have|has|was|were|is|are) )?(?:already )?cancel(?:led|ed)",
        )
        if any(re.fullmatch(pattern + r"[.!]?", cancelled_text, re.I) for pattern in terminal):
            return "cancelled", None
    return "unknown", None


def _page_identifies_interval(booking_text: str, starts_at: object, ends_at: object, timezone: str) -> bool:
    try:
        zone = ZoneInfo(timezone)
        start = datetime.fromisoformat(str(starts_at).replace("Z", "+00:00")).astimezone(zone)
        end = datetime.fromisoformat(str(ends_at).replace("Z", "+00:00")).astimezone(zone)
    except (KeyError, TypeError, ValueError):
        return False
    # The date/time field must stand on its own. Never search later help hours
    # to fill an unsupported or missing reservation time in this field.
    # Input is decoded text from _exact_booking_content, never raw markup.
    # A second markup strip could erase escaped conflicting reservation text.
    fields = [re.sub(r"\s+", " ", value).strip().casefold()
              for value in booking_text.splitlines()]
    dated_fields = [value for value in fields if re.search(r'\b20\d{2}\b', value)]
    if len(dated_fields) != 1:
        return False
    text = dated_fields[0]
    text = text.translate(str.maketrans({
        value: "-" for value in "‐‑‒–—―−﹘﹣－"
    }))
    months = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    }
    page_dates = set()
    month_names = "|".join(sorted(months, key=len, reverse=True))
    for match in re.finditer(rf"\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(20\d{{2}})\b", text):
        try: page_dates.add(datetime(int(match.group(3)), months[match.group(1)], int(match.group(2))).date())
        except ValueError: return False
    for match in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text):
        try: page_dates.add(datetime(int(match.group(3)), int(match.group(1)), int(match.group(2))).date())
        except ValueError: return False
    expected_dates = {start.date(), end.date()}
    if not page_dates or not page_dates.issubset(expected_dates) or start.date() not in page_dates:
        return False
    text = re.sub(rf"\b({month_names})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+20\d{{2}}\b", '', text)
    text = re.sub(r"\b\d{1,2}/\d{1,2}/20\d{2}\b", '', text)
    text = re.sub(r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', '', text).strip(' ,')
    # Parse every displayed time-range shape that LibCal commonly renders. A
    # range we can see but cannot normalize must fail closed: otherwise an
    # unrelated footer range could be the only parsed value and authorize the
    # cancellation of a differently timed booking.
    meridiem = r"([ap])(?:\.?\s*m\.?)?"
    token = rf"(\d{{1,2}})(?::(\d{{2}}))?\s*(?:{meridiem})?"
    range_pattern = re.compile(token + r"\s*(?:-|to|until|through|thru)\s*" + token + r"(?!\w)")
    if not range_pattern.fullmatch(text):
        return False
    intervals = set()
    range_spans = []
    for match in range_pattern.finditer(text):
        first_minute, second_minute = match.group(2), match.group(5)
        first_meridiem, second_meridiem = match.group(3), match.group(6)
        # Ignore ordinary numeric ranges such as room capacity 7-25. Every
        # clock-like range (a colon or a meridiem) must be understood exactly.
        if not any((first_minute, second_minute, first_meridiem, second_meridiem)):
            continue
        range_spans.append(match.span())
        if first_meridiem and not second_meridiem:
            second_meridiem = first_meridiem
        elif second_meridiem and not first_meridiem:
            first_meridiem = second_meridiem
        if bool(first_meridiem) != bool(second_meridiem):
            return False

        def minute_of_day(hour_value: str, minute_value: str | None, meridiem: str | None) -> int:
            hour = int(hour_value)
            minute = int(minute_value or "0")
            if minute > 59:
                raise ValueError
            if meridiem:
                if hour < 1 or hour > 12:
                    raise ValueError
                return (hour % 12 + (12 if meridiem == "p" else 0)) * 60 + minute
            if hour < 0 or hour > 23 or first_minute is None or second_minute is None:
                raise ValueError
            return hour * 60 + minute
        try:
            intervals.add((
                minute_of_day(match.group(1), first_minute, first_meridiem),
                minute_of_day(match.group(4), second_minute, second_meridiem),
            ))
        except ValueError:
            return False
    # Do not let an unrecognized range disappear while a footer or help-hours
    # range happens to equal the reservation. Every clock token on this
    # capability page must belong to one interval we parsed above. This is
    # intentionally fail-closed for new provider markup and standalone times.
    clock_token = re.compile(
        r"(?<![\w:])(?:\d{1,2}:\d{2}\s*(?:[ap](?:\.?\s*m\.?)?)?"
        r"|\d{1,2}\s*[ap](?:\.?\s*m\.?)?)(?![\w:])"
    )
    for clock in clock_token.finditer(text):
        if not any(start <= clock.start() and clock.end() <= end for start, end in range_spans):
            return False
    expected_interval = (start.hour * 60 + start.minute, end.hour * 60 + end.minute)
    return intervals == {expected_interval}


def _exact_booking_content(page_html: str, confirmation: str) -> tuple[str, list[str]] | None:
    """Return only text and single-cancel identities owned by one exact booking node."""
    target_id = f"booking_{confirmation}".casefold()

    class BookingParser(HTMLParser):
        VOID_ELEMENTS = {
            "area", "base", "br", "col", "command", "embed", "hr", "img",
            "input", "keygen", "link", "meta", "param", "source", "track", "wbr",
        }

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.stack: list[str] = []
            self.targets = 0
            self.target_depth: int | None = None
            self.valid = True
            self.text: list[str] = []
            self.single_ids: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            tag = tag.casefold()
            values = {name.casefold(): str(value or "") for name, value in attrs}
            identity = values.get("id", "")
            if identity.casefold() == target_id:
                self.targets += 1
                if self.target_depth is not None or tag in self.VOID_ELEMENTS:
                    self.valid = False
                else:
                    self.target_depth = len(self.stack) + 1
            if self.target_depth is not None and identity.casefold().startswith("s-lc-cancel-confirm-single-"):
                self.single_ids.append(identity[len("s-lc-cancel-confirm-single-"):])
            if self.target_depth is not None and tag in {'br', 'p', 'div', 'h1', 'h2', 'li', 'tr'}:
                self.text.append('\n')
            if tag not in self.VOID_ELEMENTS:
                self.stack.append(tag)

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = {name.casefold(): str(value or "") for name, value in attrs}
            identity = values.get("id", "")
            if identity.casefold() == target_id:
                self.targets += 1
                self.valid = False
            if self.target_depth is not None and identity.casefold().startswith("s-lc-cancel-confirm-single-"):
                self.single_ids.append(identity[len("s-lc-cancel-confirm-single-"):])

        def handle_endtag(self, tag: str) -> None:
            tag = tag.casefold()
            if tag in self.VOID_ELEMENTS:
                self.valid = False
                return
            if not self.stack or self.stack[-1] != tag:
                self.valid = False
                return
            if self.target_depth is not None and tag in {'p', 'div', 'h1', 'h2', 'li', 'tr'}:
                self.text.append('\n')
            self.stack.pop()
            if self.target_depth is not None and len(self.stack) < self.target_depth:
                self.target_depth = None

        def handle_data(self, data: str) -> None:
            if self.target_depth is not None:
                self.text.append(data)

    parser = BookingParser()
    parser.feed(page_html)
    if not parser.valid or parser.targets != 1 or parser.target_depth is not None:
        return None
    return "".join(parser.text), parser.single_ids


def _page_identifies_exact_booking(page_html: str, room_name: str, confirmation: str,
                                   starts_at: object, ends_at: object, timezone: str) -> bool:
    exact = _exact_booking_content(page_html, confirmation)
    if exact is None:
        return False
    booking_content, single_ids = exact
    # Consume the whole exact container, including undated fields. Unknown
    # reservation prose cannot silently disappear beside a recognized interval.
    fields = [re.sub(r"\s+", " ", value).strip()
              for value in booking_content.splitlines() if value.strip()]
    expected = re.sub(r"\s+", " ", room_name).strip().casefold()
    if fields and fields[-1].casefold() == 'cancel booking':
        fields.pop()
    return (len(fields) == 2 and fields[0].casefold() == expected and bool(expected)
            and _page_identifies_interval(fields[1], starts_at, ends_at, timezone)
            and single_ids in ([], [str(confirmation)]))



DATE = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}'
TIME = r'\d{1,2}:\d{2}\s*[ap]m'
RANGE = rf'({TIME})\s*[-–]\s*({TIME})'
class MailText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('br','p','div','tr','li'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('p','div','tr','li'): self.parts.append('\n')
    def handle_data(self,data): self.parts.append(data)

def body_text(payload):
    parts=[]
    def walk(part):
        data=part.get('body',{}).get('data')
        mime=part.get('mimeType','')
        if data and mime in ('text/plain','text/html'):
            text=base64.urlsafe_b64decode(data+'='*(-len(data)%4)).decode('utf-8','replace')
            parts.append((mime,text))
        for child in part.get('parts',[]): walk(child)
    walk(payload)
    chosen=next((text for mime,text in parts if mime=='text/html'),None)
    if chosen is None: return next((text for _,text in parts),'')
    parser=MailText(); parser.feed(chosen)
    return ''.join(parser.parts)

def stamp(day,clock,zone):
    day=re.sub(r'^[A-Za-z]+,?\s+','',day).replace(',','')
    dt=datetime.strptime(day+' '+clock.replace(' ','').upper(),'%B %d %Y %I:%M%p')
    local = dt.replace(tzinfo=ZoneInfo(zone))
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        raise ValueError('Ambiguous or nonexistent receipt wall time')
    return local.isoformat()

def _receipt_status(value, library_name):
    """Recognize complete provider status statements, never status substrings."""
    patterns = {
        'confirmed': (r'(?:your (?:room )?)?booking (?:confirmation|confirmed|approved)',
            r'your (?:room )?booking has been approved',
            r'the following bookings have been confirmed',
            rf'your reservation at {re.escape(library_name)} is confirmed for'),
        'submitted': (r'your booking has been submitted',),
        'requested': (r'(?:your reservation|(?:your )?booking) request (?:has been )?submitted',
            r'not confirmed until approved'),
        'cancelled': (r'(?:your )?booking cancel(?:led|ed)',
            r'the following (?:bookings|reservations) have been cancel(?:led|ed)'),
        'denied': (r'(?:your )?booking (?:declined|denied|rejected)',
            rf'your reservation at {re.escape(library_name)} has been denied',
            r'the following booking request could not be approved'),
        'reminder': (r'reminder about your booking',),
    }
    value = value.strip().rstrip(':!.').strip()
    for status, choices in patterns.items():
        if any(re.fullmatch(pattern, value, re.I) for pattern in choices):
            return status
    return None


def _parse_message(raw, sender_address, zone, library_name):
    payload = raw.get('payload', {})
    headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}
    if parseaddr(headers.get('from', ''))[1].lower() != sender_address:
        return []
    status = _receipt_status(headers.get('subject', ''), library_name)
    if status is None:
        return []
    lines = [re.sub(r'[ \t]+', ' ', line).strip()
             for line in body_text(payload).splitlines() if line.strip()]
    # Every line must belong to the single record, a consistent complete status
    # statement, or a supported cancellation control. New text fails closed.
    record = []
    for line in lines:
        body_status = _receipt_status(line, library_name)
        if body_status is not None:
            if body_status != status:
                return []
            # Compact approval templates name the library in this statement.
            if re.fullmatch(r'your reservation at .+ is confirmed for:', line, re.I):
                record.append(line)
        elif (line.casefold() == 'cancel'
                or re.fullmatch(r'https://[^\s<>]+', line)
                or re.fullmatch(r'Staff may cancel your booking\. To cancel visit https://[^\s<>]+', line)):
            continue
        else:
            record.append(line)
    text = '\n'.join(record)
    standard = re.fullmatch(
        rf'Location: ([^\n]+)\nSpace: ([^\n]+)\nDate: ({DATE})\nTime: {RANGE}',
        text, re.I)
    if standard:
        library, room, day, start, end = standard.groups()
    else:
        compact = re.fullmatch(
            rf'(?:(?:Your reservation at ([^\n]+) is confirmed for:|([^\n]+ Library))\n)?'
            rf'([^\n]+?)(?::[ \t]*|\n){RANGE}\s+({DATE})', text, re.I)
        if compact is None:
            return []
        named_library, library_line, room, start, end, day = compact.groups()
        library = named_library or library_line or ''
        if not library:
            prefix = re.split(r'\s+(?:Study|Meeting|Community|Conference)\s+Room', room, flags=re.I)[0]
            if prefix != room:
                library = prefix + ' Library'
    row = dict(status=status, library=library.strip(), room=room.strip(),
               start=stamp(day, start, zone), end=stamp(day, end, zone), receiptIndex=0)
    identities = _attachment_identities(payload)
    if len(identities) == 1 and status == 'confirmed':
        row['confirmationId'] = next(iter(identities))
    return [row]


def _decoded_bodies(payload: dict) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []

    def walk(part: dict) -> None:
        data = (part.get("body") or {}).get("data")
        mime = str(part.get("mimeType") or "")
        if data and mime in {"text/plain", "text/html"}:
            raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
            result.append((mime, raw.decode("utf-8", "replace")))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload or {})
    return result


def _attachment_identities(payload: dict) -> set[str]:
    identities: set[str] = set()

    def walk(part: dict) -> None:
        match = re.fullmatch(r"Booking_(\d{4,20})\.ics", str(part.get("filename") or ""), re.I)
        if match:
            identities.add(match.group(1))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload or {})
    return identities


def _cancellation_links(payload: dict, expected_origin: str) -> set[str]:
    origin = urllib.parse.urlsplit(expected_origin)
    links: set[str] = set()
    for mime, body in _decoded_bodies(payload):
        values = (
            [html.unescape(value) for value in re.findall(r'href=["\']([^"\']+)', body, re.I)]
            if mime == "text/html"
            else re.findall(r'https?://[^\s<>"\']+', body, re.I)
        )
        for value in values:
            parsed = urllib.parse.urlsplit(value)
            if parsed.scheme != "https" or parsed.netloc.lower() != origin.netloc.lower():
                continue
            if parsed.path.rstrip("/") != "/equipment/cancel":
                continue
            token = urllib.parse.parse_qs(parsed.query).get("id", [])
            if len(token) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{6,}", token[0]):
                links.add(value)
    return links



@dataclass(frozen=True)
class Receipt:
    evidence: ConfirmationEvidence
    state: str
    _capability: str | None = field(default=None, repr=False)
    _room_name: str = field(default="", repr=False)


def parse_receipt(*, payload, subject, sender, authenticated_origin, expected_origin,
                  expected_sender, request, booking_id, library_name, room_name):
    """Parse supplied MIME content. Caller authenticates source, selects and retains mail.

    payload uses mimeType/body.data (base64url), parts and filename only. An ICS
    filename supplies identity, never event contents or proof of authentication.
    No header, link or filename alone can authenticate a receipt.
    """
    evidence = ConfirmationEvidence(request, booking_id, expected_origin, 'provider-receipt', False)
    unknown = Receipt(evidence, 'unverified')
    try:
        if (type(request) is not BookingRequest or not library_name or not room_name
                or authenticated_origin != expected_origin
                or expected_origin != _origin(expected_origin)
                or not expected_sender or sender != expected_sender):
            return unknown
        # Ignore caller-supplied headers: only the separately authenticated values apply.
        raw = {'payload': dict(payload, headers=[{'name':'From', 'value':sender},
                                                {'name':'Subject', 'value':subject}])}
        rows = _parse_message(raw, expected_sender, request.interval.timezone, library_name)
        text = body_text(payload)
        labels = [len(re.findall(r'(?im)^\s*' + name + r':', text))
                  for name in ('Location', 'Space', 'Date', 'Time')]
        if any(labels) and labels != [1, 1, 1, 1]:
            return unknown
        for mime, body in _decoded_bodies(payload):
            alternative = {'payload': {'mimeType': mime, 'body': {'data':
                base64.urlsafe_b64encode(body.encode()).decode()}, 'headers': raw['payload']['headers']}}
            if _parse_message(alternative, expected_sender, request.interval.timezone, library_name) != [
                    {k:v for k,v in row.items() if k != 'confirmationId'} for row in rows]:
                return unknown
        identities = _attachment_identities(payload)
        if len(rows) != 1 or identities != {booking_id}:
            return unknown
        row = rows[0]
        if (row.get('library') != library_name or row.get('room') != room_name
                or Interval(row['start'], row['end'], request.interval.timezone).bounds() != request.interval.bounds()):
            return unknown
        state = {'confirmed':'confirmed', 'requested':'pending', 'submitted':'submitted', 'cancelled':'cancelled',
                 'denied':'rejected'}.get(row['status'], 'unverified')
        verified = state == 'confirmed'
        evidence = ConfirmationEvidence(request, booking_id, expected_origin, 'provider-receipt', verified)
        links = _cancellation_links(payload, expected_origin)
        # Capability URLs are private, ephemeral fields and never part of neutral evidence.
        capability = next(iter(links)) if len(links) == 1 and state == 'confirmed' else None
        if capability is not None and not _valid_capability(capability, expected_origin):
            capability = None
        return Receipt(evidence, state, capability, room_name)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return unknown


def _valid_capability(url, origin):
    try:
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        return (_origin(url) == origin and parts.path == '/equipment/cancel'
                and set(query) == {'id'} and len(query['id']) == 1
                and re.fullmatch(r'[A-Za-z0-9_-]{6,}', query['id'][0]) is not None)
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class CancellationResult:
    state: str  # active (readback only), cancelled, unverified, unknown, authority_required, claim_denied
    submission_attempted: bool = False


class LibCalCancellation:
    """No transport defaults or replay. claim_cancellation owns durable authorization.

    A claim is consumed before any possible POST. A false/uncertain result must
    not be retried automatically. Fresh instances still require the same durable
    caller claim. Transport must prevent redirects and automatic request retries.
    """
    def __init__(self, *, claim_cancellation):
        self._claim = claim_cancellation
        from threading import Lock
        self._lock = Lock()
        self._used = set()

    def readback(self, *, receipt, request, booking_id, expected_origin, room_name,
                 dependencies):
        """Read one caller-authenticated capability; never claim or submit a write."""
        if (type(receipt) is not Receipt or receipt.state != 'confirmed'
                or not evidence_matches(receipt.evidence, request, booking_id, expected_origin)
                or room_name != receipt._room_name or not receipt._capability
                or not _valid_capability(receipt._capability, expected_origin)):
            return CancellationResult('unverified')
        try:
            _check_request(request, dependencies)
            if dependencies.configuration['base_url'].rstrip('/') != expected_origin:
                return CancellationResult('unverified')
            body = _exchange(dependencies, 'GET', receipt._capability).body
            state = _page_state(body, expected_origin)[0]
            if state == 'cancelled' and _page_identity_matches_confirmation(body, booking_id):
                return CancellationResult('cancelled')
            if (state == 'active' and _page_identifies_exact_booking(body, room_name, booking_id,
                    request.interval.start, request.interval.end, request.interval.timezone)
                    and _single_cancel_endpoint(body, expected_origin, booking_id)):
                return CancellationResult('active')
            return CancellationResult('unverified')
        except Exception:
            return CancellationResult('unverified')

    def cancel(self, *, receipt, request, booking_id, expected_origin, room_name,
               authorized, dependencies):
        if authorized is not True:
            return CancellationResult('authority_required')
        if (type(receipt) is not Receipt or receipt.state != 'confirmed'
                or not evidence_matches(receipt.evidence, request, booking_id, expected_origin)
                or room_name != receipt._room_name
                or not receipt._capability or not _valid_capability(receipt._capability, expected_origin)):
            return CancellationResult('unverified')
        submitted = False
        try:
            _check_request(request, dependencies)
            if dependencies.configuration['base_url'].rstrip('/') != expected_origin or not room_name:
                return CancellationResult('unverified')
            # The exact identity includes caller resource ID; the display name is
            # an additional page check, never a replacement for neutral identity.
            def page():
                return _exchange(dependencies, 'GET', receipt._capability).body

            def active(body):
                return (_page_state(body, expected_origin)[0] == 'active'
                        and _page_identifies_exact_booking(body, room_name, booking_id,
                            request.interval.start, request.interval.end, request.interval.timezone)
                        and _single_cancel_endpoint(body, expected_origin, booking_id))

            body = page()
            if (_page_state(body, expected_origin)[0] == 'cancelled'
                    and _page_identity_matches_confirmation(body, booking_id)):
                return CancellationResult('cancelled')
            endpoint = active(body)
            if not endpoint:
                return CancellationResult('unverified')
            # Reopen in the injected session, as in the source, and reject drift.
            if active(page()) != endpoint:
                return CancellationResult('unverified')
            key = (request.room, request.interval, booking_id, expected_origin)
            with self._lock:
                if key in self._used:
                    return CancellationResult('claim_denied')
                self._used.add(key)
            if self._claim(receipt.evidence) is not True:
                return CancellationResult('claim_denied')
            submitted = True
            response = _exchange(dependencies, 'POST', endpoint)
            result = json.loads(response.body)
            if type(result) is not dict or result.get('success') is not True or result.get('error'):
                return CancellationResult('unknown', True)
            readback = page()
            if (_page_state(readback, expected_origin)[0] == 'cancelled'
                    and _page_identity_matches_confirmation(readback, booking_id)):
                return CancellationResult('cancelled', True)
            return CancellationResult('unknown', True)
        except Exception:
            # Transport/claim errors can contain secrets. Never return or log them.
            return CancellationResult('unknown' if submitted else 'unverified', submitted)
