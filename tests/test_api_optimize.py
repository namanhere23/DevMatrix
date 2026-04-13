from fastapi.testclient import TestClient

import api_server


class StubOptimizer:
    def optimize(self, prompt: str):
        return {
            "optimized_prompt": "Create a small FastAPI todo API with tests and docs.",
            "extracted_requirements": ["FastAPI", "tests"],
            "assumptions": ["Python backend is preferred."],
            "scope_notes": ["Keep the response backend-oriented."],
        }


def test_optimize_endpoint_success(monkeypatch):
    monkeypatch.setattr("nexussentry.agents.optimizer.OptimizerAgent", StubOptimizer)
    client = TestClient(api_server.app)

    response = client.post("/api/optimize", json={"prompt": "make a todo app"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert "optimized_prompt" in payload["result"]
    assert "provider" not in payload["result"]
    assert "provider_selected" not in payload["result"]
    assert "original_prompt" not in payload["result"]


def test_optimize_endpoint_rejects_empty_prompt():
    client = TestClient(api_server.app)

    response = client.post("/api/optimize", json={"prompt": "   "})
    assert response.status_code == 400
    assert response.json()["detail"] == "Prompt cannot be empty"
