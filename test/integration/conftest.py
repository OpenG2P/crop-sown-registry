"""Run the Crop Sown extension through the registry platform's activity services on a real PostgreSQL.

Needs the registry-platform core and this extension installed in the
environment, openg2p-data checked out beside this repo (or $OPENG2P_DATA_DIR),
and a disposable database:

    docker run -d --name csr-pg -e POSTGRES_PASSWORD=postgres -p 55432:5432 postgres:16
    docker exec csr-pg psql -U postgres -c "create database csr_test"
    CSR_TEST_DB_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/csr_test pytest test/integration

The public schema is dropped and rebuilt from the platform migration plus this
extension's seed SQL — the same order the Helm install uses (APIs migrate, then
db-seed runs the SQL). Code lists are read from Master Data, not the registry:
the Master Data engine points at this same database, which gets Master Data's
two code-list tables filled from the ETH pack (core lists + agriculture domain),
exactly what Master Data loads.
"""

import importlib
import json
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.modules["openg2p_registry_extensions"] = importlib.import_module("openg2p_registry_crop_sown_extension")
sys.modules["openg2p_registry_extensions.register_domain.models"] = importlib.import_module(
    "openg2p_registry_crop_sown_extension.register_domain.models"
)
sys.modules["openg2p_registry_extensions.register_domain.services"] = importlib.import_module(
    "openg2p_registry_crop_sown_extension.register_domain.services"
)

from openg2p_fastapi_common.context import dbengine  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from master_data_pack import load_geography, load_lists, pack_dir  # noqa: E402

DB_URL = os.environ.get("CSR_TEST_DB_URL", "postgresql+asyncpg://postgres:postgres@localhost:55432/csr_test")
META = Path(__file__).resolve().parents[2] / "crop-sown-extension/src/openg2p_registry_crop_sown_extension/meta_data"

SEED_DIRS = ["register-metadata", "activity-metadata", "data-models", "registry-outbound-messages-templates",
             "reporting-views", "awe-integration"]


async def _prepare():
    pack = pack_dir()
    if pack is None:
        return None
    engine = create_async_engine(DB_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except Exception:
        await engine.dispose()
        return None
    dbengine.set(engine)
    import openg2p_registry_core.engine as registry_engine

    registry_engine._engines = {"db_engine_master_data": engine}

    from openg2p_registry_core import app as core_app
    from openg2p_registry_core.models import (
        DataModel, G2PActivityContext, G2PActivityIdempotencyKey, G2PActivityIndicator, G2PActivityOdkFailure,
        G2PActivityOdkForm, G2PActivityOutbox, G2PActivityPeriodLock, G2PActivityTemporaryReference,
        G2PActivityType, G2PRegisterDefinition, G2PRegistryDocument, OutgoingTemplate,
        G2PActivityTypeSchema, G2PActivityEnrichment, G2PActivityAggregate, G2PActivityAggregateHistory,
        G2PActivityParticipant,
    )

    for model in (G2PRegisterDefinition, G2PActivityType, G2PActivityContext, G2PActivityPeriodLock,
                  G2PActivityIdempotencyKey, G2PActivityOutbox, G2PActivityTemporaryReference, G2PActivityIndicator,
                  G2PActivityOdkForm, G2PActivityOdkFailure, DataModel, G2PRegistryDocument, OutgoingTemplate,
                  G2PActivityTypeSchema, G2PActivityEnrichment, G2PActivityAggregate, G2PActivityAggregateHistory,
                  G2PActivityParticipant):
        await model.create_migrate()
    await core_app.migrate_activity_core_tables()
    await core_app.migrate_activity_tables()

    # The Cluster entity register: the metadata tables its seed SQL fills, and its
    # own tables, created by the extension's migrate_database.
    from openg2p_registry_core.models import (
        G2PIntakeFormDefinition, G2PIntakeFormUITab, G2PIntakeFormUITabSection, G2PRegisterSchema,
        G2PRegisterSection, G2PRegisterUITab, G2PRegisterUITabSection, G2PRegistryAwePolicyConfiguration,
    )
    from openg2p_registry_crop_sown_extension.register_domain.models import (
        G2PIntakeFormCluster, G2PRegisterCluster, G2PRegisterHistoryCluster,
    )

    for model in (G2PRegisterSchema, G2PRegisterSection, G2PRegisterUITab, G2PRegisterUITabSection,
                  G2PIntakeFormDefinition, G2PIntakeFormUITab, G2PIntakeFormUITabSection,
                  G2PRegistryAwePolicyConfiguration,
                  G2PRegisterCluster, G2PRegisterHistoryCluster, G2PIntakeFormCluster):
        await model.create_migrate()

    async with engine.begin() as conn:
        # Master Data's code-list tables (master-data-service scripts/migrations/002_codelists.sql).
        await conn.execute(text("CREATE TABLE g2p_attributes (attribute_id varchar PRIMARY KEY, "
                                "attribute_code varchar, attribute_display varchar, is_hierarchical boolean)"))
        await conn.execute(text("CREATE TABLE g2p_attribute_values (value_id varchar NOT NULL, attribute_id varchar "
                                "NOT NULL, value_code varchar, value_display varchar, parent_value_id varchar, "
                                "sort_order integer, PRIMARY KEY (attribute_id, value_id))"))
        for code, doc in load_lists(pack).items():
            await conn.execute(text("INSERT INTO g2p_attributes VALUES (:a, :c, :d, :h)"),
                               {"a": doc["attribute_id"], "c": code, "d": doc.get("attribute_display"),
                                "h": bool(doc.get("is_hierarchical"))})
            for v in doc["values"]:
                await conn.execute(text("INSERT INTO g2p_attribute_values VALUES (:id, :a, :c, :d, :p, :o)"),
                                   {"id": v["value_id"], "a": doc["attribute_id"], "c": v.get("value_code"),
                                    "d": v.get("value_display"), "p": v.get("parent_value_id"),
                                    "o": v.get("sort_order")})
        # Master Data's geography tables, with the ETH pack's 1271 units.
        await conn.execute(text("CREATE TABLE g2p_geo_levels (level_id varchar PRIMARY KEY, "
                                "level_mnemonic varchar, parent_level_id varchar)"))
        await conn.execute(text("CREATE TABLE g2p_geo_level_values (level_value_id varchar PRIMARY KEY, "
                                "level_id varchar, level_value_mnemonic varchar, parent_level_value_id varchar)"))
        levels, units = load_geography(pack)
        await conn.execute(text("INSERT INTO g2p_geo_levels VALUES (:level_id, :level_mnemonic, :parent_level_id)"),
                           levels)
        await conn.execute(
            text("INSERT INTO g2p_geo_level_values VALUES "
                 "(:level_value_id, :level_id, :level_value_mnemonic, :parent_level_value_id)"),
            [{k: u[k] for k in ("level_value_id", "level_id", "level_value_mnemonic", "parent_level_value_id")}
             for u in units],
        )
        # Master Data's sample people (the pack's samples/individuals.json), the source of sample crop seasons.
        await conn.execute(text("CREATE TABLE g2p_sample_individuals (individual_id varchar PRIMARY KEY, "
                                "age integer, national_id varchar, geo_pcode varchar)"))
        people = json.loads((pack / "samples" / "individuals.json").read_text())
        await conn.execute(
            text("INSERT INTO g2p_sample_individuals VALUES (:individual_id, :age, :national_id, :geo_pcode)"),
            [{k: p.get(k) for k in ("individual_id", "age", "national_id", "geo_pcode")} for p in people],
        )
        raw = (await conn.get_raw_connection()).driver_connection  # asyncpg: multi-statement like psql
        for directory in SEED_DIRS:
            for path in sorted((META / directory).glob("*.sql")):
                await raw.execute(path.read_text())
    return engine


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database():
    engine = await _prepare()
    if engine is None:
        pytest.skip(f"PostgreSQL not reachable at {DB_URL}, or openg2p-data not found (OPENG2P_DATA_DIR)")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def clean(database):
    async with database.begin() as conn:
        for table in ("g2p_activity_crop_sown", "g2p_activity_projection_crop_sown", "g2p_activity_contexts",
                      "g2p_activity_idempotency_keys", "g2p_activity_outbox", "g2p_activity_period_locks",
                      "g2p_activity_temporary_references", "g2p_activity_enrichments", "g2p_activity_aggregates",
                      "g2p_activity_aggregate_history", "g2p_activity_participants"):
            await conn.execute(text(f"TRUNCATE {table}"))
    yield


@pytest.fixture
def service(database):
    from openg2p_registry_core.services import G2PActivityService

    svc = G2PActivityService()
    svc.references._cache._values.clear()
    return svc
