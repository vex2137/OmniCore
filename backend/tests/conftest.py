import pytest
from fastapi.testclient import TestClient

from omnicore.app import create_app
from omnicore.config import RuntimeConfig


@pytest.fixture
def config(tmp_path):
    return RuntimeConfig(data_dir=tmp_path / "data")


@pytest.fixture
def app(config):
    return create_app(config)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://localhost") as client:
        yield client
