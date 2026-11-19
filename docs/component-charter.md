# Library Tools component charter

Owner: Mathist Consulting LLC maintainers. Repository: `library-room-booking-public`.
The current repository name and URLs remain in use pending coordinated mapping.
Package names and imports stay unchanged. Retaining the current directory layout
avoids a migration with no functional benefit.

| Area | Responsibility | Boundary |
| --- | --- | --- |
| `python/src/library_room_booking` | Existing Python component | Public API reference and synthetic contracts |
| `javascript/src` | Existing JavaScript component | Narrower capabilities; see JavaScript guide |
| `requirements` | Source-backed acceptance and explanations | JSON is authoritative; protected originals retain provenance |
| `docs`, `examples`, `tests` | Consumer instructions and offline evidence | Fixtures do not prove provider compatibility |

Room booking owns exact neutral room/time identities, explicit operation
capabilities, LibCal parsing, optional mailbox retrieval composition and receipt
verification. Gmail access is replaceable and independently packaged in
[Email Tools](https://github.com/Mathist-Consulting-LLC/gmail-connector-public).
The adapter and evidence cancellation helper have different capabilities: the
neutral LibCal adapter advertises no cancellation operation; a separately
constructed cancellation helper can perform an explicitly authorized operation.
Callers own trusted provenance, durable claims, membership/booking policy,
permissions, scheduling, persistence, notification preferences and delivery.
Direct consumers are applications/scripts; their workers, storage and UI are
indirect consumers needing their own composed acceptance. Trace `LRB-*` through
transport, exact receipt binding and installed contract/consumer tests.
No monitor is activated. Discovery/availability are read operations; preparation
may create temporary holds and must never be used as a read-only probe.

Expansion point: implement the documented provider protocol with explicit
capabilities and isolated contract cases after separate authorization. The
alternate provider example is simulated. Catalog, borrowing and holds product
features are not implemented.

Read [API](api.md), [setup and transport](setup.md), [recovery](recovery.md) and
[validation](validation.md). Acceptance and authorization are separate from
capability detection. Review changes against the original accepted baseline and
actual final diff; preserve all negative tests and state evidence limits.
