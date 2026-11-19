import pytest
from fastapi.testclient import TestClient

from app.main import app

pytest_plugins = ["gates.pytest_ac"]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
