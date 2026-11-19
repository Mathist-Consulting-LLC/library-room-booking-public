# Room booking API contracts

[Python signatures and dataclass fields](python-api.md) list exact constructor
arguments, defaults and method parameters. Core imports come from
`library_room_booking`; adapters/evidence/mail are explicit submodule imports.
Python records are frozen; JavaScript factory records and result arrays are
frozen copies. No callback is invoked by neutral model construction.

| Surface | Inputs and outputs | Implemented languages |
| --- | --- | --- |
| Location, Room | Exact provider namespace, external location/room ID, named timezone | Python/JS |
| Interval | Start/end strings with explicit offset valid in IANA timezone | Python/JS |
| AvailabilityRequest | Exact room and bounded interval in location zone | Python/JS |
| BookingRequest | Availability fields plus caller `attempt_id` / `attemptId` | Python/JS |
| OperationResult | Outcome, request, slots, optional booking ID/evidence/expected origin | Python/JS |
| ConfirmationEvidence | Original request, booking ID, origin, reference, verified flag | Python/JS |
| Dependencies | Transport, credentials, clock, contact, configuration, evidence | Python; structural caller object in JS |
| LibCal discovery | Exact configured Location -> DiscoveryResult with resources | Python/JS |
| LibCal availability | AvailabilityRequest -> result with slots or explicit failure | Python/JS |
| LibCal prepare/submit/book | BookingRequest -> PreparedBooking or LibCalResult; submit consumes prepared attempt | Python only |
| Receipt parsing, exact cancellation helper | Explicit selected MIME evidence/original identity -> Receipt or CancellationResult | Python only |
| Optional email lookup | Bound mailbox/exact tagged recipient -> LookupResult | Python only |

`OperationResult` may return `available`, `unavailable`, `unsupported`,
`manual_only`, `authentication_required`, `deferred`, `pending_confirmation`,
`confirmed`, `rejected`, `failed_before_submit`, `unknown_after_submit`.
Only available results carry slots, all within the request. Confirmed results
require exact matching verified evidence. `LibCalResult` adds safe `detail`,
private `reference`, `preparation_attempted` and `submission_attempted` flags.
`DiscoveryResult` has outcome/location/resources/detail; each `Resource` has
room/name/capacity/group ID. A provider attempt ID is correlation, not durable
idempotency. The caller owns atomic cross-process claims.

`capabilities(**operations)` defaults every omitted operation to `unsupported`.
Each of discovery, availability, booking, confirmation, modification, cancellation
has its own supported/unsupported/manual_only/authentication_required value.
Python LibCal advertises discovery/availability/booking; JS advertises only
discovery/availability for valid configurations. Confirmation/modification/
cancellation are unsupported on these adapters. The separately constructed
[Python cancellation helper](evidence.md) has an explicit authorization contract;
its existence does not change the neutral adapter's advertised capabilities.

## Time and exact identity

Do not normalize external IDs, infer names, substitute rooms or reuse namespaces
across colliding tenants. Bind configuration to exact location/room and timezone.
Intervals need a positive duration and explicit valid offset; a DST fall fold
must select an offset, and a spring gap or offset mismatch is invalid.
`Interval.bounds()` returns UTC datetimes; `buffered_interval(i,setup,cleanup)`
returns UTC bounds; `within_window(i,window,setup_minutes=0,cleanup_minutes=0)`
checks inclusive occupied bounds. Buffers must be nonnegative whole minutes.
A caller computes booking windows, quotas and lead times; core has no such policy.

JS uses `location(provider,locationId,timezone)`, `room(location,roomId)`,
`interval(start,end,timezone)`, `availabilityRequest(room,interval)`,
`bookingRequest(room,interval,attemptId)`,
`confirmationEvidence(request,bookingId,origin,reference,verified)`,
`operationResult(outcome,request,{slots=[],bookingId=null,evidence=null,expectedOrigin=null}={})`,
`capabilities(operations={})`, `evidenceMatches(evidence,request,bookingId,expectedOrigin)`,
`instant(value,timezone)`, `bufferedInterval(value,setupMinutes=0,cleanupMinutes=0)`
and `withinWindow(value,window,setupMinutes=0,cleanupMinutes=0)`.
`instant` returns milliseconds; buffer bounds are millisecond numbers, not
Date objects. String subset: ISO seconds with Z or numeric offset; Python also
accepts datetime.fromisoformat forms. Invalid JS inputs throw TypeError (bad
Intl zones can throw RangeError); Python validation can raise ValueError or
ZoneInfoNotFoundError. Structural providers may be asynchronous in JS.

Read [Python LibCal mechanics](libcal.md), [JavaScript specifics](javascript-libcal.md),
[email lookup](email.md), [evidence](evidence.md), [setup](setup.md) and
[recovery](recovery.md). [Shared time fixtures](../contracts/time.json) and
[provider configurations](../contracts/providers.json) are synthetic contracts.
