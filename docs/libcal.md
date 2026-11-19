# Python LibCal mechanics

Callers construct `Dependencies` for each isolated provider session:

- `configuration`: `provider` (exact namespace), `base_url` (HTTPS origin),
  `availability_path`, positive `location_id`/`group_id`, IANA `timezone`,
  and optional `form_values` mapping provider question names to deliberate string
  answers. Caller requests use the exact namespace/location/room IDs and zone.
- `contact`: `first_name`, `last_name`, `email`, `phone`; only required patron
  controls receive those values. Unknown visible required fields block submission
  with field names. Attendance, event name/description, after-hours answers and
  consent (`terms`, usually `"1"`) are caller values, with no inferred defaults,
  RSVP ceiling or room-capacity policy.
- `transport(method=..., url=..., headers=..., body=...) -> Response`: synchronous,
  URL-encoded POST bytes or GET with `body=None`. Response supplies HTTP status,
  final URL, decoded text, a caller-retainable receipt `reference`, and optional
  headers (`Location` for explicit authentication redirects). Transport owns
  session cookies, deadlines, response/resource limits, cleanup and cancellation.
  **Disable automatic redirects and automatic write retries**. The adapter never
  creates a network client, retries or reads environment configuration.
- `credentials`: used only for an encountered login form when `auth_origins`
  explicitly lists approved HTTPS origins. It returns `username` and `password`
  strings. Bounded form login preserves hidden inputs, checks the action before
  credentials, and follows at most three explicit redirects through approved
  origins or the configured provider origin. The booking form must return from
  the provider origin with a session. Unapproved login, SSO/form drift and
  HTTP 401/403 return `authentication_required` before final submission.
- `clock` remains caller-owned; no lead-time/quota/holiday policy is inferred.
  `evidence` retains the existing exact `ConfirmationEvidence` contract.

`discover(location, dependencies)` parses `resources.push({...})` and
`var/let/const resources = [...]` within the configured location and group.
It follows at most one same-origin `/r/new/availability` grid link bound to
the configured location, retaining the configured group. It returns neutral
`Resource` objects with room identity, name, capacity and group.
It does not infer room suitability or select a room. Unrecognized markup is an
explicit failure, not an empty successful discovery.

`availability(request, dependencies)` obtains the session page and the bounded
`/spaces/availability/grid` schedule (`pageIndex=0`, `pageSize=100`), with dates
from the request in its configured timezone, ending on the following local day.
Only continuous green slots of the exact room prove coverage. Explicit red
unavailable/padding overlap means `unavailable`; unfamiliar/missing coverage
fails closed. The provider's `windowEnd=true` with incomplete coverage returns
`deferred`. Provider local timestamps are interpreted in the configured zone,
using UTC for coverage. Spring DST transitions preserve elapsed time. Ambiguous
fall-fold timestamps and nonexistent wall times fail explicitly because this
provider wire format cannot encode an offset. Core contracts still support
explicit-offset folds, setup/cleanup buffers and caller booking windows.

`prepare(booking_request, dependencies)` checks coverage and the start checksum,
adds a temporary booking through `/spaces/availability/booking/add`, updates its
end using `options`/`optionChecksums` when necessary, validates the returned exact
room/location/group/start/end identity and unchanged pending booking ID, then obtains `/ajax/space/times` and
builds the patron payload. `PreparedBooking` snapshots configuration and contacts.
Preparation is **write-capable**, including login and temporary holds. Both
`prepare` and `book` must be excluded from ordinary read-only monitors.
A preparation failure is `failed_before_submit` or `authentication_required`,
with `preparation_attempted=true` if a hold request may have run; a hold can
remain even though no final reservation submission occurred.

The form parser preserves hidden/session and checked defaults, omits optional
visible fields without defaults, ignores disabled/concealed required controls,
and removes class-marked and known honeypots including **Feedback and Address**,
even when marked required in raw markup. Genuine required known patron fields
remain mandatory; unknown visible required fields are actionable drift.
Required radio/checkbox answers must match offered values. Active visible select
controls are unsupported and block preparation before the caller claim; their
options (including disabled options/groups) are not interpreted. Disabled,
concealed and honeypot selects remain omitted. No consent or contact
value is supplied automatically by the package.

Construct the adapter with `claim_submission(request) -> bool`, a caller-owned,
atomic claim for the reservation intent. `submit(prepared)` invokes it after
preparation and immediately before `/ajax/space/book`. The caller must deny
already submitted, in-flight or unresolved intents, including changed attempt
IDs and across processes/restarts. The package does not replace durable claims.
A prepared object is consumed once under a lock, including failed/denied claims;
repeat use cannot send a second request. `book(request, dependencies)` composes
prepare and submit. A repeated `book` may create a new temporary hold before the
caller claim denies submission; callers should gate unresolved intents before
preparation as well. Claims, hold expiry and reconciliation remain caller-owned.

A timeout, invalid response, HTTP/auth change or transport exception after final
submission starts returns `unknown_after_submit`, preserving the configured origin
and any received response reference even when status or parsing fails. A transport
exception before a response can leave the reference absent. Explicit provider `error`
returns `rejected`, with no retry. The caller must reconcile before deciding any
new reservation attempt. A recognized submission receipt returns
`pending_confirmation`, with exact request, provider origin, explicit booking ID
when unique, receipt reference and attempt flags. Generic success words and
cancellation URL tokens never become booking IDs. Conflicting IDs stay unverified.
`confirmed` additionally requires exactly one caller-verified evidence item
matching the exact booking ID, request (including attempt, room and interval)
and provider origin. The adapter does not authenticate mail or infer exact
reservation ownership from a generic success page.

Unsupported: automatic endpoint/group discovery beyond resource markup and the bounded grid link, closure
calendars, interactive SSO/CAPTCHA, new patron question schemas, pagination beyond
the bounded grid, ambiguous provider wall times, modification, cancellation,
standalone confirmation/readback and evidence reconciliation. Required-field
and markup drift produce an explicit diagnostic rather than guessed behavior.
Authentication form support requires caller approval of origins and injected
credentials/session; no real credentials or live requests are part of validation.

The calling application retains eligibility, ranking/selection, quotas,
holidays, attendance policy, durable claims, recovery matching, persistence,
permissions and cancellation authority. Consumer adoption, composed HTTP/worker/
database recovery and live compatibility require separate acceptance.

`tests/libcal_contracts.py` runs against the actual installed adapter in both
wheel and rebuilt-sdist consumers via `scripts/check.py`, with synthetic URLs,
contacts and login values only. It verifies provider request bodies and effects,
malformed data, auth drift, form drift, exact evidence, DST, timeout after provider
success and duplicate submissions within and across adapters using a caller ledger.
