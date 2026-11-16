"""Synthetic tests run against installed public modules by scripts/check.py."""
import base64
from dataclasses import replace
from datetime import datetime, timezone
import unittest
import pathlib
import sys
import library_room_booking.libcal_evidence as installed
assert pathlib.Path(installed.__file__).is_relative_to(sys.prefix), installed.__file__
from library_room_booking import BookingRequest, Dependencies, Interval, Location, Room
from library_room_booking.libcal import Response
from library_room_booking.libcal_evidence import parse_receipt, LibCalCancellation

ORIGIN = 'https://rooms.example.test'
TOKEN = 'synthetic-secret'
URL = ORIGIN + '/equipment/cancel?id=' + TOKEN
ROOM = 'Example Study Room 1'
REQUEST = BookingRequest(Room(Location('libcal', '1', 'America/Denver'), '2'),
    Interval('2026-11-19T18:00:00-07:00', '2026-11-19T20:00:00-07:00', 'America/Denver'), 'attempt')
TEXT = ('Location: Example Library<br>Space: '+ROOM+'<br>Date: Thursday, November 19, 2026'
        '<br>Time: 6:00pm - 8:00pm<br><a href="'+URL+'">Cancel</a>')
PAGE = '''<html><body><div id="booking_123456"><h1>Example Study Room 1</h1>
<p>November 19, 2026, 6:00 p.m. - 8:00 p.m.</p>
<button id="s-lc-cancel-confirm-single-123456">Cancel Booking</button></div>
<script>function cancelSingleBooking(bookingId){url:"/ajax/equipment/cancel/group-token/" + bookingId;}
function cancelAllBookings(){url:"/ajax/equipment/cancel/group-token";}</script></body></html>'''
TERMINAL = '<div id="booking_123456">Booking already cancelled.</div>'


def payload(text=TEXT, filenames=('Booking_123456.ics',)):
    return {'mimeType':'text/html', 'body':{'data':base64.urlsafe_b64encode(text.encode()).decode()},
            'parts':[{'filename':f} for f in filenames]}


def receipt(**changes):
    values = dict(payload=payload(), subject='Booking confirmed', sender='alerts@example.test',
        expected_sender='alerts@example.test', authenticated_origin=ORIGIN, expected_origin=ORIGIN,
        request=REQUEST, booking_id='123456', library_name='Example Library', room_name=ROOM)
    values.update(changes)
    return parse_receipt(**values)


class Transport:
    def __init__(self, replies): self.replies=list(replies); self.calls=[]
    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        value=self.replies.pop(0)
        if isinstance(value, Exception): raise value
        if isinstance(value, Response): return value
        return Response(200, kwargs['url'], value)


def deps(transport):
    return Dependencies(transport, lambda *a: None, lambda: datetime.now(timezone.utc), {},
        dict(provider='libcal', location_id='1', group_id='3', timezone='America/Denver',
             base_url=ORIGIN, availability_path='/spaces'))


def cancel(client, transport, **changes):
    values=dict(receipt=receipt(), request=REQUEST, booking_id='123456', expected_origin=ORIGIN,
                room_name=ROOM, authorized=True, dependencies=deps(transport))
    values.update(changes)
    return client.cancel(**values)


class EvidenceTests(unittest.TestCase):
    def test_final_review_escaped_timing_fails_both_preflights(self):
        interval = 'November 19, 2026, 6:00 p.m. - 8:00 p.m.'
        for extra in ['&lt;Reservation time: 17h00 - 21h00&gt;',
                '&lt;Reservation time: changed&gt;',
                '&#60;Reservation time: 7:00 p.m. - 9:00 p.m.&#62;']:
            for separator in ['', '<br>']:
                page = PAGE.replace(interval, interval + separator + extra)
                for replies in [[page], [PAGE, page]]:
                    with self.subTest(extra=extra, separator=separator, stage=len(replies)):
                        claims = []
                        t = Transport(replies)
                        client = LibCalCancellation(claim_cancellation=lambda e: claims.append(e) or True)
                        result = cancel(client, t)
                        self.assertEqual(result.state, 'unverified')
                        self.assertFalse(result.submission_attempted)
                        self.assertEqual(claims, [])
                        self.assertEqual([c['method'] for c in t.calls], ['GET'] * len(replies))
                        t = Transport([page])
                        result = client.readback(receipt=receipt(), request=REQUEST,
                            booking_id='123456', expected_origin=ORIGIN, room_name=ROOM,
                            dependencies=deps(t))
                        self.assertEqual(result.state, 'unverified')
                        self.assertEqual([c['method'] for c in t.calls], ['GET'])

    def test_final_review_named_status_identity_and_meaning(self):
        for statement in ['Your reservation at Other Library is confirmed for:',
                'Your reservation at Example Library has never been approved but is confirmed for:',
                'Your reservation at Example Library is not confirmed but is confirmed for:']:
            with self.subTest(statement=statement):
                self.assert_review_receipt_unverified(TEXT, subject=statement)
                self.assert_review_receipt_unverified(statement + '<br>' + TEXT)
                p = payload()
                p['parts'].append(payload(statement + '<br>' + TEXT, filenames=()))
                self.assert_review_receipt_unverified(TEXT, payload_override=p)
        statement = 'Your reservation at Example Library is confirmed for:'
        self.assertTrue(receipt(subject=statement).evidence.verified)
        compact = (statement + '<br>' + ROOM + ': 6:00pm - 8:00pm '
            'Thursday, November 19, 2026<br><a href="' + URL + '">Cancel</a>')
        self.assertTrue(receipt(subject=statement, payload=payload(compact)).evidence.verified)
        # Library names are literal identities, including regex punctuation.
        name = 'Example (Central) Library'
        self.assertTrue(receipt(library_name=name, subject=statement.replace('Example Library', name),
            payload=payload(TEXT.replace('Example Library', name))).evidence.verified)

    def test_final_review_terminal_prose_requires_complete_statement(self):
        for prose in ['If booking is cancelled, contact staff.',
                'Booking already cancelled. Correction: cancellation failed.',
                'Booking already cancelled.<p>Correction: cancellation failed.</p>',
                '&lt;If booking is cancelled, contact staff.&gt;',
                'Booking already cancelled. &lt;Correction: cancellation failed.&gt;',
                'No bookings found unless cancellation failed.']:
            with self.subTest(prose=prose):
                page = '<div id="booking_123456">' + prose + '</div>'
                claims = []
                client = LibCalCancellation(claim_cancellation=lambda e: claims.append(e) or True)
                t = Transport([page])
                result = cancel(client, t)
                self.assertEqual(result.state, 'unverified')
                self.assertFalse(result.submission_attempted)
                self.assertEqual(claims, [])
                self.assertEqual([c['method'] for c in t.calls], ['GET'])
                t = Transport([page])
                self.assertEqual(client.readback(receipt=receipt(), request=REQUEST,
                    booking_id='123456', expected_origin=ORIGIN, room_name=ROOM,
                    dependencies=deps(t)).state, 'unverified')
                t = Transport([PAGE, PAGE, '{"success":true}', page])
                result = cancel(client, t)
                self.assertEqual(result.state, 'unknown')
                self.assertTrue(result.submission_attempted)
                self.assertEqual(len(claims), 1)
                self.assertEqual([c['method'] for c in t.calls], ['GET', 'GET', 'POST', 'GET'])
        for prose in ['Booking already cancelled.', 'Booking is canceled',
                'No active bookings were found.', 'Could not find the reservation.']:
            with self.subTest(positive=prose):
                page = '<div id="booking_123456"><p>' + prose + '</p></div>'
                client = LibCalCancellation(claim_cancellation=lambda e: self.fail('unexpected claim'))
                t = Transport([page])
                self.assertEqual(cancel(client, t).state, 'cancelled')
                self.assertEqual([c['method'] for c in t.calls], ['GET'])

    def test_supported_scoped_times_and_compact_receipt(self):
        for clock in ['6:00 p.m. - 8:00 p.m.', '6:00 - 8:00 p.m.',
                '18:00 - 20:00', '6:00 p.m. &ndash; 8:00 p.m.',
                '6:00 p.m. until 8:00 p.m.']:
            with self.subTest(clock=clock):
                page=PAGE.replace('6:00 p.m. - 8:00 p.m.',clock)
                t=Transport([page,page,'{"success":true}',TERMINAL])
                result=cancel(LibCalCancellation(claim_cancellation=lambda e: True),t)
                self.assertEqual(result.state,'cancelled')
                self.assertTrue(result.submission_attempted)
        text=('Example Library<br>'+ROOM+': 6:00pm - 8:00pm Thursday, November 19, 2026'
              '<br><a href="'+URL+'">Cancel</a>')
        self.assertTrue(receipt(payload=payload(text)).evidence.verified)
        self.assert_review_receipt_unverified(text+'<br>Other Study Room 2: '
            '7:00pm - 9:00pm Thursday, November 19, 2026')

    def test_rereview_undated_conflicting_fields_fail_both_preflights(self):
        interval = 'November 19, 2026, 6:00 p.m. - 8:00 p.m.'
        for extra in ['Reservation time: 17h00 - 21h00',
                'Reservation time: 7:00 p.m. - 9:00 p.m.',
                'Reservation time: changed', 'Awaiting approval',
                '6:00 p.m. - 8:00 p.m.']:
            for replacement in [extra+'<br>'+interval, interval+'<br>'+extra]:
                page = PAGE.replace(interval, replacement)
                for replies in [[page], [PAGE, page]]:
                    with self.subTest(extra=extra, replies=len(replies)):
                        claims=[]
                        t=Transport(replies)
                        client=LibCalCancellation(claim_cancellation=lambda e: claims.append(e) or True)
                        result=cancel(client,t)
                        self.assertEqual(result.state,'unverified')
                        self.assertFalse(result.submission_attempted)
                        self.assertEqual(claims,[])
                        self.assertEqual([c['method'] for c in t.calls], ['GET']*len(replies))
                        t=Transport([page])
                        result=client.readback(receipt=receipt(), request=REQUEST, booking_id='123456',
                            expected_origin=ORIGIN, room_name=ROOM, dependencies=deps(t))
                        self.assertEqual(result.state,'unverified')

    def test_rereview_unsupported_records_and_status_fail_closed(self):
        extras=['Other Study Room 2: 17h00 - 21h00 Thursday, November 19, 2026',
            'Other Study Room 2: 7:00 p.m. - 9:00 p.m. Thursday, November 19, 2026',
            'Other Study Room 2: time unavailable',
            'Your booking has never been approved.',
            'Your booking is awaiting approval.',
            'Your booking may eventually be confirmed.',
            'Unrecognized provider text']
        compact=('Example Library<br>'+ROOM+': 6:00pm - 8:00pm Thursday, November 19, 2026'
                 '<br><a href="'+URL+'">Cancel</a>')
        for base in [TEXT, compact]:
            for extra in extras:
                with self.subTest(base=base, extra=extra):
                    self.assert_review_receipt_unverified(base+'<br>'+extra)
                    self.assert_review_receipt_unverified(extra+'<br>'+base)
                    p=payload(base)
                    p['parts'].append(payload(base+'<br>'+extra, filenames=()))
                    self.assert_review_receipt_unverified(base, payload_override=p)
        for subject in ['Your booking has never been approved.',
                'Your booking is awaiting approval.', 'Booking possibly confirmed']:
            self.assert_review_receipt_unverified(TEXT, subject=subject)

    def test_positive_complete_receipt_templates_and_states(self):
        for intro in ['', 'The following bookings have been confirmed:<br>']:
            text=intro+TEXT+'<br>Staff may cancel your booking. To cancel visit https://private.test/token'
            self.assertTrue(receipt(payload=payload(text)).evidence.verified)
        text=('Your reservation at Example Library is confirmed for:<br>'+ROOM+
              ': 6:00pm - 8:00pm Thursday, November 19, 2026<br><a href="'+URL+'">Cancel</a>')
        self.assertTrue(receipt(payload=payload(text),
            subject='Your room booking has been approved!').evidence.verified)
        for subject, intro, state in [
                ('Your reservation request has been submitted', 'Not confirmed until approved.', 'pending'),
                ('Booking Cancelled', 'The following bookings have been cancelled:', 'cancelled'),
                ('Your reservation at Example Library has been denied',
                 'The following booking request could not be approved:', 'rejected')]:
            r=receipt(subject=subject, payload=payload(intro+'<br>'+TEXT))
            self.assertEqual(r.state,state)
            self.assertFalse(r.evidence.verified)
            self.assertIsNone(r._capability)
        # The source also supports a page without the optional single button.
        page=PAGE.replace('<button id="s-lc-cancel-confirm-single-123456">Cancel Booking</button>', '')
        page=page.replace('</body>', '<button>Cancel All Bookings</button></body>')
        t=Transport([page,page,'{"success":true}',TERMINAL])
        self.assertEqual(cancel(LibCalCancellation(claim_cancellation=lambda e: True),t).state,'cancelled')

    def test_review_reservation_time_cannot_use_help_hours(self):
        for clock in ['17h00 - 21h00', 'changed range', '6:00 p.m. - 8:00 p.m. or 6:00 p.m. - 8:00 p.m.']:
            page=PAGE.replace('6:00 p.m. - 8:00 p.m.',
                clock+'<br>Help hours: 6:00 p.m. - 8:00 p.m.')
            for stage,replies in enumerate([[page,page], [PAGE,page]]):
                with self.subTest(clock=clock, stage=stage):
                    claims=[]
                    t=Transport(replies+['{"success":true}',TERMINAL])
                    result=cancel(LibCalCancellation(claim_cancellation=lambda e: claims.append(e) or True),t)
                    self.assertEqual(result.state,'unverified')
                    self.assertFalse(result.submission_attempted)
                    self.assertEqual(claims,[])
                    self.assertTrue(all(c['method']=='GET' for c in t.calls))

    def test_review_multiple_ranges_and_mixed_receipt_styles(self):
        cases=[TEXT.replace('6:00pm - 8:00pm','6:00pm - 8:00pm or 7:00pm - 9:00pm'),
            TEXT.replace('6:00pm - 8:00pm','6:00pm - 8:00pm or 6:00pm - 8:00pm'),
            TEXT+'<br>Other Study Room 2: 7:00pm - 9:00pm Thursday, November 19, 2026',
            TEXT.replace('6:00pm - 8:00pm','17h00 - 21h00')+'<br>Help hours: 6:00pm - 8:00pm']
        for text in cases:
            with self.subTest(text=text):
                self.assert_review_receipt_unverified(text)

    def test_review_contradictory_pending_and_unapproved(self):
        for phrase in ['This booking is pending confirmation.', 'Your booking has not been approved.',
                'This booking is pending approval.', 'Your booking is unapproved.']:
            with self.subTest(phrase=phrase):
                self.assert_review_receipt_unverified(TEXT+'<br>'+phrase)
                p=payload()
                p['parts'].append({'mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode(
                    (TEXT.replace('<br>','\n')+'\n'+phrase).encode()).decode()}})
                self.assertFalse(receipt(payload=p).evidence.verified)

    def assert_review_receipt_unverified(self, text, payload_override=None, **changes):
        r=receipt(payload=payload_override or payload(text), **changes)
        self.assertEqual(r.state,'unverified')
        self.assertFalse(r.evidence.verified)
        self.assertIsNone(r._capability)
        t=Transport([])
        result=cancel(LibCalCancellation(claim_cancellation=lambda e: self.fail('unexpected claim')),t,receipt=r)
        self.assertEqual(result.state,'unverified')
        self.assertFalse(result.submission_attempted)
        self.assertEqual(t.calls,[])

    def test_confirmed_neutral_evidence_and_no_secret_repr(self):
        r=receipt()
        self.assertEqual(r.state, 'confirmed'); self.assertTrue(r.evidence.verified)
        self.assertNotIn(TOKEN, repr(r)); self.assertNotIn(TOKEN, repr(r.evidence))

    def test_jcpl_submission_never_confirms(self):
        result = receipt(subject='Your booking has been submitted')
        self.assertEqual(result.state, 'submitted')
        self.assertFalse(result.evidence.verified)
        self.assertIsNone(result._capability)
        contradictory = receipt(subject='Your booking has been submitted',
                                payload=payload('Booking confirmed<br>' + TEXT))
        self.assertEqual(contradictory.state, 'unverified')

    def test_pending_never_confirmation(self):
        r=receipt(subject='Your reservation request has been submitted')
        self.assertEqual(r.state,'pending'); self.assertFalse(r.evidence.verified)
        self.assertIsNone(r._capability)

    def test_spoof_unrelated_partial_ambiguous_and_drift(self):
        cases=[dict(sender='spoof@example.test'), dict(authenticated_origin='https://evil.test'),
            dict(subject='Library news'), dict(payload=payload('new markup')),
            dict(payload=payload(TEXT.replace(ROOM, ROOM+'0'))),
            dict(payload=payload(TEXT.replace('6:00pm','5:00pm'))),
            dict(payload=payload(TEXT.replace('19, 2026','20, 2026'))),
            dict(payload=payload(filenames=())), dict(payload=payload(filenames=('Booking_999999.ics',))),
            dict(payload=payload(filenames=('Booking_123456.ics','Booking_999999.ics'))),
            dict(payload=payload(TEXT+TEXT)), dict(payload=payload(TEXT+'<br>Location: Partial')),
            dict(payload=payload(TEXT+'<br>Not yet confirmed')), dict(library_name='Other Library'),
            dict(expected_origin=ORIGIN+'/path')]
        for case in cases:
            with self.subTest(case=case): self.assertFalse(receipt(**case).evidence.verified)
        p=payload(); p['parts'].append(payload(TEXT.replace(ROOM, 'Other Room')))
        self.assertFalse(receipt(payload=p).evidence.verified)

    def test_ambiguous_local_receipt_time_is_unverified(self):
        request=replace(REQUEST, interval=Interval('2026-11-01T01:00:00-06:00',
            '2026-11-01T02:00:00-07:00', 'America/Denver'))
        text=TEXT.replace('Thursday, November 19, 2026','Sunday, November 1, 2026').replace(
            '6:00pm - 8:00pm','1:00am - 2:00am')
        self.assertFalse(receipt(request=request,payload=payload(text)).evidence.verified)

    def test_capability_origin_and_ambiguity(self):
        for url in ['https://evil.test/equipment/cancel?id='+TOKEN,
                    'https://user@rooms.example.test/equipment/cancel?id='+TOKEN,
                    URL+'&id=other-secret', URL+'#fragment']:
            self.assertIsNone(receipt(payload=payload(TEXT.replace(URL,url)))._capability)
        self.assertIsNone(receipt(payload=payload(TEXT+'<a href="'+URL+'2">Cancel</a>'))._capability)

    def test_readback_and_already_cancelled_do_not_write_or_claim(self):
        client=LibCalCancellation(claim_cancellation=lambda e: self.fail('unexpected claim'))
        for page, expected in [(PAGE,'active'), (TERMINAL,'cancelled'),
                (TERMINAL.replace('123456','654321'),'unverified'),
                ('<p>Booking already cancelled.</p>','unverified')]:
            t=Transport([page])
            result=client.readback(receipt=receipt(), request=REQUEST, booking_id='123456',
                expected_origin=ORIGIN, room_name=ROOM, dependencies=deps(t))
            self.assertEqual(result.state,expected)
            self.assertFalse(result.submission_attempted)
            self.assertEqual([c['method'] for c in t.calls],['GET'])
        t=Transport([TERMINAL])
        self.assertEqual(cancel(client,t).state,'cancelled')
        self.assertEqual(len(t.calls),1)

    def test_success_only_single_authored_endpoint(self):
        t=Transport([PAGE,PAGE,'{"success":true}',TERMINAL]); claims=[]
        r=cancel(LibCalCancellation(claim_cancellation=lambda e: claims.append(e) or True),t)
        self.assertEqual(r.state,'cancelled'); self.assertTrue(r.submission_attempted)
        self.assertEqual([c['method'] for c in t.calls],['GET','GET','POST','GET'])
        self.assertTrue(t.calls[2]['url'].endswith('/group-token/123456'))
        self.assertEqual(len(claims),1); self.assertNotIn(TOKEN,repr(r))

    def test_authority_identity_and_claim(self):
        for change in [dict(authorized=False), dict(booking_id='999999'), dict(room_name='Other'),
            dict(expected_origin='https://evil.test'), dict(request=replace(REQUEST, attempt_id='other')),
            dict(receipt=receipt(subject='Booking request submitted'))]:
            t=Transport([])
            self.assertFalse(cancel(LibCalCancellation(claim_cancellation=lambda e: True),t,**change).submission_attempted)
            self.assertEqual(t.calls,[])
        t=Transport([PAGE,PAGE])
        self.assertEqual(cancel(LibCalCancellation(claim_cancellation=lambda e: False),t).state,'claim_denied')

    def test_page_spoof_drift_partial_group_only_and_origin(self):
        pages=[PAGE.replace('123456','654321'), PAGE.replace(ROOM, ROOM+'0'),
            PAGE.replace('6:00','5:00'), PAGE.replace('November 19','November 20'),
            PAGE.replace('</body>','<div id="booking_654321"></div></body>'),
            PAGE.replace(' + bookingId',''), '<p>Booking already cancelled.</p>',
            PAGE.replace('6:00 p.m. - 8:00 p.m.', 'changed range')]
        for page in pages:
            t=Transport([PAGE,page]); r=cancel(LibCalCancellation(claim_cancellation=lambda e: True),t)
            self.assertFalse(r.submission_attempted)
        t=Transport([Response(200,'https://evil.test',PAGE)])
        self.assertEqual(cancel(LibCalCancellation(claim_cancellation=lambda e: True),t).state,'unverified')
        t=Transport([Response(302,URL,'',headers={'Location':'https://evil.test'})])
        self.assertFalse(cancel(LibCalCancellation(claim_cancellation=lambda e: True),t).submission_attempted)

    def test_uncertain_write_no_replay_even_fresh_client(self):
        claimed=set()
        def claim(e):
            key=(e.request,e.booking_id,e.origin)
            if key in claimed: return False
            claimed.add(key); return True
        for outcome in [TimeoutError(TOKEN), '{bad', '{"success":false}',
                        Response(200,'https://evil.test','{"success":true}')]:
            claimed.clear(); t=Transport([PAGE,PAGE,outcome]); client=LibCalCancellation(claim_cancellation=claim)
            r=cancel(client,t); self.assertEqual(r.state,'unknown'); self.assertTrue(r.submission_attempted)
            self.assertNotIn(TOKEN,repr(r))
            for c in [client,LibCalCancellation(claim_cancellation=claim)]:
                again=Transport([PAGE,PAGE]); self.assertEqual(cancel(c,again).state,'claim_denied')
                self.assertFalse(any(x['method']=='POST' for x in again.calls))
        for terminal in [TimeoutError(TOKEN), '<p>Booking cancelled.</p>', TERMINAL.replace('123456','654321'),PAGE]:
            t=Transport([PAGE,PAGE,'{"success":true}',terminal])
            self.assertEqual(cancel(LibCalCancellation(claim_cancellation=lambda e: True),t).state,'unknown')


if __name__ == '__main__': unittest.main()
