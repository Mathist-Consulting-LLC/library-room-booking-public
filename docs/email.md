# Optional booking email interpretation

Use `library_room_booking.email.lookup_recipient` with an injected connector
implementing the profile/list/get protocol in [Python API](python-api.md).
Bind `MailboxBinding(account, address)` to one dedicated caller-owned inbox.
Results are `LookupResult(messages=tuple[MailMessage], error=MailError|None)`.
[Email Tools](https://github.com/Mathist-Consulting-LLC/gmail-connector-public)
provides the optional generic Gmail service adapter; the extra is never required
for booking or the fixture examples. The compatibility wrapper is
`library_room_booking.gmail_connector.GmailServiceConnector` and translates its
failure type to the booking email interface.

Profile address equality is exact and checked before search. Bind each mailbox
separately; there are no personal/business names, domains or mailbox defaults.
The recipient is an opaque addr-spec, including its complete plus tag. The module
never strips tags, folds dots, changes case or performs substring matching. It
supports a deliberately narrow unquoted ASCII address syntax; display names,
whitespace and query operators in the lookup input are rejected. Gmail search
uses quoted recipient operands across To/Cc/Bcc/Delivered-To; every returned
candidate is checked again against parsed complete routing addresses in those
headers. Subject/body/From matches do not count. Missing routing evidence yields
no match. Search indexing/provider behavior can omit candidates; empty output
proves only that this bounded scan found no exact match.

The scan deduplicates message IDs, bounds pages and listed entries (including
duplicates), rejects repeated page tokens, and checks fetched identity. Any error
returns zero messages so incomplete scans cannot masquerade as complete results.
Defaults are 10 pages and 1000 listed entries. The caller decides recovery and
whether to increase those limits; there is no automatic retry.

## Provenance and privacy

Routing headers, From, Authentication-Results, subjects, links and attachment
names are untrusted data. They never establish source authenticity. By default
every returned message has `provenance=None`. An optional trusted caller callback
`provenance(mailbox_binding, message_id)` may return `TrustedProvenance(origin,
sender)` or `None`. It receives only the bound mailbox and message identity;
it must obtain its attestation independently from a trusted boundary. Never
implement it by copying values from the retrieved headers or parsing a link.
The type is an explicit trust assertion by the caller, not cryptographic proof.
A callback failure aborts the scan with `provenance_failed`.

Payloads are retained as untrusted MIME trees for caller use, copied away from
connector data and hidden from repr. They may contain private text or capability
URLs: do not serialize or log complete results or dataclass internals. No receipt
parsing or confirmation is triggered by retrieval. An explicitly selected message
may be passed to the separate `libcal_evidence.parse_receipt` only under that
module's exact booking and trusted-origin contract. Retrieval alone confers no
booking match, confirmation or cancellation permission.

Errors expose fixed codes, operation (`configuration`, `profile`, `list`, `get`,
`provenance`) and useful fixed recovery text. Connectors may raise
`ConnectorFailure` with `authentication_required`, `permission_denied` or
`rate_limited`. Other exceptions become generic sanitized errors; exception text,
URLs, provider bodies and unknown codes never reach the result or library logs.
Connectors and callbacks must redact their own logs. Raw payloads and trusted
attestations remain caller-controlled private data.


## Alternate retrieval or push delivery

Implement `profile(*,account)`, `list_messages(*,account,query,page_token,max_results)`
and `get_message(*,account,message_id)` with Gmail-compatible dictionaries for
this lookup protocol. The caller owns service limits, deadlines, refresh,
resource cleanup and retries. Another provider's query language needs an explicit
translation at that boundary; the booking lookup currently emits Gmail query
syntax. No alternate mailbox or push implementation is bundled.

For push delivery, the application owns the authenticated receiver, account
isolation, deduplication, bounded MIME retrieval and original identity. Pass only
an explicitly selected payload plus independently trusted provenance to receipt
verification. Delivery order and routing matches confer no authority.

Email may remain disconnected. Submission still works; confirm only with other
exact trusted evidence. Email-only updates remain unavailable. API search and
follow-up approval are distinct evidence stages; fixtures establish neither live
delivery nor production adoption. Applications own operator permissions and
private original-message access; member updates must use safe projections.
