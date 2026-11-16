"""Run against installed wheel/sdist: synthetic transport, production adapter."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit
from library_room_booking import Location, Room, Interval, BookingRequest, Dependencies, Outcome, ConfirmationEvidence
from library_room_booking.libcal import LibCalAdapter, PreparedBooking, Response

BASE = 'https://library.example.invalid'
FORM = '''<form><input type="hidden" name="session" value="session-fixture">
<input name="fname" required><input name="lname" required><input name="email" required>
<input name="Feedback" required><input name="Address" required><input name="q3240" required>
<input type="checkbox" name="terms" value="1" required>
<input type="hidden" name="provider-default" value="retained"><input name="choice" value="yes" checked></form>'''


class Transport:
    def __init__(self):
        self.calls, self.created = [], 0
        self.form, self.receipt = FORM, {'html': '<p>Booking ID: Booking_12345</p>'}
        self.update, self.window_end = False, False
        self.mismatch = {}
        self.auth = self.timeout = self.bad_status = self.redirect = self.grid = None
        self.slots = [{'itemId': '30', 'start': '2026-11-12 15:00:00', 'end': '2026-11-12 15:30:00', 'checksum': 'start-check'},
                      {'itemId': '30', 'start': '2026-11-12 15:30:00', 'end': '2026-11-12 16:00:00', 'checksum': 'next-check'}]
        self.page = 'var resources = [{eid:30,gid:20,lid:10,capacity:6,title:"Study One"},{eid:31,gid:99,lid:10,capacity:8,title:"Other"}]; bookingMethod: 11'

    def __call__(self, *, method, url, headers, body):
        path = urlsplit(url).path
        pairs = parse_qs(body.decode(), keep_blank_values=True) if body is not None else {}
        self.calls.append((method, path, pairs))
        assert headers['Referer'] == BASE + '/spaces?lid=10&gid=20'
        if self.timeout == path and path != '/ajax/space/book': raise TimeoutError('synthetic')
        if self.bad_status and path == self.bad_status[0]: return Response(self.bad_status[1], url, 'denied')
        if self.redirect == path: return Response(200, BASE+'/login', '<form>login</form>')
        if method == 'GET': result = self.page
        elif path == '/spaces/availability/grid':
            assert pairs['start'] == ['2026-11-12'] and pairs['end'] == ['2026-11-13']
            assert pairs['gid'] == ['20'] and pairs['eid'] == ['30'] and pairs['pageSize'] == ['100']
            result = self.grid if self.grid is not None else {'slots': self.slots, 'windowEnd': self.window_end}
        elif path == '/spaces/availability/booking/add':
            pending = {'id': 40, 'eid': 30, 'gid': 20, 'lid': 10, 'seat_id': 0, 'start': '2026-11-12 15:00:00', 'end': '2026-11-12 16:00:00', 'checksum': 'hold-check'}
            if 'update[id]' in pairs:
                assert pairs['update[id]'] == ['40'] and pairs['update[checksum]'] == ['end-check']
                assert pairs['bookings[0][eid]'] == ['30']
            else:
                assert pairs['add[checksum]'] == ['start-check'] and pairs['bookings'] == ['[]']
                if self.update: pending.update(end='2026-11-12 15:30:00', options=['2026-11-12 16:00:00'], optionChecksums=['end-check'])
            pending.update(self.mismatch)
            result = {'bookings': [pending]}
        elif path == '/ajax/space/times':
            assert pairs['bookings[0][eid]'] == ['30'] and pairs['method'] == ['11']
            result = {'redirect': self.auth} if self.auth else {'html': self.form}
        elif path == '/ajax/space/book':
            assert 'Feedback' not in pairs and 'Address' not in pairs
            pending, = json.loads(pairs['bookings'][0])
            assert str(pending['eid']) == '30' and str(pending['id']) == '40'
            self.created += 1
            if self.timeout == path: raise TimeoutError('success response lost')
            result = self.receipt
        else: raise AssertionError('Unexpected endpoint '+path)
        return Response(200, url, result if type(result) is str else json.dumps(result), 'fixture-receipt')


class LibCalContracts(unittest.TestCase):
    def setUp(self):
        import library_room_booking.libcal as installed
        self.assertTrue(Path(installed.__file__).is_relative_to(sys.prefix))
        self.request = BookingRequest(Room(Location('libcal-test', '10', 'America/Denver'), '30'), Interval('2026-11-12T15:00:00-07:00', '2026-11-12T16:00:00-07:00', 'America/Denver'), 'attempt-one')
        self.transport, self.claims, self.claim_calls = Transport(), set(), []
        def claim(request):
            self.claim_calls.append(request)
            key = (request.room, request.interval)  # caller-owned ledger shared across adapter instances
            if key in self.claims: return False
            self.claims.add(key)
            return True
        self.claim = claim
        self.adapter = LibCalAdapter(claim_submission=claim)
        def forbidden(): self.fail('No credential access allowed')
        self.deps = Dependencies(self.transport, forbidden, lambda: datetime(2026, 11, 12, tzinfo=timezone.utc),
            {'first_name':'Test', 'last_name':'Patron', 'email':'patron@example.invalid', 'phone':'555-0100'},
            {'provider':'libcal-test', 'base_url':BASE, 'availability_path':'/spaces?lid=10&gid=20', 'location_id':10, 'group_id':20, 'timezone':'America/Denver', 'form_values':{'q3240':'4', 'terms':'1'}})

    def submitted(self): return [c for c in self.transport.calls if c[1] == '/ajax/space/book']

    def test_discovery_variants_and_readonly_availability(self):
        result = self.adapter.discover(self.request.room.location, self.deps)
        self.assertEqual(result.resources[0].room, self.request.room)
        self.assertEqual(len(result.resources), 1)
        self.assertEqual(result.resources[0].capacity, 6)
        self.assertEqual(self.adapter.availability(self.request, self.deps).slots, (self.request.interval,))
        self.assertFalse(any('/booking/add' in c[1] for c in self.transport.calls))
        self.assertEqual(self.adapter.operation_effects['preparation'], 'write')
        self.assertEqual(self.adapter.capabilities['cancellation'], 'unsupported')
        self.transport.page = 'resources.push({eid:30,lid:10,gid:20,capacity:2,title:"Room \\u00e9"});'
        self.assertEqual(self.adapter.discover(self.request.room.location, self.deps).resources[0].name, 'Room é')
        for body in ('unknown', 'resources.push({eid:30,lid:10,gid:20,title:"No capacity"});'):
            self.transport.page = body
            self.assertEqual(self.adapter.discover(self.request.room.location, self.deps).outcome, Outcome.FAILED_BEFORE_SUBMIT)

    def test_bounded_same_origin_discovery_grid_link(self):
        calls = []
        def transport(**kw):
            calls.append(kw['url'])
            if '/r/new/availability' in kw['url']:
                self.assertEqual(kw['url'],BASE+'/r/new/availability?lid=10&gid=20')
                body = self.transport.page
            else:
                body = '<a href="mailto:synthetic@example.invalid">contact</a><a href="https://untrusted.example.invalid/r/new/availability?lid=10">foreign</a><a href="/r/new/availability?lid=999">other</a><a href="/r/new/availability?lid=10&amp;gid=999">grid</a>'
            return Response(200,kw['url'],body)
        result = self.adapter.discover(self.request.room.location,replace(self.deps,transport=transport))
        self.assertEqual(result.resources[0].room,self.request.room)
        self.assertEqual(len(calls),2)
        self.assertTrue(all(url.startswith(BASE) for url in calls))

    def test_second_configuration_and_exact_room_identity(self):
        config = {**self.deps.configuration, 'provider':'second-config', 'base_url':'https://second.example.invalid',
                  'availability_path':'/reserve/spaces/branch', 'location_id':50, 'group_id':60, 'timezone':'UTC'}
        location = Location('second-config', '50', 'UTC')
        request = BookingRequest(Room(location, '70'), Interval('2026-11-12T15:00:00Z','2026-11-12T16:00:00Z','UTC'), 'second-attempt')
        calls = []
        def transport(**kw):
            calls.append(kw)
            if '/grid' in kw['url']:
                pairs = parse_qs(kw['body'].decode())
                self.assertEqual((pairs['lid'],pairs['gid'],pairs['eid']), (['50'],['60'],['70']))
                body = json.dumps({'slots':[{'itemId':'70','start':'2026-11-12 15:00:00','end':'2026-11-12 16:00:00'}]})
            else: body = 'resources.push({eid:70,lid:50,gid:60,capacity:4,title:"Second Room"});'
            return Response(200,kw['url'],body)
        deps = replace(self.deps,configuration=config,transport=transport)
        self.assertEqual(self.adapter.discover(location,deps).resources[0].room,request.room)
        self.assertEqual(self.adapter.availability(request,deps).slots,(request.interval,))
        self.assertTrue(all(c['url'].startswith(config['base_url']) for c in calls))

    def test_hold_update_and_form_submission(self):
        self.transport.update = True
        result = self.adapter.book(self.request, self.deps)
        self.assertEqual(result.outcome, Outcome.PENDING_CONFIRMATION)
        self.assertEqual((result.booking_id, result.reference, result.expected_origin), ('Booking_12345','fixture-receipt',BASE))
        self.assertEqual(result.request, self.request)
        self.assertTrue(result.preparation_attempted and result.submission_attempted)
        payload = self.submitted()[0][2]
        for k,v in {'fname':'Test','q3240':'4','terms':'1','session':'session-fixture','provider-default':'retained','choice':'yes'}.items(): self.assertEqual(payload[k], [v])
        self.assertEqual(len([c for c in self.transport.calls if '/booking/add' in c[1]]), 2)

    def test_required_drift_and_missing_contact_are_before_claim(self):
        for extra, name in (('<input name="new-required" required>', 'new-required'), ('<input name="q26898" required>','q26898')):
            self.transport.form = FORM + extra
            result = self.adapter.book(self.request, self.deps)
            self.assertEqual(result.outcome, Outcome.FAILED_BEFORE_SUBMIT)
            self.assertIn(name, result.detail)
            self.assertTrue(result.preparation_attempted)
        self.transport.form = FORM
        self.assertIn('fname', self.adapter.book(self.request, replace(self.deps, contact={})).detail)
        deps = replace(self.deps, configuration={**self.deps.configuration,'form_values':{'terms':'1'}})
        self.assertIn('q3240', self.adapter.book(self.request, deps).detail)
        self.assertEqual(self.claim_calls, [])
        self.assertEqual(self.submitted(), [])

    def test_concealed_disabled_traps_and_optional_defaults(self):
        self.transport.form = FORM + '''<div class="slc-hi"><input name="new-trap" required></div>
          <div aria-hidden="true"><input name="concealed" required></div><div style="display: none"><input name="concealed2" required></div>
          <input name="disabled" required disabled><input type="hidden" name="background" value="6" required>
          <input name="optional"><input type="checkbox" name="sms-opt-in" value="1">'''
        self.assertEqual(self.adapter.book(self.request,self.deps).outcome, Outcome.PENDING_CONFIRMATION)
        payload = self.submitted()[0][2]
        for name in ('new-trap','concealed','concealed2','disabled','optional','sms-opt-in'): self.assertNotIn(name,payload)
        self.assertEqual(payload['background'], ['6'])

    def test_consent_and_session_validation(self):
        deps = replace(self.deps, configuration={**self.deps.configuration, 'form_values':{'terms':'yes','q3240':'4'}})
        self.assertIn('Invalid required choice', self.adapter.book(self.request,deps).detail)
        self.transport.form = '<form><input name="fname" required></form>'
        self.assertIn('session',self.adapter.book(self.request,self.deps).detail)
        self.assertEqual(self.claim_calls,[])

    def test_pending_identity_and_end_checksum_drift(self):
        for mismatch in ({'eid':31},{'lid':11},{'gid':21},{'start':'2026-11-12 15:30:00'},{'checksum':''},{'end':'2026-11-12 17:00:00'}):
            self.transport.mismatch = mismatch
            self.assertEqual(self.adapter.book(self.request,self.deps).outcome,Outcome.FAILED_BEFORE_SUBMIT)
        self.transport.update,self.transport.mismatch = True, {'optionChecksums':[]}
        self.assertIn('checksum',self.adapter.book(self.request,self.deps).detail)
        self.assertEqual(self.submitted(),[])

    def test_end_update_preserves_pending_id_before_form_or_claim(self):
        self.transport.update = True
        original = self.transport
        def transport(**kw):
            response = original(**kw)
            pairs = parse_qs(kw['body'].decode()) if kw['body'] else {}
            if 'update[id]' in pairs:
                data = json.loads(response.body)
                data['bookings'][0]['id'] = 999
                return replace(response, body=json.dumps(data))
            return response
        result = self.adapter.prepare(self.request, replace(self.deps, transport=transport))
        self.assertNotIsInstance(result, PreparedBooking)
        self.assertEqual(result.outcome, Outcome.FAILED_BEFORE_SUBMIT)
        self.assertIn('identity', result.detail)
        self.assertTrue(result.preparation_attempted)
        self.assertFalse(result.submission_attempted)
        self.assertFalse(any(c[1] == '/ajax/space/times' for c in original.calls))
        self.assertEqual(self.claim_calls, [])
        self.assertEqual(self.submitted(), [])

    def test_uncertain_submit_retains_origin_and_received_reference(self):
        original = self.transport
        for change in ({'body':'bad json'}, {'body':'[]'}, {'body':'{}'},
                       {'status':403}, {'status':500}, {'url':BASE+'/login'},
                       {'body':None}):
            with self.subTest(change=change):
                self.claims.clear()
                def transport(**kw):
                    response = original(**kw)
                    return replace(response, **change) if urlsplit(kw['url']).path == '/ajax/space/book' else response
                result = self.adapter.book(self.request, replace(self.deps, transport=transport))
                self.assertEqual(result.outcome, Outcome.UNKNOWN_AFTER_SUBMIT)
                self.assertEqual(result.expected_origin, BASE)
                self.assertEqual(result.reference, 'fixture-receipt')
                self.assertEqual(result.request, self.request)
                self.assertTrue(result.preparation_attempted and result.submission_attempted)

    def test_required_select_fails_closed_before_claim(self):
        for options in ('<option value="No">No</option>',
                        '<option value="unoffered-answer" disabled>No</option>',
                        '<optgroup disabled><option value="unoffered-answer">No</option></optgroup>'):
            with self.subTest(options=options):
                self.claims.clear()
                self.transport.form = FORM + '<select name="q9176" required>' + options + '</select>'
                deps = replace(self.deps, configuration={**self.deps.configuration,
                    'form_values':{**self.deps.configuration['form_values'], 'q9176':'unoffered-answer'}})
                result = self.adapter.book(self.request, deps)
                self.assertEqual(result.outcome, Outcome.FAILED_BEFORE_SUBMIT)
                self.assertIn('q9176', result.detail)
                self.assertTrue(result.preparation_attempted)
                self.assertFalse(result.submission_attempted)
                self.assertEqual(self.claim_calls, [])
                self.assertEqual(self.submitted(), [])

    def test_auth_changes_and_redirects(self):
        self.transport.auth = 'https://login.example.invalid/signin'
        result = self.adapter.book(self.request,self.deps)
        self.assertEqual(result.outcome,Outcome.AUTHENTICATION_REQUIRED)
        self.assertTrue(result.preparation_attempted)
        self.transport.auth,self.transport.bad_status = None,('/spaces/availability/grid',401)
        self.assertEqual(self.adapter.book(self.request,self.deps).outcome,Outcome.AUTHENTICATION_REQUIRED)
        self.transport.bad_status,self.transport.redirect = None,'/spaces'
        self.assertEqual(self.adapter.book(self.request,self.deps).outcome,Outcome.AUTHENTICATION_REQUIRED)
        self.assertEqual(self.submitted(),[])
        self.assertEqual(self.claim_calls,[])

    def test_unavailable_gap_unknown_and_booking_window(self):
        for classes,outcome in ((['s-lc-eq-r-padding'],Outcome.UNAVAILABLE),(['unknown'],Outcome.FAILED_BEFORE_SUBMIT)):
            self.transport.slots[0]['className']=classes
            self.assertEqual(self.adapter.availability(self.request,self.deps).outcome,outcome)
        del self.transport.slots[0]['className']
        self.transport.slots.pop()
        self.assertEqual(self.adapter.availability(self.request,self.deps).outcome,Outcome.FAILED_BEFORE_SUBMIT)
        self.transport.slots,self.transport.window_end = [],True
        self.assertEqual(self.adapter.availability(self.request,self.deps).outcome,Outcome.DEFERRED)
        self.assertEqual(self.submitted(),[])

    def test_malformed_schedule_and_configuration(self):
        for bad in ('not json',[],{'unexpected':[]},{'slots':[None]},{'slots':[{'itemId':'30','start':'bad'}]}, {'slots':[{'itemId':'31','start':'bad'}]}):
            self.transport.grid=bad
            self.assertEqual(self.adapter.book(self.request,self.deps).outcome,Outcome.FAILED_BEFORE_SUBMIT)
        self.assertEqual(self.claim_calls,[])
        with self.assertRaises(ValueError): self.adapter.book(replace(self.request,room=replace(self.request.room,location=replace(self.request.room.location,location_id='999'))),self.deps)
        with self.assertRaises(ValueError): self.adapter.book(self.request,replace(self.deps,configuration={**self.deps.configuration,'availability_path':'https://wrong.example.invalid/spaces'}))

    def test_timeout_after_success_and_caller_owned_duplicates(self):
        self.transport.timeout='/ajax/space/book'
        prepared=self.adapter.prepare(self.request,self.deps)
        result=self.adapter.submit(prepared)
        self.assertEqual(result.outcome,Outcome.UNKNOWN_AFTER_SUBMIT)
        self.assertTrue(result.submission_attempted)
        self.assertEqual(result.expected_origin, BASE)
        self.assertIsNone(result.reference)
        self.assertEqual(self.adapter.submit(prepared).outcome,Outcome.UNKNOWN_AFTER_SUBMIT)
        other=LibCalAdapter(claim_submission=self.claim)
        for request in (self.request,replace(self.request,attempt_id='another-id-same-intent')):
            self.assertEqual(other.book(request,self.deps).outcome,Outcome.UNKNOWN_AFTER_SUBMIT)
        self.assertEqual(self.transport.created,1)
        self.assertEqual(len(self.submitted()),1)

    def test_preparation_timeout_and_claim_failure(self):
        self.transport.timeout='/spaces/availability/booking/add'
        result=self.adapter.book(self.request,self.deps)
        self.assertEqual(result.outcome,Outcome.FAILED_BEFORE_SUBMIT)
        self.assertTrue(result.preparation_attempted)
        self.assertFalse(result.submission_attempted)
        self.transport.timeout=None
        def broken(request): raise RuntimeError('ledger unavailable')
        self.assertEqual(LibCalAdapter(claim_submission=broken).book(self.request,self.deps).outcome,Outcome.FAILED_BEFORE_SUBMIT)
        self.assertEqual(self.submitted(),[])

    def test_malformed_receipt_rejection_and_post_submit_auth(self):
        for receipt,outcome in (([],Outcome.UNKNOWN_AFTER_SUBMIT),('bad json',Outcome.UNKNOWN_AFTER_SUBMIT),({},Outcome.UNKNOWN_AFTER_SUBMIT),
          ({'html':'Unknown form'},Outcome.UNKNOWN_AFTER_SUBMIT),({'error':'Not allowed'},Outcome.REJECTED),
          ({'html':'Your booking has been Submitted.'},Outcome.PENDING_CONFIRMATION),({'html':'Confirmation: confirmed'},Outcome.PENDING_CONFIRMATION)):
            self.claims.clear(); self.transport.receipt=receipt
            result=self.adapter.book(self.request,self.deps)
            self.assertEqual(result.outcome,outcome)
            self.assertTrue(result.submission_attempted)
        self.claims.clear(); self.transport.bad_status=('/ajax/space/book',403)
        self.assertEqual(self.adapter.book(self.request,self.deps).outcome,Outcome.UNKNOWN_AFTER_SUBMIT)

    def test_exact_evidence_and_ambiguous_receipts(self):
        e=ConfirmationEvidence(self.request,'Booking_12345',BASE,'caller-receipt',True)
        self.assertEqual(self.adapter.book(self.request,replace(self.deps,evidence=(e,))).outcome,Outcome.CONFIRMED)
        for bad in (replace(e,verified=False),replace(e,booking_id='other'),replace(e,origin='other'),replace(e,request=replace(self.request,attempt_id='other')),
          replace(e,request=replace(self.request,room=replace(self.request.room,room_id='31'))),
          replace(e,request=replace(self.request,interval=Interval('2026-11-12T16:00:00-07:00','2026-11-12T17:00:00-07:00','America/Denver')))):
            self.claims.clear()
            self.assertEqual(self.adapter.book(self.request,replace(self.deps,evidence=(bad,))).outcome,Outcome.PENDING_CONFIRMATION)
        self.claims.clear()
        self.assertEqual(self.adapter.book(self.request,replace(self.deps,evidence=(e,e))).outcome,Outcome.PENDING_CONFIRMATION)
        for receipt in ('<p>Booking ID: Booking_12345</p><p>Reference: OTHER123</p>', '<p>Bookings confirmed.</p><a href="https://library.example.invalid/equipment/cancel?id=secret">Cancel this booking</a>'):
            self.claims.clear(); self.transport.receipt={'html':receipt}
            result=self.adapter.book(self.request,self.deps)
            self.assertIsNone(result.booking_id)
            self.assertIsNone(result.evidence)
            self.assertNotEqual(result.outcome,Outcome.CONFIRMED)

    def test_bounded_injected_authentication_and_untrusted_action(self):
        auth_origin = 'https://auth.example.invalid'
        self.transport.auth = auth_origin + '/login'
        auth_calls = []
        def credentials():
            auth_calls.append('credentials')
            return {'username': 'synthetic-patron', 'password': 'synthetic-password'}
        def transport(**kw):
            url = kw['url']
            if url == auth_origin+'/login':
                return Response(200, url, '<form action="/authenticate"><input type="hidden" name="token" value="test-token"><input name="username"><input name="password"></form>')
            if url == auth_origin+'/authenticate':
                pairs = parse_qs(kw['body'].decode())
                self.assertEqual(pairs['username'], ['synthetic-patron'])
                self.assertEqual(pairs['token'], ['test-token'])
                auth_calls.append('login')
                return Response(302, url, '', headers={'Location': BASE+'/details'})
            if url == BASE+'/details': return Response(200, url, FORM)
            return self.transport(**kw)
        deps = replace(self.deps, transport=transport, credentials=credentials,
            configuration={**self.deps.configuration, 'auth_origins': (auth_origin,)})
        self.assertEqual(self.adapter.book(self.request, deps).outcome, Outcome.PENDING_CONFIRMATION)
        self.assertEqual(auth_calls, ['credentials','login'])
        def malicious(**kw):
            if kw['url'] == auth_origin+'/login':
                return Response(200, kw['url'], '<form action="https://untrusted.example.invalid/steal"><input name="username"><input name="password"></form>')
            return self.transport(**kw)
        result = self.adapter.book(self.request, replace(deps, transport=malicious))
        self.assertEqual(result.outcome, Outcome.AUTHENTICATION_REQUIRED)
        self.assertEqual(auth_calls, ['credentials','login'])
        def auth_drift(**kw):
            if kw['url'] == auth_origin+'/login': return Response(200, kw['url'], '<p>SSO changed</p>')
            return self.transport(**kw)
        self.assertEqual(self.adapter.book(self.request, replace(deps, transport=auth_drift)).outcome, Outcome.AUTHENTICATION_REQUIRED)

    def test_prepared_snapshot_and_concurrent_one_use(self):
        from concurrent.futures import ThreadPoolExecutor
        prepared = self.adapter.prepare(self.request, self.deps)
        self.assertIsInstance(prepared, PreparedBooking)
        self.deps.configuration['base_url'] = 'https://changed.example.invalid'
        self.deps.contact['first_name'] = 'Changed'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.adapter.submit, (prepared, prepared)))
        self.assertEqual(sum(r.outcome is Outcome.PENDING_CONFIRMATION for r in results), 1)
        self.assertEqual(len(self.submitted()), 1)
        self.assertEqual(self.submitted()[0][2]['fname'], ['Test'])
        with self.assertRaises(ValueError): LibCalAdapter(claim_submission=self.claim).submit(prepared)

    def test_dst_spring_and_provider_ambiguous_fold(self):
        def transport(**kw):
            slots=[{'itemId':'30','start':'2026-03-08 01:30:00','end':'2026-03-08 03:30:00','checksum':'spring'}]
            return Response(200,kw['url'],json.dumps({'slots':slots}) if '/grid' in kw['url'] else 'bookingMethod: 11')
        request=replace(self.request,interval=Interval('2026-03-08T01:30:00-07:00','2026-03-08T03:30:00-06:00','America/Denver'))
        result=self.adapter.availability(request,replace(self.deps,transport=transport))
        self.assertEqual(result.outcome,Outcome.AVAILABLE)
        self.assertEqual((result.slots[0].bounds()[1]-result.slots[0].bounds()[0]).total_seconds(),3600)
        def fall(**kw):
            slots=[{'itemId':'30','start':'2026-11-01 01:30:00','end':'2026-11-01 02:30:00'}]
            return Response(200,kw['url'],json.dumps({'slots':slots}) if '/grid' in kw['url'] else 'page')
        request=replace(self.request,interval=Interval('2026-11-01T01:30:00-06:00','2026-11-01T02:30:00-07:00','America/Denver'))
        result=self.adapter.book(request,replace(self.deps,transport=fall))
        self.assertEqual(result.outcome,Outcome.FAILED_BEFORE_SUBMIT)
        self.assertIn('ambiguous',result.detail)
        self.assertEqual(self.claim_calls,[])


if __name__ == '__main__': unittest.main()
