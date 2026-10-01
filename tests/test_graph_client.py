from datetime import datetime, timezone

import pytest

from briefing.graph_client import GraphClient, GraphError


class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, params=None, **kwargs):
        self.calls.append({"method": method, "url": url, "params": params, "headers": headers})
        return self.responses.pop(0)


def _client(responses):
    session = FakeSession(responses)
    sleeps = []
    client = GraphClient(lambda: "tok", session=session, sleep=sleeps.append)
    return client, session, sleeps


def test_retries_on_429_using_retry_after():
    client, session, sleeps = _client(
        [FakeResponse(429, headers={"Retry-After": "3"}), FakeResponse(200, {"value": [{"id": 1}]})]
    )
    out = client.unread_messages(datetime(2026, 9, 29, tzinfo=timezone.utc))
    assert out == [{"id": 1}]
    assert sleeps == [3.0]
    assert session.calls[0]["headers"]["Authorization"] == "Bearer tok"


def test_follows_next_link_and_respects_limit():
    client, session, _ = _client(
        [
            FakeResponse(
                200,
                {
                    "value": [{"id": 1}, {"id": 2}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/next",
                },
            ),
            FakeResponse(200, {"value": [{"id": 3}, {"id": 4}]}),
        ]
    )
    out = client.unread_messages(datetime(2026, 9, 29, tzinfo=timezone.utc), limit=3)
    assert [m["id"] for m in out] == [1, 2, 3]
    assert session.calls[1]["url"].endswith("/next")
    assert session.calls[1]["params"] is None


def test_filter_uses_utc_and_unread():
    client, session, _ = _client([FakeResponse(200, {"value": []})])
    client.unread_messages(datetime(2026, 9, 29, 1, 0, tzinfo=timezone.utc))
    f = session.calls[0]["params"]["$filter"]
    assert f == "receivedDateTime ge 2026-09-29T01:00:00Z and isRead eq false"


def test_raises_on_client_error_without_retry():
    client, session, sleeps = _client([FakeResponse(403, {"error": "Forbidden"})])
    with pytest.raises(GraphError) as exc:
        client.me()
    assert exc.value.status == 403
    assert sleeps == [] and len(session.calls) == 1


def test_calendar_drops_cancelled():
    client, _, _ = _client(
        [FakeResponse(200, {"value": [{"id": 1}, {"id": 2, "isCancelled": True}]})]
    )
    start = datetime(2026, 9, 29, tzinfo=timezone.utc)
    assert client.events_between(start, start) == [{"id": 1}]
