"""Composed synthetic application contracts, against installed public modules."""
from copy import deepcopy
from pathlib import Path
import json
import runpy
import unittest

example = runpy.run_path(str(Path(__file__).with_name('consumer_example.py')))
Consumer, Principal, message = (example[n] for n in ('Consumer', 'Principal', 'message'))
MEMBER, OPERATOR, REF = (example[n] for n in ('MEMBER', 'OPERATOR', 'REFERENCE'))


class ConsumerContracts(unittest.TestCase):
    def started(self, **options):
        app = Consumer(**options)
        self.assertEqual(app.create_event(MEMBER)['status'], 'submitted')
        return app

    def assert_private(self, app):
        public = json.dumps([app.view(MEMBER), app.site_updates, app.outbox])
        for private in [example['CAPABILITY'], 'synthetic-private-capability', example['RECIPIENT'],
                        example['SENDER'], 'Booking_123456.ics', 'mail-confirmed', 'Authentication-Results']:
            self.assertNotIn(private, public)
        for update in app.site_updates + app.outbox:
            self.assertEqual(set(update), {'reference', 'status', 'message'})

    def test_real_submission_tagged_lookup_pending_then_confirmation(self):
        app = self.started(email_updates=True)
        submitted = [c for c in app.provider.calls if c[1] == '/ajax/space/book']
        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0][2]['email'], [example['RECIPIENT']])
        self.assertEqual(app.result.booking_id, '123456')
        app.inbox.messages = [message('mail-pending', subject='Your reservation request has been submitted',
            text='Not confirmed until approved.<br>' + example['TEXT'])]
        original = app.lookup_original(OPERATOR, REF)
        self.assertEqual(original.messages[0].message_id, 'mail-pending')
        self.assertEqual(app.refresh(OPERATOR)['status'], 'provider_pending')
        app.inbox.messages = [message()]
        self.assertEqual(app.refresh(OPERATOR)['status'], 'confirmed')
        app.refresh(OPERATOR)
        self.assertEqual([u['status'] for u in app.site_updates], ['submitted', 'provider_pending', 'confirmed'])
        self.assertEqual(app.outbox, app.site_updates)
        self.assert_private(app)

    def test_server_authorization_precedes_side_effects_and_reads(self):
        for principal in [None, Principal('member-a', tenant='other'), Principal('member-a', can_request=False), OPERATOR]:
            app = Consumer()
            with self.assertRaises(PermissionError):
                app.create_event(principal)
            self.assertEqual(app.provider.calls, [])
            self.assertEqual(app.inbox.calls, [])
            self.assertEqual(app.outbox, [])
        app = self.started()
        for principal in [None, Principal('member-a', tenant='other'), Principal('other-member')]:
            with self.assertRaises(PermissionError):
                app.view(principal)
        for principal in [MEMBER, None, Principal('op', tenant='other', operator=True)]:
            with self.assertRaises(PermissionError):
                app.lookup_original(principal, REF)
            with self.assertRaises(PermissionError):
                app.refresh(principal)
        with self.assertRaises(PermissionError):
            app.lookup_original(OPERATOR, 'guessed-reference')
        self.assertEqual(app.inbox.calls, [])

    def test_missing_inaccessible_and_wrong_inbox_are_actionable(self):
        for failure, expected in [(None, 'exact tagged recipient'), ('authentication_required', 'Reconnect'),
                ('permission_denied', 'permissions'), ('rate_limited', 'Retry later')]:
            with self.subTest(failure=failure):
                app = self.started(email_updates=True)
                app.inbox.failure = failure
                self.assertEqual(app.refresh(OPERATOR)['status'], 'needs_attention')
                self.assertIn(expected, app.action)
                before = len(app.outbox)
                app.refresh(OPERATOR)
                self.assertEqual(len(app.outbox), before)
                self.assert_private(app)
        app = self.started()
        app.inbox.address = 'wrong@example.invalid'
        self.assertEqual(app.refresh(OPERATOR)['status'], 'needs_attention')
        self.assertIn('Bind', app.action)
        self.assertEqual([c[0] for c in app.inbox.calls], ['profile'])

    def test_exact_tag_and_provenance_are_independent(self):
        app = self.started()
        app.inbox.messages = [message(recipient=example['RECIPIENT'].replace('18-fixture', '18-fixture-other'))]
        self.assertEqual(app.refresh(OPERATOR)['status'], 'needs_attention')
        app.inbox.messages = [message()]
        app.attestations.clear()  # Headers still claim From + dkim=pass.
        self.assertEqual(app.refresh(OPERATOR)['status'], 'needs_attention')
        self.assertIn('provenance', app.action)
        trust = example['TrustedProvenance']
        for attestation in [trust('https://foreign.example.invalid', example['SENDER']),
                            trust(example['ORIGIN'], 'forged@example.invalid')]:
            app.attestations[(example['MAILBOX'].account, 'mail-confirmed')] = attestation
            self.assertEqual(app.refresh(OPERATOR)['status'], 'needs_attention')
        self.assert_private(app)

    def test_multiple_conflicting_or_wrong_identity_evidence_never_confirms(self):
        cases = [[message(), message('mail-pending', subject='Your reservation request has been submitted')],
                 [message(), message('second-confirmation')],
                 [message(text=example['TEXT'].replace('Study One', 'Other Room'))],
                 [message(text=example['TEXT'].replace('6:00pm', '5:00pm'))],
                 [message(subject='Booking Cancelled')], [message(subject='Library news')]]
        bad_id = message()
        bad_id['payload']['parts'] = [{'filename': 'Booking_999999.ics'}]
        cases.append([bad_id])
        ambiguous_subject = message()
        ambiguous_subject['payload']['headers'].append({'name': 'Subject', 'value': 'Booking Cancelled'})
        cases.append([ambiguous_subject])
        conflicting_mime = message()
        conflicting_mime['payload']['parts'].append(message(text=example['TEXT'].replace('Study One', 'Other Room'))['payload'])
        cases.append([conflicting_mime])
        for messages in cases:
            with self.subTest(messages=len(messages)):
                app = self.started(email_updates=True)
                app.inbox.messages = deepcopy(messages)
                self.assertEqual(app.refresh(OPERATOR)['status'], 'needs_attention')
                self.assertTrue(app.action)
                self.assert_private(app)

    def test_uncertain_submission_and_missing_identity_never_replay_or_infer(self):
        for flag in ['timeout', 'missing_identity']:
            app = Consumer()
            setattr(app.provider, flag, True)
            self.assertEqual(app.create_event(MEMBER)['status'], 'needs_attention')
            app.inbox.messages = [message()]
            self.assertEqual(app.refresh(OPERATOR)['status'], 'needs_attention')
            with self.assertRaises(ValueError):
                app.create_event(MEMBER)
            self.assertEqual(len([c for c in app.provider.calls if c[1] == '/ajax/space/book']), 1)
            self.assert_private(app)

    def test_optional_delivery_projection_is_copied_and_polling_is_quiet(self):
        app = self.started()
        app.inbox.messages = [message()]
        app.refresh(OPERATOR)
        self.assertEqual(app.outbox, [])
        app.email_updates = True  # No retroactive delivery when opting in.
        app.refresh(OPERATOR)
        self.assertEqual(app.outbox, [])
        app.inbox.messages = []
        app.refresh(OPERATOR)
        self.assertEqual(len(app.outbox), 1)
        returned = app.view(MEMBER)
        returned['message'] = 'untrusted mutation'
        self.assertNotEqual(app.outbox[0]['message'], returned['message'])
        self.assert_private(app)


if __name__ == '__main__':
    unittest.main()
