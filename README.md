# Library Room Booking

Python and JavaScript interfaces for library room availability and booking. Applications supply provider configuration, authorization, and transport.

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
