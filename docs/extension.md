# Provider extension and application integration

Use exact neutral identities and per-operation capabilities. The Python
`Provider` protocol requires `availability(request,dependencies)->OperationResult`
and `book(request,dependencies)->OperationResult`; discovery may add its own
explicit typed result. In JS use equivalent structural async methods and frozen
neutral factory results. Omitted capabilities are unsupported.

The [runnable workflow](../tests/consumer_example.py) includes
`SimulatedAlternateProvider`. It returns one configured synthetic slot and reports
booking unsupported, without a transport. It demonstrates shape extensibility,
not a second provider implementation. Run it using the quickstart and copy its
example application responsibilities into your own design only after replacing
in-memory state/permissions with real reviewed ownership.

For a separately authorized real adapter: define exact routing/configuration,
provider identifiers, operation effects, authentication, time/bounds and response
contracts; state unsupported operations; distinguish pre-submit failure from
uncertainty; retain caller claim and recovery ownership. Test shared time and
capability fixtures, malformed/partial responses, wrong identities, DST/buffers,
conflicting evidence and no replay from installed artifacts. Never weaken current
LibCal cases to fit another provider. No catalog/borrowing/holds product feature
or additional provider is implemented here.

Booking-specific receipt interpretation stays with Library Tools. Generic service
access stays in [Email Tools](https://github.com/Mathist-Consulting-LLC/gmail-connector-public).
Application permissions, notifications, member updates, persistence and schedules
stay with the consumer. Push retrieval needs a caller-owned authenticated receiver
and independent provenance, not a new trust shortcut in receipt parsing.

After a coordinated repository rename, update clone/build instructions,
cross-repo Gmail setup links, charters, requirements routing and owner-managed
monitor targets. Keep package identities/imports and compatibility wrappers stable.
No automatic monitor or probe is activated by this documentation.
