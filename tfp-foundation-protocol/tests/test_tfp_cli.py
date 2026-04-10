import json

from tfp_cli.main import main


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_cli_publish(monkeypatch, capsys):
    def fake_post(url, json, timeout):  # noqa: A002
        assert url.endswith("/api/publish")
        assert json["title"] == "Demo"
        return FakeResponse(200, {"root_hash": "abc", "status": "broadcasting"})

    monkeypatch.setattr("tfp_cli.main.httpx.post", fake_post)
    code = main(["publish", "--title", "Demo", "--text", "Hello", "--tags", "demo"])
    assert code == 0
    assert '"root_hash": "abc"' in capsys.readouterr().out


def test_cli_get_error(monkeypatch, capsys):
    def fake_get(url, params, timeout):
        assert "/api/get/" in url
        return FakeResponse(402, {"detail": "earn credits first"})

    monkeypatch.setattr("tfp_cli.main.httpx.get", fake_get)
    code = main(["get", "missing-hash"])
    assert code == 1
    assert '"status_code": 402' in capsys.readouterr().out
