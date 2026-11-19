# Python API reference

Import from `library_room_booking` unless a module is shown. This inventory is derived from
current source declarations. Defaults, keyword-only arguments and record fields
are listed below; caller responsibilities are specified in [setup](setup.md).

## `library_room_booking`

[Source](../python/src/library_room_booking/__init__.py)

### `Outcome`

```python
instant(value: str, zone: str) -> datetime
```

### `Location`

Record fields (including shown defaults; inherited fields also apply):

```python
provider: str
location_id: str
timezone: str
```

### `Room`

Record fields (including shown defaults; inherited fields also apply):

```python
location: Location
room_id: str
```

### `Interval`

Record fields (including shown defaults; inherited fields also apply):

```python
start: str
end: str
timezone: str
```

```python
Interval.bounds(self)
```

```python
buffered_interval(interval: Interval, setup_minutes: int, cleanup_minutes: int)
```

```python
within_window(interval: Interval, window: Interval, *, setup_minutes=0, cleanup_minutes=0)
```

### `AvailabilityRequest`

Record fields (including shown defaults; inherited fields also apply):

```python
room: Room
interval: Interval
```

### `BookingRequest`

Record fields (including shown defaults; inherited fields also apply):

```python
attempt_id: str
```

### `ConfirmationEvidence`

Record fields (including shown defaults; inherited fields also apply):

```python
request: BookingRequest
booking_id: str
origin: str
reference: str
verified: bool
```

```python
evidence_matches(evidence, request, booking_id, expected_origin)
```

### `OperationResult`

Record fields (including shown defaults; inherited fields also apply):

```python
outcome: Outcome
request: AvailabilityRequest
slots: tuple[Interval, ...] = ()
booking_id: str | None = None
evidence: ConfirmationEvidence | None = None
expected_origin: str | None = None
```

```python
capabilities(**operations) -> Mapping[str, str]
```

### `Dependencies`

Record fields (including shown defaults; inherited fields also apply):

```python
transport: Callable = field(repr=False)
credentials: Callable = field(repr=False)
clock: Callable[[], datetime] = field(repr=False)
contact: Mapping = field(repr=False)
configuration: Mapping = field(repr=False)
evidence: tuple[ConfirmationEvidence, ...] = field(default=(), repr=False)
```

### `Provider`

Record fields (including shown defaults; inherited fields also apply):

```python
capabilities: Mapping[str, str]
```

```python
Provider.availability(self, request: AvailabilityRequest, dependencies: Dependencies) -> OperationResult
```

```python
Provider.book(self, request: BookingRequest, dependencies: Dependencies) -> OperationResult
```

## `library_room_booking.email`

[Source](../python/src/library_room_booking/email.py)

### `MailboxBinding`

Record fields (including shown defaults; inherited fields also apply):

```python
account: str = field(repr=False)
address: str = field(repr=False)
```

### `TrustedProvenance`

Record fields (including shown defaults; inherited fields also apply):

```python
origin: str
sender: str = field(repr=False)
```

### `MailMessage`

Record fields (including shown defaults; inherited fields also apply):

```python
message_id: str = field(repr=False)
recipient: str = field(repr=False)
payload: dict = field(repr=False)
provenance: TrustedProvenance | None = None
```

### `MailError`

Record fields (including shown defaults; inherited fields also apply):

```python
code: str
operation: str
action: str
```

### `LookupResult`

Record fields (including shown defaults; inherited fields also apply):

```python
messages: tuple[MailMessage, ...] = ()
error: MailError | None = None
```

### `GmailConnector`

```python
GmailConnector.profile(self, *, account: str) -> dict
```

```python
GmailConnector.list_messages(self, *, account: str, query: str, page_token: str | None, max_results: int) -> dict
```

```python
GmailConnector.get_message(self, *, account: str, message_id: str) -> dict
```

### `ConnectorFailure`

```python
ConnectorFailure.__init__(self, code: str)
```

```python
lookup_recipient(*, connector: GmailConnector, mailbox: MailboxBinding, recipient: str, max_pages: int=10, max_messages: int=1000, provenance: Callable[[MailboxBinding, str], TrustedProvenance | None] | None=None) -> LookupResult
```

## `library_room_booking.gmail_connector`

[Source](../python/src/library_room_booking/gmail_connector.py)

### `GmailServiceConnector`

```python
GmailServiceConnector.__init__(self, services: Mapping[str, object])
```

```python
GmailServiceConnector.profile(self, *, account: str) -> dict
```

```python
GmailServiceConnector.list_messages(self, *, account: str, query: str, page_token: str | None, max_results: int) -> dict
```

```python
GmailServiceConnector.get_message(self, *, account: str, message_id: str) -> dict
```

## `library_room_booking.libcal`

[Source](../python/src/library_room_booking/libcal.py)

### `Response`

Record fields (including shown defaults; inherited fields also apply):

```python
status: int
url: str
body: str = field(repr=False)
reference: str = 'transport-response'
headers: object = field(default_factory=dict, repr=False)
```

### `LibCalResult`

Record fields (including shown defaults; inherited fields also apply):

```python
detail: str = ''
reference: str | None = None
preparation_attempted: bool = False
submission_attempted: bool = False
```

### `Resource`

Record fields (including shown defaults; inherited fields also apply):

```python
room: Room
name: str
capacity: int
group_id: str
```

### `DiscoveryResult`

Record fields (including shown defaults; inherited fields also apply):

```python
outcome: Outcome
location: Location
resources: tuple[Resource, ...] = ()
detail: str = ''
```

### `PreparedBooking`

Record fields (including shown defaults; inherited fields also apply):

```python
request: BookingRequest
```

### `LibCalAdapter`

```python
LibCalAdapter.__init__(self, *, claim_submission: Callable[[BookingRequest], bool])
```

```python
LibCalAdapter.discover(self, location, dependencies)
```

```python
LibCalAdapter.availability(self, request, dependencies)
```

```python
LibCalAdapter.prepare(self, request, dependencies)
```

```python
LibCalAdapter.submit(self, prepared)
```

```python
LibCalAdapter.book(self, request, dependencies)
```

## `library_room_booking.libcal_evidence`

[Source](../python/src/library_room_booking/libcal_evidence.py)

### `MailText`

```python
MailText.__init__(self)
```

```python
MailText.handle_starttag(self, tag, attrs)
```

```python
MailText.handle_endtag(self, tag)
```

```python
MailText.handle_data(self, data)
```

```python
body_text(payload)
```

```python
stamp(day, clock, zone)
```

### `Receipt`

Record fields (including shown defaults; inherited fields also apply):

```python
evidence: ConfirmationEvidence
state: str
```

```python
parse_receipt(*, payload, subject, sender, authenticated_origin, expected_origin, expected_sender, request, booking_id, library_name, room_name)
```

### `CancellationResult`

Record fields (including shown defaults; inherited fields also apply):

```python
state: str
submission_attempted: bool = False
```

### `LibCalCancellation`

```python
LibCalCancellation.__init__(self, *, claim_cancellation)
```

```python
LibCalCancellation.readback(self, *, receipt, request, booking_id, expected_origin, room_name, dependencies)
```

```python
LibCalCancellation.cancel(self, *, receipt, request, booking_id, expected_origin, room_name, authorized, dependencies)
```
