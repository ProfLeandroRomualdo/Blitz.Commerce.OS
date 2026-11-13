import os
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_API_KEY", "blitz-demo-key")
    from app import main
    monkeypatch.setattr(main, "DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.setattr(main, "SEED_KEY", "blitz-demo-key")
    with TestClient(main.app) as c:
        yield c

@pytest.fixture
def headers():
    return {"X-API-Key": "blitz-demo-key"}
