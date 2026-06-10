from xcode_cli.qqchat.auth import QQAuthClient


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.responses = []

    def push(self, payload, status=200):
        self.responses.append((status, payload))

    def post_json(self, url, payload, headers=None, timeout=10):
        self.calls.append((url, payload, headers or {}, timeout))
        status, body = self.responses.pop(0)
        return status, body


def test_get_token_posts_app_credentials():
    transport = FakeTransport()
    transport.push({"access_token": "token-1", "expires_in": 7200})
    clock = FakeClock()
    client = QQAuthClient("app-id", "secret", transport=transport, now=clock)

    token = client.get_access_token()

    assert token == "token-1"
    assert transport.calls[0][0] == "https://bots.qq.com/app/getAppAccessToken"
    assert transport.calls[0][1] == {"appId": "app-id", "clientSecret": "secret"}


def test_get_token_reuses_cache_until_near_expiry():
    transport = FakeTransport()
    transport.push({"access_token": "token-1", "expires_in": 7200})
    clock = FakeClock()
    client = QQAuthClient("app-id", "secret", transport=transport, now=clock)

    assert client.get_access_token() == "token-1"
    clock.value += 100
    assert client.get_access_token() == "token-1"

    assert len(transport.calls) == 1


def test_get_token_refreshes_when_less_than_60_seconds_left():
    transport = FakeTransport()
    transport.push({"access_token": "token-1", "expires_in": 120})
    transport.push({"access_token": "token-2", "expires_in": 7200})
    clock = FakeClock()
    client = QQAuthClient("app-id", "secret", transport=transport, now=clock)

    assert client.get_access_token() == "token-1"
    clock.value += 80
    assert client.get_access_token() == "token-2"

    assert len(transport.calls) == 2


def test_auth_error_does_not_leak_secret():
    transport = FakeTransport()
    transport.push({"error": "bad super-secret Authorization"}, status=401)
    client = QQAuthClient("app-id", "super-secret", transport=transport, now=FakeClock())

    try:
        client.get_access_token()
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "super-secret" not in message
    assert "Authorization" not in message
    assert "401" in message
