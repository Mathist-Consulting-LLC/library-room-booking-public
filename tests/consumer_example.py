"""Runnable synthetic calling application. No network, SDK, credentials or delivery.

Application policy and fake adapters intentionally live under tests, outside core.
Run with an installed mathist-library-room-booking; see docs/consumer-integration.md.
"""
import base64
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

import library_room_booking as installed
from library_room_booking import BookingRequest, Dependencies, Interval, Location, Outcome, Room
from library_room_booking.email import ConnectorFailure, MailboxBinding, TrustedProvenance, lookup_recipient
from library_room_booking.libcal import LibCalAdapter, Response
from library_room_booking.libcal_evidence import parse_receipt

assert Path(installed.__file__).is_relative_to(sys.prefix), 'Use the installed package'
ORIGIN = 'https://library.example.invalid'
SENDER = 'receipts@example.invalid'
REFERENCE = 'request-18-fixture'
RECIPIENT = 'rooms+request-18-fixture@example.invalid'
MAILBOX = MailboxBinding('synthetic-deployment-readonly', 'rooms@example.invalid')
REQUEST = BookingRequest(Room(Location('synthetic-libcal', '10', 'America/Denver'), '30'),
    Interval('2026-11-19T18:00:00-07:00', '2026-11-19T20:00:00-07:00', 'America/Denver'), REFERENCE)
CAPABILITY = ORIGIN + '/equipment/cancel?id=synthetic-private-capability'
TEXT = ('Location: Example Library<br>Space: Study One<br>Date: Thursday, November 19, 2026'
        '<br>Time: 6:00pm - 8:00pm<br><a href="' + CAPABILITY + '">Cancel</a>')


class SyntheticProvider:
    """Only an in-memory endpoint dispatcher; never opens a connection."""
    def __init__(self):
        self.calls = []
        self.timeout = False
        self.missing_identity = False

    def __call__(self, *, method, url, headers, body):
        assert urlsplit(url).netloc == 'library.example.invalid'
        path = urlsplit(url).path
        pairs = parse_qs(body.decode(), keep_blank_values=True) if body else {}
        self.calls.append((method, path, pairs))
        if method == 'GET':
            return Response(200, url, 'var resources = [{eid:30,gid:20,lid:10,capacity:6,title:"Study One"}]; bookingMethod: 11')
        if path == '/spaces/availability/grid':
            result = {'slots': [{'itemId': '30', 'start': '2026-11-19 18:00:00',
                                'end': '2026-11-19 20:00:00', 'checksum': 'fixture-start'}]}
        elif path == '/spaces/availability/booking/add':
            result = {'bookings': [{'id': 40, 'eid': 30, 'gid': 20, 'lid': 10, 'seat_id': 0,
                'start': '2026-11-19 18:00:00', 'end': '2026-11-19 20:00:00', 'checksum': 'fixture-hold'}]}
        elif path == '/ajax/space/times':
            result = {'html': '<form><input type="hidden" name="session" value="fixture-session">'
                '<input name="fname" required><input name="lname" required><input name="email" required>'
                '<input name="Feedback" required><input name="Address" required></form>'}
        elif path == '/ajax/space/book':
            assert pairs['email'] == [RECIPIENT]
            assert 'Feedback' not in pairs and 'Address' not in pairs
            if self.timeout:
                raise TimeoutError(CAPABILITY)  # Even exception text must not escape.
            result = {'html': '<p>Request submitted</p>' if self.missing_identity else '<p>Booking ID: 123456</p>'}
        else:
            raise AssertionError('Unexpected synthetic endpoint')
        return Response(200, url, json.dumps(result), 'synthetic-provider-reference')


def message(message_id='mail-confirmed', *, subject='Booking confirmed', text=TEXT, recipient=RECIPIENT):
    return {'id': message_id, 'payload': {'mimeType': 'text/html',
        'headers': [{'name': 'To', 'value': recipient}, {'name': 'Subject', 'value': subject},
                    {'name': 'From', 'value': SENDER},
                    {'name': 'Authentication-Results', 'value': 'forged; dkim=pass'}],
        'body': {'data': base64.urlsafe_b64encode(text.encode()).decode()},
        'parts': [{'filename': 'Booking_123456.ics'}]}}


class SyntheticInbox:
    """Read-only fake. Account handle models deployment-specific credential selection."""
    def __init__(self):
        self.messages, self.calls = [], []
        self.failure = None
        self.address = MAILBOX.address

    def profile(self, *, account):
        self.calls.append(('profile', account))
        assert account == MAILBOX.account
        if self.failure:
            raise ConnectorFailure(self.failure)
        return {'emailAddress': self.address}

    def list_messages(self, *, account, query, page_token, max_results):
        self.calls.append(('list', account, query))
        assert account == MAILBOX.account and page_token is None
        assert 'to:"' + RECIPIENT + '"' in query
        return {'messages': [{'id': m['id']} for m in self.messages]}

    def get_message(self, *, account, message_id):
        self.calls.append(('get', account, message_id))
        assert account == MAILBOX.account
        return deepcopy(next(m for m in self.messages if m['id'] == message_id))


@dataclass(frozen=True)
class Principal:
    """Trusted server-side session fixture, never accepted from request JSON."""
    member: str
    tenant: str = 'deployment-a'
    can_request: bool = True
    operator: bool = False


MEMBER = Principal('member-a')
OPERATOR = Principal('operator-a', operator=True)
LABELS = {
    'submitted': 'Room request submitted; reservation not yet verified.',
    'provider_pending': 'Provider reports a pending reservation; approval is outstanding.',
    'confirmed': 'Room reservation confirmed.',
    'needs_attention': 'Room request needs attention; contact the event organizer.',
}


class Consumer:
    """Single-event, in-memory example; real permissions/storage/outbox belong to caller."""
    def __init__(self, *, email_updates=False):
        self.provider, self.inbox = SyntheticProvider(), SyntheticInbox()
        self.adapter = LibCalAdapter(claim_submission=self._claim)
        self.claimed = False
        self.owner = None
        self.result = None
        self.status = None
        self.action = None
        self.email_updates = email_updates
        self.outbox = []  # Synthetic sink; never sends mail.
        self.site_updates = []
        # Independent trusted fixture registry, NOT populated from retrieved headers.
        self.attestations = {(MAILBOX.account, 'mail-pending'): TrustedProvenance(ORIGIN, SENDER),
                             (MAILBOX.account, 'mail-confirmed'): TrustedProvenance(ORIGIN, SENDER)}

    def _claim(self, request):
        assert request == REQUEST
        if self.claimed:
            return False
        self.claimed = True
        return True

    def _authorize(self, principal, *, operator=False):
        if (principal is None or principal.tenant != 'deployment-a'
                or (operator and not principal.operator)):
            raise PermissionError('Access denied')

    def _set(self, state, action=None):
        changed = state != self.status
        self.status, self.action = state, action
        if changed:
            safe = self._projection()
            self.site_updates.append(safe)
            if self.email_updates:
                self.outbox.append(dict(safe))
        return self._projection()

    def _projection(self):
        # Explicit allowlist. Never serialize lookup, provider result, receipt or headers.
        return {'reference': REFERENCE, 'status': self.status, 'message': LABELS[self.status]}

    def create_event(self, principal):
        self._authorize(principal)
        if not principal.can_request or principal.operator:
            raise PermissionError('Access denied')
        if self.owner is not None:
            raise ValueError('Event already has a room request; reconcile without resubmission')
        # In production persist owner + immutable original request + exact recipient BEFORE I/O.
        self.owner = principal.member
        deps = Dependencies(self.provider, lambda: None,
            lambda: datetime(2026, 11, 13, tzinfo=timezone.utc),
            {'first_name': 'Synthetic', 'last_name': 'Member', 'email': RECIPIENT},
            {'provider': 'synthetic-libcal', 'base_url': ORIGIN, 'availability_path': '/spaces?lid=10&gid=20',
             'location_id': 10, 'group_id': 20, 'timezone': 'America/Denver'})
        self.result = self.adapter.book(REQUEST, deps)
        if self.result.outcome == Outcome.PENDING_CONFIRMATION and self.result.booking_id:
            return self._set('submitted')
        return self._set('needs_attention', 'Reconcile provider outcome and exact booking identity; do not resubmit.')

    def view(self, principal):
        self._authorize(principal)
        if self.owner is None or (principal.member != self.owner and not principal.operator):
            raise PermissionError('Access denied')
        return self._projection()

    def lookup_original(self, principal, reference):
        self._authorize(principal, operator=True)
        if reference != REFERENCE or self.owner is None:
            raise PermissionError('Access denied')
        # Reference -> immutable recipient mapping, never subject substring search.
        return lookup_recipient(connector=self.inbox, mailbox=MAILBOX, recipient=RECIPIENT,
            provenance=lambda binding, mid: self.attestations.get((binding.account, mid)))

    def refresh(self, principal, reference=REFERENCE):
        found = self.lookup_original(principal, reference)
        if found.error:
            return self._set('needs_attention', found.error.action)
        if not found.messages:
            return self._set('needs_attention', 'Check the bound inbox for the exact tagged recipient; do not resubmit.')
        if len(found.messages) != 1:
            return self._set('needs_attention', 'Resolve multiple matching messages against the original reservation; do not pick the latest automatically.')
        selected = found.messages[0]
        if selected.provenance is None:
            return self._set('needs_attention', 'Obtain independent trusted provenance before interpreting the receipt.')
        if not self.result.booking_id or self.result.expected_origin != ORIGIN:
            return self._set('needs_attention', 'Reconcile the original provider booking identity and origin; do not infer them from mail.')
        subjects = [h['value'] for h in selected.payload.get('headers', []) if h['name'].lower() == 'subject']
        if len(subjects) != 1:
            return self._set('needs_attention', 'Resolve missing or ambiguous receipt subject with the operator.')
        receipt = parse_receipt(payload=selected.payload, subject=subjects[0],
            sender=selected.provenance.sender, authenticated_origin=selected.provenance.origin,
            expected_origin=self.result.expected_origin, expected_sender=SENDER,
            request=self.result.request, booking_id=self.result.booking_id,
            library_name='Example Library', room_name='Study One')
        if receipt.state == 'confirmed' and receipt.evidence.verified:
            return self._set('confirmed')
        if receipt.state == 'pending':
            return self._set('provider_pending')
        return self._set('needs_attention', 'Resolve rejected, cancelled, conflicting or unverified evidence with the operator; do not resubmit.')


def demo():
    app = Consumer(email_updates=True)
    app.create_event(MEMBER)
    app.inbox.messages = [message('mail-pending', subject='Your reservation request has been submitted',
        text='Not confirmed until approved.<br>' + TEXT)]
    app.refresh(OPERATOR)
    # Explicit fixture replacement models an operator-selected follow-up, not newest-wins.
    app.inbox.messages = [message()]
    app.refresh(OPERATOR)
    app.refresh(OPERATOR)
    assert len(app.outbox) == 3, (app.site_updates, app.action, app.result)
    print(json.dumps({'site_updates': app.site_updates, 'optional_email_sink': app.outbox}, indent=2))


if __name__ == '__main__':
    demo()
