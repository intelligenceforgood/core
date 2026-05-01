import json
from pathlib import Path

import pytest

from i4g.ingestion.phishdestroy.actors import ingest_actors
from i4g.store.actor_identity_edge_store import ActorIdentityEdgeStore
from i4g.store.actor_identity_store import ActorIdentityStore
from i4g.store.leak_record_store import LeakRecordStore
from i4g.store.registrant_pivot_store import RegistrantPivotStore
from i4g.store.threat_actor_store import ThreatActorStore


@pytest.fixture
def dummy_data(tmp_path):
    data_path = tmp_path / "data.json"
    registrants_path = tmp_path / "registrants.json"

    data = {
        "emails": [
            {
                "email": "scammer@example.com",
                "leak_info": {"fullname": "John Doe"},
                "passwords": [{"password": "secretpassword", "source": "SomeBreach"}],
            },
            {"email": "scammer2@example.com", "google": {"fullname": "Jane Doe"}},
        ]
    }

    registrants = [
        {"actor": "scammer@example.com", "domain": "fake-bank.com", "name": "John Doe", "phone": "555-1234"},
        {"actor": "scammer2@example.com", "domain": "fake-bank.com", "name": "Jane Doe", "phone": "555-9999"},
    ]

    with open(data_path, "w") as f:
        json.dump(data, f)
    with open(registrants_path, "w") as f:
        json.dump(registrants, f)

    return data_path


def test_ingest_actors(
    tmp_path,
    dummy_data: Path,
):
    db_path = str(tmp_path / "test.db")
    threat_actor_store = ThreatActorStore(db_path=db_path)
    actor_identity_store = ActorIdentityStore(db_path=db_path)
    leak_record_store = LeakRecordStore(db_path=db_path)
    registrant_pivot_store = RegistrantPivotStore(db_path=db_path)
    actor_identity_edge_store = ActorIdentityEdgeStore(db_path=db_path)

    # Run first ingestion
    ingest_actors(
        data_path=dummy_data,
        commit_sha="dummy-sha",
        ingest_job="test-job",
        ingest_job_run_id=None,
        threat_actor_store=threat_actor_store,
        actor_identity_store=actor_identity_store,
        leak_record_store=leak_record_store,
        registrant_pivot_store=registrant_pivot_store,
        actor_identity_edge_store=actor_identity_edge_store,
    )

    # Get DB state lengths
    with threat_actor_store._session_factory() as session:
        import sqlalchemy as sa

        from i4g.store import sql as sql_schema

        actors_count = session.execute(sa.select(sa.func.count(sql_schema.threat_actors.c.actor_id))).scalar()
        leaks_count = session.execute(sa.select(sa.func.count(sql_schema.leak_records.c.leak_id))).scalar()
        pivots_count = session.execute(sa.select(sa.func.count(sql_schema.registrant_pivots.c.pivot_id))).scalar()
        edges_count = session.execute(sa.select(sa.func.count(sql_schema.actor_identity_edges.c.edge_id))).scalar()

    assert actors_count == 2
    assert leaks_count == 1
    assert pivots_count == 5
    assert edges_count == 1

    # Idempotency check: run second ingestion
    ingest_actors(
        data_path=dummy_data,
        commit_sha="dummy-sha",
        ingest_job="test-job",
        ingest_job_run_id=None,
        threat_actor_store=threat_actor_store,
        actor_identity_store=actor_identity_store,
        leak_record_store=leak_record_store,
        registrant_pivot_store=registrant_pivot_store,
        actor_identity_edge_store=actor_identity_edge_store,
    )

    with threat_actor_store._session_factory() as session:
        actors_count2 = session.execute(sa.select(sa.func.count(sql_schema.threat_actors.c.actor_id))).scalar()
        leaks_count2 = session.execute(sa.select(sa.func.count(sql_schema.leak_records.c.leak_id))).scalar()
        pivots_count2 = session.execute(sa.select(sa.func.count(sql_schema.registrant_pivots.c.pivot_id))).scalar()
        edges_count2 = session.execute(sa.select(sa.func.count(sql_schema.actor_identity_edges.c.edge_id))).scalar()

    assert actors_count2 == actors_count
    assert leaks_count2 == leaks_count
    assert pivots_count2 == pivots_count
    assert edges_count2 == edges_count
