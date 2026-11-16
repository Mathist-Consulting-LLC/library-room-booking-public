"""Synthetic installed-consumer tests; no Google SDK or network."""
from copy import deepcopy
import importlib.util
import pathlib
import sys
import unittest
from library_room_booking.email import (
    MailboxBinding, TrustedProvenance, ConnectorFailure, lookup_recipient,
)
import library_room_booking.email as module

assert pathlib.Path(module.__file__).is_relative_to(sys.prefix)
assert importlib.util.find_spec('google') is None

ADDRESS = 'reader+opaque.Tag-17@example.test'
BINDING = MailboxBinding('caller-account', 'reader@example.test')


def raw(address=ADDRESS, message_id='one'):
    return {'id': message_id, 'payload': {'headers': [
        {'name': 'To', 'value': 'Reader <' + address + '>'},
        {'name': 'From', 'value': 'forged@untrusted.test'},
        {'name': 'Authentication-Results', 'value': 'spoofed pass'},
        {'name': 'X-Authenticated-Origin', 'value': 'https://forged.test'},
    ], 'mimeType': 'text/plain', 'body': {'data': 'c2VjcmV0'}}}


class Connector:
    def __init__(self):
        self.calls = []
        self.pages = [{'messages': [{'id': 'one'}]}]
        self.raw = raw()
        self.address = BINDING.address
        self.failure = None

    def profile(self, **kwargs):
        self.calls.append(('profile', kwargs))
        if self.failure:
            raise self.failure
        return {'emailAddress': self.address}

    def list_messages(self, **kwargs):
        self.calls.append(('list', kwargs))
        return self.pages.pop(0)

    def get_message(self, **kwargs):
        self.calls.append(('get', kwargs))
        return deepcopy(self.raw)


class MailTests(unittest.TestCase):
    def lookup(self, connector, **kwargs):
        return lookup_recipient(connector=connector, mailbox=BINDING,
                                recipient=ADDRESS, **kwargs)

    def test_exact_tag_and_no_inferred_provenance(self):
        c = Connector()
        result = self.lookup(c)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.messages), 1)
        self.assertIsNone(result.messages[0].provenance)
        query = c.calls[1][1]['query']
        self.assertIn('to:"' + ADDRESS + '"', query)
        self.assertTrue(all(call[1]['account'] == BINDING.account for call in c.calls))
        self.assertNotIn('forged', repr(result))
        self.assertNotIn(ADDRESS, repr(result))
        self.assertNotIn('c2VjcmV0', repr(result))
        result.messages[0].payload['headers'].clear()
        self.assertTrue(c.raw['payload']['headers'])

    def test_no_normalization_or_partial_match(self):
        for address in ['reader@example.test', 'reader+opaque@example.test',
                        'reader+opaque.Tag-170@example.test', ADDRESS.upper(),
                        'reader+opaque.Tag-17@other.test']:
            with self.subTest(address=address):
                c = Connector(); c.raw = raw(address)
                self.assertEqual(self.lookup(c).messages, ())
        c = Connector(); c.raw['payload']['headers'] = [
            {'name': 'Subject', 'value': ADDRESS},
            {'name': 'From', 'value': ADDRESS}]
        self.assertEqual(self.lookup(c).messages, ())

    def test_recipient_headers_and_lists(self):
        for header in ['To', 'Cc', 'Bcc', 'Delivered-To']:
            c = Connector(); c.raw['payload']['headers'] = [
                {'name': header, 'value': 'other@example.test, ' + ADDRESS}]
            self.assertEqual(len(self.lookup(c).messages), 1)

    def test_trusted_caller_boundary(self):
        calls = []
        trusted = TrustedProvenance('https://provider.example.test', 'alerts@example.test')
        def resolve(binding, message_id):
            calls.append((binding, message_id))
            return trusted
        result = self.lookup(Connector(), provenance=resolve)
        self.assertEqual(result.messages[0].provenance, trusted)
        self.assertEqual(calls, [(BINDING, 'one')])
        result = self.lookup(Connector(), provenance=lambda *_: {'origin': 'forged'})
        self.assertEqual(result.error.code, 'provenance_failed')

    def test_mailbox_binding_stops_before_search(self):
        c = Connector(); c.address = 'other@example.test'
        self.assertEqual(self.lookup(c).error.code, 'mailbox_mismatch')
        self.assertEqual([x[0] for x in c.calls], ['profile'])

    def test_invalid_inputs_never_call_connector(self):
        for address in ['*', 'a@example.test OR in:anywhere', 'a@example.test\n',
                        'Display <a@example.test>', '', 'a"@example.test']:
            c = Connector()
            self.assertEqual(lookup_recipient(connector=c, mailbox=BINDING,
                recipient=address).error.code, 'invalid_configuration')
            self.assertEqual(c.calls, [])
        for limits in [{'max_pages': 0}, {'max_messages': False}]:
            c = Connector()
            self.assertEqual(self.lookup(c, **limits).error.code, 'invalid_configuration')
            self.assertEqual(c.calls, [])

    def test_pagination_deduplication_and_empty(self):
        c = Connector(); c.pages = [
            {'messages': [{'id': 'one'}], 'nextPageToken': 'next'},
            {'messages': [{'id': 'one'}]}]
        self.assertEqual(len(self.lookup(c).messages), 1)
        self.assertEqual([x[0] for x in c.calls].count('get'), 1)
        self.assertEqual(c.calls[-1][1]['page_token'], 'next')
        c = Connector(); c.pages = [{}]
        self.assertEqual(self.lookup(c).messages, ())

    def test_limits_and_bad_pages_discard_partial_results(self):
        for pages, limits, expected in [
            ([{'messages': [{'id': 'one'}], 'nextPageToken': 'n'}], {'max_pages': 1}, 'scan_limit'),
            ([{'messages': [{'id': 'one'}], 'nextPageToken': 'n'}], {'max_messages': 1}, 'scan_limit'),
            ([{'messages': [{'id': 'one'}, {'id': 'two'}]}], {'max_messages': 1}, 'scan_limit'),
            ([{'nextPageToken': 'n'}, {'nextPageToken': 'n'}], {}, 'invalid_response'),
            ([{'messages': 'bad'}], {}, 'invalid_response'),
            ([{'messages': [{}]}], {}, 'invalid_response'),
            ([{'nextPageToken': 5}], {}, 'invalid_response'),
        ]:
            c = Connector(); c.pages = pages
            result = self.lookup(c, **limits)
            self.assertEqual(result.error.code, expected)
            self.assertEqual(result.messages, ())

    def test_bad_message_and_header_shapes(self):
        for message in [{}, {'id': 'wrong', 'payload': {}},
                        {'id': 'one', 'payload': {'headers': None}},
                        {'id': 'one', 'payload': {'headers': [{'name': 'To'}]}},
                        {'id': 'one', 'payload': {'headers': [{'name': 'To', 'value': ADDRESS+'\n'}]}}]:
            c = Connector(); c.raw = message
            self.assertEqual(self.lookup(c).error.code, 'invalid_response')

    def test_failures_during_list_get_and_late_page_are_atomic(self):
        for stage in ('list', 'get', 'late-list'):
            class Failing(Connector):
                def list_messages(self, **kwargs):
                    if stage == 'list' or (stage == 'late-list' and kwargs['page_token']):
                        raise RuntimeError('SECRET body token')
                    return {'messages': [{'id': 'one'}], 'nextPageToken': 'next'}
                def get_message(self, **kwargs):
                    if stage == 'get':
                        raise ConnectorFailure('permission_denied')
                    return super().get_message(**kwargs)
            result = self.lookup(Failing())
            self.assertEqual(result.messages, ())
            self.assertEqual(result.error.operation, 'get' if stage == 'get' else 'list')
            self.assertNotIn('SECRET', repr(result))

    def test_sanitized_errors_and_no_retry(self):
        for error, code in [(RuntimeError('SECRET token https://private'), 'connector_failed'),
                            (ConnectorFailure('authentication_required'), 'authentication_required'),
                            (ConnectorFailure('permission_denied'), 'permission_denied'),
                            (ConnectorFailure('rate_limited'), 'rate_limited'),
                            (ConnectorFailure('SECRET'), 'connector_failed')]:
            c = Connector(); c.failure = error
            result = self.lookup(c)
            self.assertEqual(result.error.code, code)
            self.assertTrue(result.error.action)
            self.assertNotIn('SECRET', repr(result))
            self.assertEqual(len(c.calls), 1)
        def broken(*_):
            raise RuntimeError('SECRET')
        result = self.lookup(Connector(), provenance=broken)
        self.assertEqual(result.error.operation, 'provenance')
        self.assertNotIn('SECRET', repr(result))


if __name__ == '__main__':
    unittest.main()
