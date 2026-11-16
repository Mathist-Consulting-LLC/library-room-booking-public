"""Exercise the real service adapter with a read-only in-memory service."""
from copy import deepcopy
import unittest

from library_room_booking.email import MailboxBinding, lookup_recipient
from library_room_booking.gmail_connector import GmailServiceConnector


ADDRESS = "rooms+opaque-fixture@example.invalid"
BINDING = MailboxBinding("fixture-account", "rooms@example.invalid")


class Service:
    def __init__(self, address=BINDING.address):
        self.address = address
        self.calls = []
        self.failure = None
        self.failure_operation = "profile"

    def users(self):
        return self

    def messages(self):
        return self

    def request(self, operation, kwargs, result):
        owner = self

        class Request:
            def execute(self, *, num_retries):
                owner.calls.append((operation, kwargs, num_retries))
                if owner.failure and operation == owner.failure_operation:
                    raise owner.failure
                return deepcopy(result)

        return Request()

    def getProfile(self, **kwargs):
        return self.request("profile", kwargs, {"emailAddress": self.address})

    def list(self, **kwargs):
        return self.request("list", kwargs, {"messages": [{"id": "fixture-message"}]})

    def get(self, **kwargs):
        return self.request("get", kwargs, {
            "id": "fixture-message", "payload": {"headers": [
                {"name": "Delivered-To", "value": ADDRESS},
            ]},
        })

    # No send/modify/delete/attachment or reservation interfaces exist.


class ConnectorTests(unittest.TestCase):
    def lookup(self, connector, mailbox=BINDING):
        return lookup_recipient(connector=connector, mailbox=mailbox, recipient=ADDRESS)

    def test_actual_lookup_uses_bound_service_and_read_only_shapes(self):
        service, other = Service(), Service("other@example.invalid")
        result = self.lookup(GmailServiceConnector({BINDING.account: service, "other": other}))
        self.assertIsNone(result.error)
        self.assertEqual(len(result.messages), 1)
        self.assertIsNone(result.messages[0].provenance)
        self.assertEqual(other.calls, [])
        self.assertEqual([x[0] for x in service.calls], ["profile", "list", "get"])
        self.assertTrue(all(x[1]["userId"] == "me" and x[2] == 0 for x in service.calls))
        self.assertIn('to:"' + ADDRESS + '"', service.calls[1][1]["q"])
        self.assertEqual(service.calls[2][1], {
            "userId": "me", "id": "fixture-message", "format": "full"})

    def test_unknown_account_has_no_fallback(self):
        service = Service()
        connector = GmailServiceConnector({"other": service})
        result = self.lookup(connector)
        self.assertEqual(result.error.code, "authentication_required")
        self.assertEqual(service.calls, [])

    def test_mapping_changes_cannot_rebind_existing_connector(self):
        service, other = Service(), Service("other@example.invalid")
        services = {BINDING.account: service}
        connector = GmailServiceConnector(services)
        services[BINDING.account] = other
        self.assertIsNone(self.lookup(connector).error)
        self.assertEqual(other.calls, [])

    def test_profile_mismatch_stops_before_search(self):
        service = Service("wrong@example.invalid")
        result = self.lookup(GmailServiceConnector({BINDING.account: service}))
        self.assertEqual(result.error.code, "mailbox_mismatch")
        self.assertEqual([x[0] for x in service.calls], ["profile"])

    def test_pagination_arguments_are_preserved(self):
        service = Service()
        connector = GmailServiceConnector({BINDING.account: service})
        connector.list_messages(account=BINDING.account, query="fixture-query",
                                page_token="fixture-next", max_results=7)
        self.assertEqual(service.calls, [("list", {
            "userId": "me", "q": "fixture-query", "pageToken": "fixture-next",
            "maxResults": 7}, 0)])

    def test_failure_is_sanitized_and_never_retried(self):
        for index, stage in enumerate(("profile", "list", "get"), start=1):
            service = Service()
            service.failure = TimeoutError("PRIVATE fixture cancellation capability")
            service.failure_operation = stage
            result = self.lookup(GmailServiceConnector({BINDING.account: service}))
            self.assertEqual(result.error.code, "connector_failed")
            self.assertEqual(result.error.operation, stage)
            self.assertEqual(result.messages, ())
            self.assertNotIn("PRIVATE", repr(result))
            self.assertEqual(len(service.calls), index)
            self.assertTrue(all(call[2] == 0 for call in service.calls))


if __name__ == "__main__":
    unittest.main()
