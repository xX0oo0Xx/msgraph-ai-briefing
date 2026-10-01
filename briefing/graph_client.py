from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
RETRYABLE_STATUS = {429, 502, 503, 504}

MESSAGE_FIELDS = "id,subject,from,receivedDateTime,bodyPreview,importance,hasAttachments"
EVENT_FIELDS = "id,subject,start,end,location,organizer,isAllDay,isOnlineMeeting,isCancelled"


class GraphError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Graph API error {status}: {body}")
        self.status = status


def _graph_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GraphClient:
    def __init__(
        self,
        token_provider: Callable[[], str],
        outlook_timezone: str = "Pacific Standard Time",
        session: requests.Session | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._token = token_provider
        self._tz = outlook_timezone
        self._session = session or requests.Session()
        self._max_retries = max_retries
        self._sleep = sleep
        self.request_count = 0

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        if not url.startswith("https://"):
            url = GRAPH_BASE + url
        extra_headers = kwargs.pop("headers", {})
        for attempt in range(self._max_retries + 1):
            headers = {
                "Authorization": f"Bearer {self._token()}",
                "Prefer": f'outlook.timezone="{self._tz}"',
                **extra_headers,
            }
            self.request_count += 1
            resp = self._session.request(method, url, headers=headers, timeout=30, **kwargs)
            if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                self._sleep(min(delay, 60))
                continue
            if resp.status_code >= 400:
                raise GraphError(resp.status_code, resp.text[:500])
            return resp
        raise GraphError(resp.status_code, resp.text[:500])

    def _get_paged(self, url: str, params: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        next_params: dict[str, Any] | None = params
        while next_url and len(items) < limit:
            data = self._request("GET", next_url, params=next_params).json()
            items.extend(data.get("value", []))
            next_url = data.get("@odata.nextLink")
            next_params = None
        return items[:limit]

    def me(self) -> dict[str, Any]:
        return self._request(
            "GET", "/me", params={"$select": "displayName,mail,userPrincipalName"}
        ).json()

    def unread_messages(self, since: datetime, limit: int = 25) -> list[dict[str, Any]]:
        # Graph requires the $orderby property to also appear first in $filter.
        params = {
            "$filter": f"receivedDateTime ge {_graph_utc(since)} and isRead eq false",
            "$orderby": "receivedDateTime desc",
            "$select": MESSAGE_FIELDS,
            "$top": min(limit, 50),
        }
        return self._get_paged("/me/mailFolders/inbox/messages", params, limit)

    def events_between(
        self, start: datetime, end: datetime, limit: int = 50
    ) -> list[dict[str, Any]]:
        params = {
            "startDateTime": start.isoformat(),
            "endDateTime": end.isoformat(),
            "$select": EVENT_FIELDS,
            "$orderby": "start/dateTime",
            "$top": min(limit, 50),
        }
        events = self._get_paged("/me/calendarView", params, limit)
        return [e for e in events if not e.get("isCancelled")]

    def send_mail(self, to: str, subject: str, html_body: str) -> None:
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html_body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }
        self._request("POST", "/me/sendMail", json=payload)
