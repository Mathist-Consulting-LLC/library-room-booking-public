# Reservation lifecycle, recovery and troubleshooting

Save the original immutable room, interval, namespace, attempt reference,
recipient and caller permission before I/O. Discovery/availability observe a
point in time, not a guaranteed reservation. Preparation may create temporary
holds; its failure can leave one outstanding. Final submission consumes the
prepared object, then asks the caller's durable claim before sending. There is
no automatic retry. A denied duplicate claim is unknown_after_submit with no
new submission; a failed claim is failed_before_submit. After any possible
submission, timeout/HTTP failure/malformed response is unknown_after_submit.
Retain the claim and response reference; reconcile exact original identity before
an authorized retry decision. Do not release claims or select a newest booking.

A successful submitted receipt generally returns pending_confirmation. A returned
booking ID does not prove approval. Exact independently trusted confirmation may
produce confirmed. An explicit rejection stays rejected and still needs caller
reconciliation before another attempt. The synthetic consumer projects four
application states: submitted, provider_pending, confirmed, needs_attention.
Those are example application states, not extra provider outcome enum values.

[Receipt parsing](evidence.md) requires exact booking ID, room, interval and
independently attested origin/sender. Headers and cancellation links do not prove
authenticity. Missing, conflicting, duplicate or unfamiliar evidence stays
unverified. Receipt cancellation capability is sensitive and grants no authority.
The separate helper requires explicit authorized=True and durable exact claims,
checks preflight/readback and never submits for ambiguous preflight evidence.
Uncertainty after cancellation POST remains unknown; never automatically replay.
Adapters' unsupported operations must not be inferred from helper existence.

Email may be disconnected with booking submission available. Other trusted exact
evidence is required for confirmation; mail-only updates stay unavailable.
The [email module](email.md) returns either a complete bounded candidate scan or
zero messages plus error. Empty means no match in that scan, not no receipt
anywhere. Profile equality prevents wrong-inbox fallback. Complete tagged
addresses are compared exactly, without case/dot/plus normalization. Neither
routing nor order confirms a booking. The application separately authorizes
operators to access originals and members to request/view rooms. It owns durable
storage, scheduling, notification preferences/outbox and private retention.
Expose safe status projections to members, never full receipts or cancellation URLs.

| Failure/outcome | Recovery owner and action |
| --- | --- |
| Invalid identity/time/configuration | Caller fixes exact namespace/zone/offset; input validation may raise |
| unsupported/manual_only | Choose a supported path or operator workflow; do not invent provider support |
| authentication_required | Caller repairs permitted session/read access; no other-account fallback |
| deferred/unrecognized coverage | Recheck configuration/window/contract; do not claim empty availability |
| unavailable | Choose another interval under caller policy; availability is time-sensitive |
| failed_before_submit | Inspect flags: temporary preparation effects may still remain |
| pending_confirmation | Wait for exact trusted evidence; no duplicate submission |
| unknown_after_submit | Preserve claim and reconcile original provider identity |
| MailError | Use fixed code/operation/action; private connector details remain private |

Mail codes are authentication_required, permission_denied, rate_limited,
connector_failed, invalid_configuration, mailbox_mismatch, invalid_response,
scan_limit, provenance_failed. Lookup bounds default to ten pages/1000 listed
entries, including duplicates; repeated tokens and wrong fetched identity fail.
No automatic request retry occurs. The connector owns per-request deadlines and
limits. Python LibCal grid uses pageIndex=0/pageSize=100 and continuous exact-room
coverage; it has no arbitrary page traversal. JS discovery has bounded detail
traversal and exact-time search, no generic pagination, no hold fallback.

Troubleshoot Python imports in an isolated installed-wheel environment; ensure
IANA timezone data is present on the OS (a caller may install tzdata separately).
JS needs Node >=20 with Intl timezone support and ES modules. Do not resolve a
schema/layout failure by treating unknown markup as empty success or weakening
existing tests. All fixtures establish component behavior only: provider/live,
application HTTP/worker/database and production cycles need separate acceptance.
