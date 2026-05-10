"""
InfoShare API Tests
Run: pytest tests/ -v
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Mock DB + Blob so tests run without Azure credentials ─────────────────
@pytest.fixture(autouse=True)
def mock_azure(monkeypatch):
    monkeypatch.setenv("AZURE_SQL_SERVER",   "mock")
    monkeypatch.setenv("AZURE_SQL_DATABASE", "mock")
    monkeypatch.setenv("AZURE_SQL_USER",     "mock")
    monkeypatch.setenv("AZURE_SQL_PASSWORD", "mock")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "mock")
    monkeypatch.setenv("AZURE_CONTAINER_NAME", "test")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_SECRET", "test-admin-secret")


def make_client():
    """Import app after env vars are set."""
    with patch("main.get_db_connection"), \
         patch("main.init_db"):
        from main import app
        return TestClient(app)


def test_health():
    client = make_client()
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["app"] == "InfoShare"


def test_openapi_docs():
    client = make_client()
    r = client.get("/docs")
    assert r.status_code == 200


def test_login_wrong_credentials():
    with patch("main.get_db_connection") as mock_conn:
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        mock_conn.return_value.__enter__ = MagicMock(return_value=MagicMock(cursor=lambda: cursor))
        mock_conn.return_value.cursor.return_value = cursor
        mock_conn.return_value.close = MagicMock()

        client = make_client()
        r = client.post("/api/auth/login", data={"username":"wrong","password":"wrong"})
        assert r.status_code == 401


def test_upload_requires_auth():
    client = make_client()
    r = client.post("/api/photos/upload",
                    data={"title":"Test"},
                    files={"file": ("test.jpg", b"fake", "image/jpeg")})
    assert r.status_code == 403


def test_list_photos_public():
    with patch("main.get_db_connection") as mock_conn:
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        mock_conn.return_value.cursor.return_value = cursor
        mock_conn.return_value.close = MagicMock()

        client = make_client()
        r = client.get("/api/photos")
        assert r.status_code == 200
        assert "photos" in r.json()


def test_stats_public():
    with patch("main.get_db_connection") as mock_conn:
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(5,), (10,), (100,), (30,)]
        mock_conn.return_value.cursor.return_value = cursor
        mock_conn.return_value.close = MagicMock()

        client = make_client()
        r = client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_photos"   in data
        assert "total_users"    in data
        assert "total_views"    in data
        assert "total_comments" in data


def test_create_admin_wrong_secret():
    client = make_client()
    r = client.post("/api/auth/create-admin",
                    data={"username":"a","email":"a@a.com","password":"p","admin_secret":"wrong"})
    assert r.status_code == 403


def test_rate_requires_auth():
    client = make_client()
    r = client.post("/api/photos/some-id/rate", data={"score": 4})
    assert r.status_code == 403


def test_comment_requires_auth():
    client = make_client()
    r = client.post("/api/photos/some-id/comments", data={"content": "Nice!"})
    assert r.status_code == 403
