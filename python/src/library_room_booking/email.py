"""Optional read-only mail retrieval. No credential discovery or receipt parsing."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from email.utils import getaddresses
import re
from typing import Callable, Protocol


@dataclass(frozen=True)
class MailboxBinding:
    """Caller-owned connector account handle and expected profile address."""
    account: str = field(repr=False)
    address: str = field(repr=False)


@dataclass(frozen=True)
class TrustedProvenance:
    """Attested by the caller, never constructed from message headers here."""
    origin: str
    sender: str = field(repr=False)


@dataclass(frozen=True)
class MailMessage:
    message_id: str = field(repr=False)
    recipient: str = field(repr=False)
    payload: dict = field(repr=False)
    provenance: TrustedProvenance | None = None


@dataclass(frozen=True)
class MailError:
    code: str
    operation: str
    action: str


@dataclass(frozen=True)
class LookupResult:
    messages: tuple[MailMessage, ...] = ()
    error: MailError | None = None


class GmailConnector(Protocol):
    """Implement using already authorized read-only credentials; disable retries.

    Results have Gmail profile/list/full-message JSON shapes. The account handle
    must select the same mailbox for every call; no fallback account is allowed.
    """
    def profile(self, *, account: str) -> dict: ...
    def list_messages(self, *, account: str, query: str,
                      page_token: str | None, max_results: int) -> dict: ...
    def get_message(self, *, account: str, message_id: str) -> dict: ...


class ConnectorFailure(Exception):
    """Connector may classify failures using these fixed, sanitized codes."""
    def __init__(self, code: str):
        self.code = code
        super().__init__('Mail connector failed')


_ACTIONS = {
    'authentication_required': 'Reconnect the configured mailbox with read-only access.',
    'permission_denied': 'Check read-only mailbox permissions.',
    'rate_limited': 'Retry later under caller policy.',
    'connector_failed': 'Check the injected connector and mailbox connection.',
    'invalid_configuration': 'Supply one mailbox binding, exact recipient and positive scan limits.',
    'mailbox_mismatch': 'Bind the connector to the expected mailbox before retrying.',
    'invalid_response': 'Check connector response shape and message identity.',
    'scan_limit': 'Narrow the lookup or explicitly increase caller scan limits.',
    'provenance_failed': 'Check the trusted caller provenance resolver.',
}


def _address(value: object) -> bool:
    # Deliberately narrow addr-spec subset. No Gmail query syntax, normalization,
    # plus-tag splitting, dot folding, case folding or display names.
    return isinstance(value, str) and bool(re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value))


def _recipients(payload: dict) -> set[str]:
    headers = payload.get('headers', [])
    if not isinstance(headers, list):
        raise ValueError
    values = []
    for header in headers:
        if not isinstance(header, dict) or not isinstance(header.get('name'), str) or not isinstance(header.get('value'), str):
            raise ValueError
        if header['name'].lower() in ('to', 'cc', 'bcc', 'delivered-to'):
            if '\r' in header['value'] or '\n' in header['value']:
                raise ValueError
            values.append(header['value'])
    return {address for _, address in getaddresses(values)}


def lookup_recipient(*, connector: GmailConnector, mailbox: MailboxBinding,
                     recipient: str, max_pages: int = 10, max_messages: int = 1000,
                     provenance: Callable[[MailboxBinding, str], TrustedProvenance | None] | None = None) -> LookupResult:
    """Find exact opaque recipients, including tags; all-or-error bounded scan.

    A search hit is only a candidate. Exact header routing is checked locally and
    never authenticates sender/origin. Only a trusted out-of-band caller resolver
    can attach provenance. Results themselves confer no booking authority.
    """
    def fail(code, operation):
        return LookupResult(error=MailError(code, operation, _ACTIONS[code]))

    if (not isinstance(mailbox, MailboxBinding) or not isinstance(mailbox.account, str)
            or not mailbox.account or not _address(mailbox.address) or not _address(recipient)
            or type(max_pages) is not int or max_pages < 1
            or type(max_messages) is not int or max_messages < 1):
        return fail('invalid_configuration', 'configuration')
    operation = 'profile'
    try:
        profile = connector.profile(account=mailbox.account)
        if not isinstance(profile, dict) or not _address(profile.get('emailAddress')):
            return fail('invalid_response', operation)
        if profile['emailAddress'] != mailbox.address:
            return fail('mailbox_mismatch', operation)
        token = None
        tokens, seen, messages = set(), set(), []
        scanned = 0
        for _ in range(max_pages):
            operation = 'list'
            page = connector.list_messages(account=mailbox.account,
                query='in:anywhere {' + ' '.join(
                    f'{name}:"{recipient}"' for name in ('to', 'cc', 'bcc', 'deliveredto')) + '}', page_token=token,
                max_results=min(100, max_messages - scanned))
            if not isinstance(page, dict) or not isinstance(page.get('messages', []), list):
                return fail('invalid_response', operation)
            entries = page.get('messages', [])
            scanned += len(entries)
            if scanned > max_messages:
                return fail('scan_limit', operation)
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not entry['id']:
                    return fail('invalid_response', operation)
                message_id = entry['id']
                if message_id in seen:
                    continue
                seen.add(message_id)
                operation = 'get'
                raw = connector.get_message(account=mailbox.account, message_id=message_id)
                if (not isinstance(raw, dict) or raw.get('id') != message_id
                        or not isinstance(raw.get('payload'), dict)):
                    return fail('invalid_response', operation)
                payload = raw['payload']
                if recipient not in _recipients(payload):
                    continue
                operation = 'provenance'
                trusted = provenance(mailbox, message_id) if provenance else None
                if trusted is not None and (not isinstance(trusted, TrustedProvenance)
                        or not trusted.origin or not _address(trusted.sender)):
                    return fail('provenance_failed', operation)
                messages.append(MailMessage(message_id, recipient, deepcopy(payload), trusted))
            operation = 'list'
            token = page.get('nextPageToken')
            if token is None or token == '':
                return LookupResult(tuple(messages))
            if not isinstance(token, str) or token in tokens:
                return fail('invalid_response', operation)
            tokens.add(token)
            if scanned >= max_messages:
                return fail('scan_limit', operation)
        return fail('scan_limit', 'list')
    except Exception as exc:
        # Do not expose exception bodies, class names, request URLs or chaining.
        if operation == 'provenance':
            return fail('provenance_failed', operation)
        if isinstance(exc, ConnectorFailure) and exc.code in (
                'authentication_required', 'permission_denied', 'rate_limited'):
            return fail(exc.code, operation)
        if isinstance(exc, (ValueError, TypeError, KeyError)):
            return fail('invalid_response', operation)
        return fail('connector_failed', operation)
