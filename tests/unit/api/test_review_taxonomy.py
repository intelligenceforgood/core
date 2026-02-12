import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from i4g.api.app import app
from i4g.api.review import get_store
from i4g.store.review_store import ReviewStore
from i4g.store.sql import METADATA
from i4g.api.auth import require_token


@pytest.fixture
def temp_store(tmp_path):
    db_path = tmp_path / "test_review.db"
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    store = ReviewStore(session_factory=sf)
    return store


@pytest.fixture
def client(temp_store):
    app.dependency_overrides[get_store] = lambda: temp_store
    # Override auth to bypass token check if needed, or just provide a dummy token
    app.dependency_overrides[require_token] = lambda: {"username": "test_user", "roles": ["analyst"]}
    return TestClient(app)


def test_enqueue_with_taxonomy(client):
    payload = {
        "case_id": "CASE-123",
        "priority": "high",
        "classification": {
            "intent": [{"label": "INTENT.IMPOSTER", "confidence": 0.95}],
            "explanation": "This looks like an imposter scam.",
            "few_shot_examples": [{"text": "example 1", "label": "imposter"}],
        },
        "tags": ["scam", "urgent"],
    }

    response = client.post("/reviews/", json=payload)
    assert response.status_code == 200
    data = response.json()
    review_id = data["reviewId"]

    # Verify persistence
    response = client.get(f"/reviews/{review_id}")
    assert response.status_code == 200
    review = response.json()

    assert review["caseId"] == "CASE-123"
    # Extra fields (not defined on ReviewItemResponse) pass through with original snake_case names
    assert review["classification_result"]["intent"][0]["label"] == "INTENT.IMPOSTER"
    assert review["classification_result"]["explanation"] == "This looks like an imposter scam."
    assert review["tags"] == ["scam", "urgent"]
