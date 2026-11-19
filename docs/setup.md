# Configuration, transport and authorization

Start with the [quickstart](quickstart.md). No provider account is needed for
bundled examples. A live integration must obtain permission from its provider,
verify site-specific rules, and supply verified configuration/contact data.
This package registers no provider app, chooses no library and stores no secret.

Python: construct `LibCalAdapter(claim_submission=atomic_callback)` and pass
`Dependencies(transport, credentials, clock, contact, configuration, evidence=())`
for each isolated provider session. A claim must persist across crashes/workers
and return literal True only for a permitted new exact request. See
[LibCal configuration fields](libcal.md) and [record definitions](python-api.md).

`configuration` requires exact `provider` namespace, HTTPS `base_url`,
`availability_path`, positive `location_id`/`group_id`, and IANA `timezone`.
Optional `form_values` deliberately supplies attendance/consent/provider question
strings; no application defaults are inferred. `contact` has first_name,
last_name, email, phone. Unknown genuine required form fields block submission;
Address/Feedback anti-spam traps are omitted even when marked required.

`transport(method=...,url=...,headers=...,body=...) -> libcal.Response` receives
GET with body=None or URL-encoded POST bytes. Return exact HTTP status, final URL,
decoded body string, optional private receipt reference and response headers.
Keep cookies in the caller's isolated session. Enforce TLS, exact configured
origins, response/decompression/body bounds, deadlines and cleanup before returning.
Disable automatic redirects and all automatic write retries. Explicit permitted
auth redirects are checked by the adapter (at most three). Python callbacks have
no implicit timeout/cancellation; a blocking callback blocks the method.

`credentials()` is consulted only for supported login forms at explicitly
configured `auth_origins`; return username/password strings privately. The action
origin is checked before credential acquisition. Unsupported SSO or missing
booking session returns authentication_required. Configure identity through the
caller; credentials do not authorize a booking and should never be printed.
The cancellation helper accepts only its exact configured provider origin.

For a read-only integration call discover/availability only. `prepare`, `submit`
and `book` are write-capable; preparation can create temporary holds before the
final atomic submission claim. Do not call them as probes. The full offline
consumer supplies a local dispatcher showing every required request/response;
replace it with your own constrained session only after independent authorization.

JavaScript: import `createLibCalAdapter` from
`@mathist/library-room-booking/libcal`, inject `fetch` and explicit
configuration. It expects a standard Response stream, content headers, status,
ok, redirected and URL. Requests are GET with manual redirects, omitted
credentials and AbortSignal. Only configured HTTPS `*.libcal.com` tenant origins
and supported read paths are accepted. It cannot login or submit. Full option
names, limits and supported layouts are in [the JS guide](javascript-libcal.md).

## Optional Gmail composition

The booking package and fixtures install without Gmail. For the optional extra,
build the current [Email Tools](https://github.com/Mathist-Consulting-LLC/gmail-connector-public)
wheel and booking wheel into the same wheel directory, then in your consumer:

```sh
"$PIP_PYTHON" -m pip --python "$PYTHON" install --no-index --find-links "$WHEELS" 'mathist-library-room-booking[gmail]==0.0.0.dev1'
"$PYTHON" -I -c 'import pathlib,sys,mathist_gmail_connector as p; assert pathlib.Path(p.__file__).is_relative_to(sys.prefix); print("installed Gmail connector")'
```

`PIP_PYTHON` and `PYTHON` retain the quickstart provisioning and target interpreters.
Expected readback: `installed Gmail connector`.
`WHEELS` must be an absolute directory containing both built wheels. The extra
requires `mathist-gmail-connector==0.0.0.dev1` but adds no SDK/credentials.
The preserved `library_room_booking.gmail_connector.GmailServiceConnector`
uses the installed standalone connector when present and the bundled compatible
read shim otherwise. Both use caller-created authorized service mappings with
explicit account selection, `execute(num_retries=0)` and no fallback. Supply
read-only credentials, bounded HTTP, refresh owner and safe exception handling;
[Email Tools setup](https://github.com/Mathist-Consulting-LLC/gmail-connector-public/blob/main/docs/setup.md)
explains that caller contract. No live mail access is needed to validate this seam.
