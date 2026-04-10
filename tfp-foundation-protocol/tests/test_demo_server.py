from fastapi.testclient import TestClient

from tfp_demo.server import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["content_items"] >= 1


def test_publish_and_get_requires_credits():
    with TestClient(app) as client:
        publish = client.post(
            "/api/publish",
            json={"title": "Demo", "text": "Hello network", "tags": ["demo"]},
        )
        assert publish.status_code == 200
        root_hash = publish.json()["root_hash"]

        denied = client.get(f"/api/get/{root_hash}", params={"device_id": "tester"})
        assert denied.status_code == 402

        earn = client.post("/api/earn", json={"device_id": "tester", "task_id": "task-1"})
        assert earn.status_code == 200
        assert earn.json()["credits_earned"] == 10

        ok = client.get(f"/api/get/{root_hash}", params={"device_id": "tester"})
        assert ok.status_code == 200
        body = ok.json()
        assert body["text"] == "Hello network"
        assert body["root_hash"] == root_hash
