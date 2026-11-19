# JavaScript LibCal discovery and availability

The package exports `createLibCalAdapter` from
`@mathist/library-room-booking/libcal`, separately from the unchanged neutral
factories. The package owner is library-room-booking; callers own configuration,
transport and all application state. It has no runtime dependencies, service,
monitor, provider inventory, browser session or write operation.

```js
import {createLibCalAdapter} from '@mathist/library-room-booking/libcal';
const adapter = createLibCalAdapter({
  fetch: injectedFetch,
  configuration: {
    provider: 'libcal', namespace: 'synthetic-alpha',
    bookingUrl: 'https://synthetic.libcal.com/spaces?lid=41&gid=51',
    allowedOrigins: ['https://synthetic.libcal.com'],
    locationId: '41', groupId: '51', timezone: 'America/Denver'
  },
  timeoutMs: 5000, maxBytes: 524288, maxRooms: 20
});
// await adapter.discover(neutralLocation)
// await adapter.availability(neutralAvailabilityRequest)
```

All identifiers above are synthetic. `provider` selects the adapter kind and
must remain `libcal`; `namespace` supplies the neutral location's `provider`
value (for example `synthetic-alpha`). Discovery and availability compare the
complete neutral location, including this namespace, and return the exact
requested identity. Use different namespaces for tenants/configurations whose
location and room IDs can collide. The caller owns namespace uniqueness: the
adapter cannot distinguish two configurations deliberately assigned the same
namespace, location ID and timezone. Origins and group IDs are routing metadata,
not additional neutral identity fields. Changing routing while reusing that
identity therefore requires caller care.

For compatibility with existing shared fixtures, omitting `namespace` defaults
to `libcal`. This legacy default does **not** isolate colliding tenant IDs;
configure an explicit distinct namespace before combining such tenants. An
explicit empty, null, non-string or padded namespace is rejected.

 Configured IDs are exact positive decimal
strings; configuration is snapshotted. Unknown providers advertise unsupported
capabilities and make no request. Malformed LibCal configuration throws before
transport. Discovery/availability require the exact configured neutral location;
other locations return `unsupported`. Invalid neutral requests throw. No fallback
to environment, global fetch, default timezone, catalog or fuzzy name occurs.

Only configured HTTPS LibCal tenant origins are permitted. `bookingUrl` paths are
`/spaces`, `/space/<id>`, `/r/search`, or `/reserve/spaces/<slug>`; only known
read-only search query keys are accepted. Availability uses the reserve search
path or `/r/search` and supplies the configured location/group and local interval.
Discovery may GET the configured page, one same-origin search listing, and at
most `maxRooms` exact `/space/<id>` details. There are no booking, hold, login,
submission, modification or cancellation methods. Native fetch options use GET,
`redirect: 'manual'` and `credentials: 'omit'`, with no body or retries. The injected
fetch must honor that contract, avoid hidden redirects/retries and supply standard
Response streams; it owns DNS/egress and any stronger connection restrictions.
The package does not claim to police the internals of caller code.

A single deadline includes fetch, body reads and the entire discovery traversal.
An AbortController plus a deadline race bounds even a stalled injected promise.
The byte budget is cumulative over all response bodies, checked before decoding
and against supplied Content-Length. Streams are cancelled on completion/failure;
cleanup is not awaited beyond the deadline. Defaults above have hard caps of
30 seconds, 2,000,000 bytes and 20 rooms. No response.text/Buffer/eval is used.

Discovery interprets the source's `resources.push({...})` and resource arrays,
including escaped Unicode titles. Resources contain neutral `room`, `name`,
`capacity` (or null) and `groupId`. Provider location/group and detail room IDs
must match exactly, including a directly configured `/space/<id>` page (one
resource with that exact requested ID). The alternate search layout must select exactly one positive
configured group and matching location. Missing/malformed resources and conflicting
identities fail explicitly. Numeric resource fields (`eid`, `id`/`eid_` alias,
`lid`, `gid`, `capacity`) require complete decimal tokens, quoted or unquoted;
fractions, exponents, signs, suffixes and invalid aliases cannot substitute an
identity. If both room aliases occur, both must be valid and agree. Capacity
is optional, zero maps to null, and supplied values must be safe nonnegative
integers. Numeric URL/form/listing/search fields are validated in full as well;
malformed results invalidate the response even alongside a valid match.
No category, eligibility or ranking is inferred.

Availability returns the existing neutral `operationResult` plus `detail`.
Only exact numeric room IDs inside the exact-time results section prove full
requested coverage; other-time suggestions and room-name matches cannot do so.
An explicit no-results message or exact results for other IDs yields `unavailable`.
Both filter and exact/other-results markers are required; unfamiliar/empty/partial
markup returns `deferred`, `detail: 'unrecognized_markup'`, with no slots.
Failures use `deferred` plus stable diagnostics (timeout, response_too_large,
redirect_rejected, content_type, http_failure, identity mismatch or malformed
response/transport); HTTP 401/403 or a password control returns
`authentication_required`. Raw errors, markup, URLs and credentials are not echoed.
Discovery uses the analogous frozen `{outcome, location, resources, detail}` shape.
These diagnostics extend provider results without adding neutral outcome values.

The search wire format represents same-local-day, whole-minute wall times.
Cross-midnight, subminute, offset-changing DST intervals and ambiguous fold
endpoints return `unsupported_interval` without transport. This conservative
boundary cannot prove those intervals through offset-free public search; it does
not weaken the neutral contracts, which still support explicit-offset DST folds,
spring transitions, buffers and booking windows. Invalid offsets/nonexistent
local times are rejected by the neutral factory. Ordinary dates before/after DST
are supported. Grid scheduling/coverage and hold preparation remain Python
mechanics; this adapter does not invent a grid or hold fallback.
