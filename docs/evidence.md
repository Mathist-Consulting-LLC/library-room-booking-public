# Python receipt evidence and cancellation helper

## Pure receipt parsing

`parse_receipt` accepts a supplied MIME tree (`mimeType`, base64url `body.data`,
`parts`, `filename`), subject, sender, `authenticated_origin`, `expected_origin`,
`expected_sender`, exact request/booking ID and exact library/room display names.
The caller authenticates mail provenance independently and passes the approved
origin and sender. A From header, subject, link or attachment name proves no
source authenticity. Payload headers are ignored. Callers select evidence and
resolve mailbox or reservation matches; the library searches neither.

The supported standard Location/Space/Date/Time and compact receipt templates
are extracted from the source. Timezone comes from the request, never a global
library default. Missing, multiple, conflicting or unfamiliar records remain
unverified. MIME alternatives must agree. Display names compare exactly; caller
mapping binds these names to neutral provider/location/resource IDs. The full
interval is compared as UTC instants with valid zone offsets. Pending, rejected,
cancelled, confirmed and unverified states remain distinct. Only `confirmed`
receipts carry `evidence.verified=True`, so pending evidence cannot confirm a
booking through the existing neutral API.

Receipt parsing consumes the complete body as one standard or compact record,
complete supported status statements, and supported cancellation controls. Status
statements must agree with the complete recognized subject. Additional records,
unrecognized prose or time syntax, and conflicting status statements remain
unverified, including in MIME alternatives. Time fields must contain one complete
range; identical repeats and mixed standard/compact records remain unverified.
Unsupported approval wording cannot establish confirmation or a capability.
Named reservation status statements in subjects and bodies must use the exact
caller-supplied library name and supported wording. Library names are matched
literally; additional approval prose cannot become part of a name wildcard.

ICS support is **attachment filename identity only**, `Booking_<digits>.ics`,
as implemented in the original. Neither source parses ICS VEVENT/UID/body data.
ICS event interpretation is unsupported; filenames alone cannot verify a booking.

`Receipt.evidence` is neutral, uses a fixed safe reference, and contains no
capability URL. One exact same-origin cancellation capability may remain in a
private, repr-hidden receipt field for immediate use. Do not serialize the entire
receipt (including dataclass introspection), request payloads or transport objects.
Retain only neutral evidence if persistence is needed. No persistence occurs by
default. Raw receipt text, links, response bodies and exception messages are
never returned in parser results or logged by this module.

## Injected operations and caller authority

Construct `LibCalCancellation(claim_cancellation=callback)`. `readback` and
`cancel` take `receipt`, exact `request`, `booking_id`, `expected_origin`,
`room_name` and `dependencies`. `cancel` additionally requires `authorized=True`.
The caller supplies the original reservation's identity and configuration,
including the display-name mapping; occurrence changes must not replace it.
Configuration must match the exact neutral provider, location and timezone.

Readback returns `active`, `cancelled` or `unverified`. Terminal readback follows
the source's one exact booking container with no active controls/endpoints; it
is bound to the already verified receipt interval and room. Identity-less prose
cannot prove cancellation. The cancel path reads the page, reopens and rechecks
room/interval/booking and the page-authored single endpoint, then claims the
operation before POST. It never calls cancel-all or invents a missing endpoint.
An already cancelled exact reservation needs no claim or POST.
Terminal text must be one complete supported cancellation or missing-booking
statement. Conditional language, corrections and additional prose remain
unverified before submission and produce `unknown` after a possible POST.

Active-page validation preserves HTML field boundaries inside the exact booking
container. The whole container must contain the exact room field, one dated
field with a fully recognized exact time range, and an optional Cancel Booking
control. Extra undated reservation fields, unfamiliar text, multiple ranges or
missing times fail both initial and reopened preflight, before any claim or POST.
Help hours cannot supply a missing reservation interval. New layouts that separate
the date and time into unfamiliar fields remain unverified.
Decoded text is preserved when validating timing and terminal statements;
escaped angle-bracket content cannot disappear through a second markup strip.

The callback receives neutral evidence and must atomically authorize/claim the
exact provider/location/room/interval/booking/origin across processes and restarts.
Return literal `True` only for a new permitted attempt. The library's in-memory
lock also prevents repeated POSTs for the same identity on one client. Durable
claims, permissions, claim storage and recovery belong to the caller.

Cancellation reports `cancelled` only after successful JSON and exact provider
readback (or already-cancelled readback). Timeout, malformed response, failed
readback, redirect and unexpected provider result after possible POST produce
`unknown` with `submission_attempted=True`; never replay or clear the durable
claim automatically. `unverified`, `authority_required` and `claim_denied` do
not submit. Diagnostic errors are generic and never expose transport exceptions.

The existing transport contract applies: the caller owns session cookies,
deadlines, response-size limits and redirect prevention. It must also disable
request retries, including hidden retries after an uncertain POST. Injected
transport is trusted with capability URLs; it must redact URLs, bodies, headers
and exceptions in its own logs and storage. Only configured HTTPS origin/path
responses are accepted. No extra auth origin is permitted for cancellation.
