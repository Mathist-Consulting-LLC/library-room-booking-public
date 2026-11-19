# Library Tools

The existing room-booking component includes neutral contracts, LibCal adapters and booking-specific email interpretation. General Gmail service access belongs to [Email Tools](https://github.com/Mathist-Consulting-LLC/gmail-connector-public).

Start with the [developer guide](docs/README.md) for installation, runnable offline examples and API contracts. See the [component map](docs/component-charter.md) and [requirements](requirements/README.md).

Find available library rooms and submit reservation requests from your own software. This library handles the room-booking part of a larger application. The application supplies the meeting details, user permissions, and status display.

## What is LibCal?

LibCal is software from Springshare that libraries use for services including room and seat reservations. A library can use it to publish available spaces, accept reservation forms, and apply its own booking rules. You may encounter a LibCal booking page when following a library website's “Reserve a room” link. See [Springshare's LibCal overview](https://www.springshare.com/libcal).

This project provides adapters for supported LibCal room-booking flows. Its common room and reservation types also provide a place to add other booking systems.

## Why this project exists

The booking code began inside a calendar application that needed to reserve library rooms for scheduled gatherings. Extracting it into a library lets another application reuse the provider integration while choosing its own event model, interface, credentials, and operating rules.

For an organizer, the underlying task is straightforward: find a room for a particular time and request it. For software, that involves reading provider-specific availability, sending the right reservation form, interpreting the response, and tracking whether the library has approved the request. This package gives those steps explicit inputs and outcomes that an application can test and act on.

## How reserving a room works

Imagine an application needs a room for a two-hour gathering. It can use this library in the following workflow.

1. Discover the configured library's rooms and their provider identifiers.
2. Check a selected room's availability for the requested time.
3. Through the Python LibCal adapter, submit the reservation form with the caller's contact information.
4. Read the submission outcome and retain the provider booking identity.
5. If approval is required, keep the request pending until matching evidence establishes approval.

Availability can change between checking a room and submitting a request. A submission can await staff approval, and a network failure can leave the submission outcome unknown. The calling application must retain its request and reconcile an uncertain result before deciding whether to retry.

Optional Python email helpers can look up receipts and check evidence against the original reservation. When email is disconnected, the application needs another supported verification method or manual review to establish approval. The application owns persistent records, notifications, and user-facing status.

## When would you use it?

Use this package when room reservations need to fit into your application's workflow, such as showing availability in an organizer dashboard or requesting a room for an existing calendar entry. It supplies reusable provider parsing, room and time contracts, and explicit results for availability and reservation attempts.

The calling application manages events, meetings, or study sessions. This library receives the room and time request and handles the supported provider interaction. It can also be used by a small script that only checks room availability.

For a code reviewer, the project demonstrates extracting an external-service integration into a reusable component, keeping application policy with the caller, reporting provider capabilities explicitly, and testing failure and recovery behavior at the transport boundary.

## What can it do today?

The Python LibCal adapter supports discovery, availability, and booking submission. The JavaScript adapter supports discovery and availability. Your application supplies site configuration, transport, contact information, and any required authorization. Each library can have its own booking rules and approval process.

The provider interface supports additional booking systems with their own capabilities. The included alternate provider is a simulation that demonstrates availability-only support. Real non-LibCal providers require their own adapters and validation.

## Try the workflow

The [offline consumer example](tests/consumer_example.py) walks through submission, a pending receipt, a simulated approval, and recovery after a lost response. It also demonstrates the alternate provider. All responses in that example are synthetic. A separate live approval-email test remains pending.

## Install from source

Requires Python 3.11 or newer. From the repository root, run `python -m pip install .`.

For JavaScript, use Node.js 20 or newer and run `npm pack --ignore-scripts` in `javascript/`. Install the resulting tarball in your application.

For the optional Gmail integration, build the Gmail Connector and Room Booking wheels into one directory, then run `python -m pip install --no-index --find-links /path/to/wheels "mathist-library-room-booking[gmail]"`. Supply a Gmail service with read access.

## Provider support

| Operation | Python LibCal adapter | JavaScript LibCal adapter |
| --- | --- | --- |
| Discovery and availability | Supported | Supported with valid site configuration |
| Booking submission | Supported | Unsupported |
| Confirmation, modification, and cancellation | Unsupported as adapter operations | Unsupported |

A successful submission can remain pending. The Python email helpers offer optional evidence lookup. The caller supplies mailbox access and verifies the evidence origin and exact booking identity before treating the booking as confirmed. Review the [consumer example](tests/consumer_example.py) and [email contract checks](tests/email_contracts.py) for offline examples.

For another booking provider, implement the [provider interface](python/src/library_room_booking/__init__.py) or equivalent [JavaScript contracts](javascript/src/index.js). Advertise capabilities per operation and return explicit outcomes. Use the provider's stable location and room IDs, with timestamps that include an offset valid for the location's timezone. Supply transport, credentials, and configuration through the consumer. The [provider fixtures](contracts/providers.json) illustrate synthetic LibCal site configurations.

To run the synthetic example after installing the Python package, run
`python tests/consumer_example.py`. It demonstrates a LibCal submission,
a pending receipt, a matching approval, and a lost submission response. After
a lost response, the caller retains its claim and waits for reconciliation
of the original booking identity. The example also shows an availability-only
simulated alternate provider. All provider and inbox responses are fixtures.

## License

[PolyForm Small Business 1.0.0](LICENSE.md). Preserve the [required notice](NOTICE) when redistributing.

## Test the installed packages

In a Python virtual environment, install the build requirements with `python -m pip install --require-hashes -r requirements-build.txt`. Download those same wheels into a local directory with `python -m pip download --require-hashes -r requirements-build.txt -d wheelhouse`. Run `BOOKING_BUILD_WHEELHOUSE=wheelhouse python scripts/check.py` from the repository root. The checks use synthetic requests.
