"""Cloud state verification for the dev bootstrap workflow."""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from i4g.cli.bootstrap.common import VerificationReport, get_bundles
from i4g.settings import get_settings

from .constants import REPO_ROOT


def verify_cloud_state(args: argparse.Namespace) -> VerificationReport:
    """Verify state of cloud resources (Cloud SQL, Vertex, GCS)."""

    settings = get_settings()

    # Workaround: Manually load Cloud SQL settings from local TOML if missing
    if not settings.storage.cloudsql_instance:
        try:
            import tomllib

            local_conf = Path("config/settings.local.toml")
            if local_conf.exists():
                with open(local_conf, "rb") as f:
                    data = tomllib.load(f)
                    storage_conf = data.get("storage", {})
                    if "cloudsql_instance" in storage_conf:
                        settings.storage.cloudsql_instance = storage_conf["cloudsql_instance"]
                    if "cloudsql_database" in storage_conf:
                        settings.storage.cloudsql_database = storage_conf["cloudsql_database"]
        except Exception as e:
            logging.warning(f"Failed to apply local settings workaround: {e}")

    errors: list[str] = []

    # 1. GCS Bundles
    bundles_state: dict = {}
    try:
        from google.cloud import storage

        storage_client = storage.Client(project=args.project)
        bundles = get_bundles()

        for name, uri in bundles.items():
            if uri.startswith("gs://"):
                parts = uri[5:].split("/", 1)
                bucket_name = parts[0]
                prefix = parts[1] if len(parts) > 1 else ""

                bucket = storage_client.bucket(bucket_name)
                blob = bucket.blob(prefix)
                if blob.exists():
                    bundles_state[name] = {"exists": True, "size": blob.size, "uri": uri}
                else:
                    blobs = list(bucket.list_blobs(prefix=prefix, max_results=1))
                    if blobs:
                        bundles_state[name] = {"exists": True, "type": "directory", "uri": uri}
                    else:
                        bundles_state[name] = {"exists": False, "uri": uri}
    except Exception as exc:
        errors.append(f"GCS Bundle Check Failed: {exc}")

    # 2. Primary DB (SQLite if local_execution)
    storage_stats: dict = {}
    if getattr(args, "local_execution", False):
        sqlite_stats: dict = {}
        try:
            from sqlalchemy import create_engine, text

            db_path = Path(settings.storage.sqlite_path)
            if not db_path.is_absolute():
                db_path = REPO_ROOT / db_path

            if not db_path.exists():
                errors.append(f"SQLite DB not found at {db_path}")
            else:
                engine = create_engine(f"sqlite:///{db_path}")
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT COUNT(*) FROM cases"))
                    count = result.scalar()
                    sqlite_stats["cases"] = count
        except Exception as exc:
            errors.append(f"SQLite Check Failed: {exc}")
        storage_stats["sqlite"] = sqlite_stats

    # 3. Relational DB (Cloud SQL)
    cloud_sql_stats: dict = {}
    if settings.storage.structured_backend == "cloudsql" or not getattr(args, "local_execution", False):
        try:
            from sqlalchemy import text

            from i4g.store.sql import build_engine

            verify_settings = settings
            if verify_settings.storage.structured_backend != "cloudsql":
                verify_settings = settings.model_copy(
                    update={"storage": settings.storage.model_copy(update={"structured_backend": "cloudsql"})}
                )

            if not verify_settings.storage.cloudsql_instance:
                verify_settings.storage.cloudsql_instance = os.getenv("I4G_APP__CLOUDSQL__INSTANCE") or os.getenv(
                    "CLOUDSQL_INSTANCE"
                )

            if not verify_settings.storage.cloudsql_user:
                verify_settings.storage.cloudsql_user = os.getenv("I4G_APP__CLOUDSQL__USER") or os.getenv(
                    "CLOUDSQL_USER"
                )

            if not verify_settings.storage.cloudsql_password:
                verify_settings.storage.cloudsql_password = os.getenv("I4G_APP__CLOUDSQL__PASSWORD") or os.getenv(
                    "CLOUDSQL_PASSWORD"
                )
            if not verify_settings.storage.cloudsql_database:
                verify_settings.storage.cloudsql_database = os.getenv("I4G_APP__CLOUDSQL__DATABASE") or os.getenv(
                    "CLOUDSQL_DATABASE"
                )
                if not verify_settings.storage.cloudsql_database and "dev" in args.project:
                    verify_settings.storage.cloudsql_database = "i4g_db"

            logging.info(
                "Cloud SQL Verify: instance=%s, user=%s, db=%s",
                verify_settings.storage.cloudsql_instance,
                verify_settings.storage.cloudsql_user,
                verify_settings.storage.cloudsql_database,
            )

            if not all(
                [
                    verify_settings.storage.cloudsql_instance,
                    verify_settings.storage.cloudsql_user,
                    verify_settings.storage.cloudsql_database,
                ]
            ):
                cloud_sql_stats["status"] = "skipped (missing I4G_APP__CLOUDSQL__* env vars)"
            else:
                engine = build_engine(settings=verify_settings)
                with engine.connect() as conn:
                    tables_result = conn.execute(
                        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
                    )
                    tables = [row[0] for row in tables_result]

                    for table in tables:
                        try:
                            if table == "alembic_version":
                                version_result = conn.execute(text(f"SELECT version_num FROM {table} LIMIT 1"))
                                cloud_sql_stats[table] = version_result.scalar()
                            else:
                                count_result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                                cloud_sql_stats[table] = count_result.scalar()
                        except Exception as e:
                            cloud_sql_stats[table] = -1
                            logging.warning(f"Failed to count table {table}: {e}")
        except Exception as exc:
            errors.append(f"Cloud SQL Check Failed: {exc}")
    storage_stats["cloud_sql"] = cloud_sql_stats

    # 4. Vector Store (Vertex AI Search)
    vector_store_stats: dict = {}
    try:
        from google.cloud import discoveryengine_v1beta as discoveryengine

        data_store_id = args.search_data_store_id or settings.vector.vertex_ai_data_store
        serving_config_id = (
            args.search_serving_config_id or os.getenv("I4G_VECTOR__VERTEX_AI_SERVING_CONFIG") or "default_search"
        )
        location = args.search_location or settings.vector.vertex_ai_location or "global"

        if data_store_id:
            client = discoveryengine.SearchServiceClient()
            serving_config = client.serving_config_path(
                project=args.project,
                location=location,
                data_store=data_store_id,
                serving_config=serving_config_id,
            )

            request = discoveryengine.SearchRequest(
                serving_config=serving_config,
                query="",
                page_size=0,
            )
            response = client.search(request=request)
            vector_store_stats = {
                "total_size": response.total_size,
                "data_store_id": data_store_id,
            }
        else:
            vector_store_stats = {"status": "skipped", "reason": "No data store ID"}

    except Exception as exc:
        errors.append(f"Vertex Search Check Failed: {exc}")

    storage_stats["vector_store"] = vector_store_stats

    return VerificationReport(
        environment="dev",
        timestamp=datetime.now(UTC).isoformat(),
        bundles=bundles_state,
        storage=storage_stats,
        smoke_tests={},
        errors=errors,
    )
