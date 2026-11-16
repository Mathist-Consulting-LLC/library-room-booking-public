"""Optional adapter for caller-created Gmail services; no SDK or credentials."""
from types import MappingProxyType
from typing import Mapping

from .email import ConnectorFailure


class _BundledGmailServiceConnector:
    """Bind opaque account handles to already authorized, read-only services.

    The caller creates/configures services, including resource limits, deadlines,
    credential refresh and redacted diagnostics. No account fallback is allowed.
    The service must implement the Gmail discovery client's read-side shape.
    """

    def __init__(self, services: Mapping[str, object]):
        self._services = MappingProxyType(dict(services))

    def _users(self, account: str):
        try:
            service = self._services[account]
        except (KeyError, TypeError):
            raise ConnectorFailure("authentication_required") from None
        return service.users()

    def profile(self, *, account: str) -> dict:
        return self._users(account).getProfile(userId="me").execute(num_retries=0)

    def list_messages(self, *, account: str, query: str,
                      page_token: str | None, max_results: int) -> dict:
        return self._users(account).messages().list(
            userId="me", q=query, pageToken=page_token,
            maxResults=max_results,
        ).execute(num_retries=0)

    def get_message(self, *, account: str, message_id: str) -> dict:
        return self._users(account).messages().get(
            userId="me", id=message_id, format="full",
        ).execute(num_retries=0)


class GmailServiceConnector(_BundledGmailServiceConnector):
    """Preserve the booking import path and delegate to the optional connector."""

    def __init__(self, services: Mapping[str, object]):
        try:
            from mathist_gmail_connector import ConnectorFailure as GmailFailure
            from mathist_gmail_connector import GmailServiceConnector as StandaloneConnector
        except ModuleNotFoundError as exc:
            if exc.name != "mathist_gmail_connector":
                raise
            super().__init__(services)
            self._standalone = None
        else:
            self._standalone = StandaloneConnector(services)
            self._standalone_failure = GmailFailure

    def profile(self, *, account: str) -> dict:
        if self._standalone is None:
            return super().profile(account=account)
        return self._call(self._standalone.profile, account=account)

    def list_messages(self, *, account: str, query: str,
                      page_token: str | None, max_results: int) -> dict:
        if self._standalone is None:
            return super().list_messages(account=account, query=query,
                                         page_token=page_token, max_results=max_results)
        return self._call(self._standalone.list_messages, account=account, query=query,
                          page_token=page_token, max_results=max_results)

    def get_message(self, *, account: str, message_id: str) -> dict:
        if self._standalone is None:
            return super().get_message(account=account, message_id=message_id)
        return self._call(self._standalone.get_message, account=account, message_id=message_id)

    def _call(self, method, **kwargs):
        try:
            return method(**kwargs)
        except self._standalone_failure as exc:
            raise ConnectorFailure(exc.code) from None
