#!/usr/bin/env python3
"""
Seed the SQLite database with the "static mock" cases defined in api/cases.py.
This allows the UI to work against the "Real DB" (Phase 2) immediately.

Usage:
    cd core
    python scripts/seed_cases.py
"""

import sys
import json
import uuid
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Fix python path to include src
sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

from i4g.api.cases import CASES_RESPONSE
from i4g.services.factories import build_review_store, build_structured_store
from i4g.store.schema import ScamRecord
from i4g.store.review_store import ReviewStore


def seed_data():
    review_store = build_review_store()
    struct_store = build_structured_store()

    print(f"Seeding data into ReviewStore: {review_store.db_path}...")

    # 1. Ensure queues exist/metadata?
    # ReviewStore doesn't maintain queues independent of items statuses, but CASES_RESPONSE has "queues".
    # We ignore the "queues" list for now as it's metadata.

    for case_data in CASES_RESPONSE["cases"]:
        case_id = case_data["id"]

        # Check if exists
        existing_rev = review_store.get_cases([case_id])
        if existing_rev:
            print(f"Skipping {case_id} (already exists)")
            continue

        print(f"Upserting {case_id}...")

        # --- Structured Record (Content) ---
        # Derive entities for graph
        entities = {
            "person": ["Subject A", "Subject B"],
            "account": ["Account 123", "Account 456"],
            "transaction": ["Txn 777", "Txn 888"],
        }

        props = {
            "title": case_data["title"],
            "progress": case_data.get("progress"),
            "dueAt": case_data.get("dueAt"),
            "queue": case_data.get("queue"),
            "files": (
                [
                    {
                        "name": "Suspicious Transaction Report.pdf",
                        "type": "document",
                        "url": "/api/artifacts/mock/doc1",
                        "size": "1.2MB",
                    },
                    {
                        "name": "Check Screenshot.png",
                        "type": "image",
                        "url": "/api/artifacts/mock/img1",
                        "size": "450KB",
                    },
                ]
                if case_id == "case-482"
                else []
            ),
        }

        record = ScamRecord(
            case_id=case_id,
            text=f"INVESTIGATION REPORT: {case_data['title']}.\n\nThis case involves potential {case_data.get('priority')} priority activity. The subject has been flagged in queue '{case_data.get('queue')}'.\n\nAutomated extraction found multiple entities.",
            entities=entities,
            classification=case_data.get("tags", ["unknown"])[0] if case_data.get("tags") else "unknown",
            confidence=0.85,
            classification_result={"label": "fraud", "score": 0.85},
            tags=case_data.get("tags", []),
            created_at=datetime.now(timezone.utc),
            metadata=props,
        )

        struct_store.upsert_record(record)

        # --- Review Queue (State) ---
        review_id = review_store.enqueue_case(
            case_id=case_id,
            priority=case_data["priority"],
            tags=case_data.get("tags", []),
            classification_result=record.classification_result,
        )

        # Manually update fields that enqueue_case doesn't support directly (status, assignee, last_updated)
        # We need raw SQL access for this helper script
        with review_store._connect() as conn:
            # Update status, assignee, last_updated
            updated_at = case_data.get("updatedAt") or datetime.now(timezone.utc).isoformat()

            conn.execute(
                """
                UPDATE review_queue 
                SET status = ?, assigned_to = ?, last_updated = ?
                WHERE review_id = ?
                """,
                (case_data["status"], case_data.get("assignee"), updated_at, review_id),
            )

            # --- Timeline (Review Actions) ---
            # 1. System creation
            conn.execute(
                """
                INSERT INTO review_actions (action_id, review_id, actor, action, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    review_id,
                    "system",
                    "system",
                    "Case ingested from seed script",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

            # 2. Analyst assignment (fake)
            if case_data.get("assignee"):
                conn.execute(
                    """
                    INSERT INTO review_actions (action_id, review_id, actor, action, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        review_id,
                        "admin",
                        "assign",
                        f"Assigned to {case_data['assignee']}",
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    print("Seeding complete.")


if __name__ == "__main__":
    seed_data()
