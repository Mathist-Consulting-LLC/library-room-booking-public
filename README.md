# Library Room Booking

Python and JavaScript interfaces for library room availability and booking. Applications supply provider configuration, authorization, and transport.

## Install from source

Requires Python 3.11 or newer. From the repository root, run `python -m pip install .`.

For JavaScript, use Node.js 20 or newer and run `npm pack --ignore-scripts` in `javascript/`. Install the resulting tarball in your application.

For the optional Gmail integration, build the Gmail Connector and Room Booking wheels into one directory, then run `python -m pip install --no-index --find-links /path/to/wheels "mathist-library-room-booking[gmail]"`. Supply a Gmail service with read access.

## License

[PolyForm Small Business 1.0.0](LICENSE.md). Preserve the [required notice](NOTICE) when redistributing.

## Test the installed packages

In a Python virtual environment, install the build requirements with `python -m pip install --require-hashes -r requirements-build.txt`. Download those same wheels into a local directory with `python -m pip download --require-hashes -r requirements-build.txt -d wheelhouse`. Run `BOOKING_BUILD_WHEELHOUSE=wheelhouse python scripts/check.py` from the repository root. The checks use synthetic requests.
