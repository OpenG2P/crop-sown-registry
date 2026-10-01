"""Typed participants, a changed crop replacing its season, and the sample crop seasons."""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from openg2p_registry_core.schemas.activity import ActivityInput, SearchActivitiesPayload
from openg2p_registry_crop_sown_extension.register_domain.models import G2PRegisterCluster

pytestmark = pytest.mark.asyncio(loop_scope="session")

REG = "CropSown"
BASE = {"farmer_id": "FR-0001", "plot_id": "LAND-0001-1", "crop_year": 2019, "season": "SEASON_MEHER",
        "crop": "CROP_TEFF", "geo_lowest_level_value_id": "ET010101"}
CLUSTER_IDS = ("CL-ET0406-001", "CL-ET0101-001")


def act(activity_type, days_ago, key=None, **payload):
    return ActivityInput(register_mnemonic=REG, activity_type=activity_type, idempotency_key=key,
                         occurred_at=datetime.utcnow().replace(microsecond=0) - timedelta(days=days_ago),
                         payload={**BASE, **payload})


@pytest_asyncio.fixture(loop_scope="session")
async def clusters(database):
    sessions = async_sessionmaker(database, expire_on_commit=False)
    async with sessions() as session:
        for code, crop, woreda in (("CL-ET0406-001", "CROP_TEFF", "ET040611"),
                                   ("CL-ET0101-001", "CROP_WHEAT", "ET010101")):
            session.add(G2PRegisterCluster(
                functional_record_id=code, cluster_name=code, crop=crop, geo_lowest_level_value_id=woreda,
                created_by="test", created_at=datetime(2026, 9, 26), last_approved_at=datetime(2026, 9, 26),
                last_approved_by="test",
            ))
        await session.commit()
    yield
    async with database.begin() as conn:
        await conn.execute(text("DELETE FROM g2p_register_clusters WHERE functional_record_id = ANY(:ids)"),
                           {"ids": list(CLUSTER_IDS)})


async def test_participants_are_typed_and_searchable(service, clean, clusters):
    planned, _ = await service.append(act("PLANNED", 30, area_ha=1.0, da_id="DA-ET010101"), "da-01", "STAFF_PORTAL")
    roles = {p.role: p for p in planned.participants}
    assert roles["farmer"].is_primary and roles["farmer"].ref_kind == "EXTERNAL" and roles["farmer"].ref_id == "FR-0001"
    assert roles["plot"].ref_kind == "EXTERNAL" and roles["plot"].ref_id == "LAND-0001-1"
    assert roles["development_agent"].ref_id == "DA-ET010101"

    # The cluster is an entity in this instance: a LOCAL participant, resolved to its record.
    enrolled, _ = await service.append(act("CLUSTER_ENROLLED", 25, cluster_id="CL-ET0101-001"), "da-01", "STAFF_PORTAL")
    cluster = next(p for p in enrolled.participants if p.role == "cluster")
    assert cluster.ref_kind == "LOCAL" and cluster.ref_register == "Cluster" and cluster.internal_record_id

    found, _ = await service.search(SearchActivitiesPayload(register_mnemonic=REG, participant_id="CL-ET0101-001",
                                                            participant_role="cluster"), None)
    assert [a.activity_id for a in found] == [enrolled.activity_id]

    # Entities first: an unknown cluster is rejected, not recorded for later.
    with pytest.raises(Exception):
        await service.append(act("CLUSTER_ENROLLED", 25, cluster_id="CL-NOPE-001"), "da-01", "STAFF_PORTAL")


async def test_changed_crop_replaces_its_season(service, clean, database):
    teff, _ = await service.append(act("PLANNED", 30, area_ha=1.0), "da-01", "STAFF_PORTAL")
    wheat, _ = await service.append(
        act("PLANNED", 20, area_ha=1.0, crop="CROP_WHEAT", replaces_crop_season_id=teff.context_id),
        "da-01", "STAFF_PORTAL")
    async with database.connect() as conn:
        result = await conn.execute(text(
            "SELECT context_id, replaces_context_id, replaced_by_context_id, status FROM g2p_activity_contexts"))
        rows = {row[0]: tuple(row[1:]) for row in result.all()}
    assert rows[teff.context_id] == (None, wheat.context_id, "CLOSED")
    assert rows[wheat.context_id] == (teff.context_id, None, "OPEN")


async def test_samples_load_once_from_master_data_people(service, clean, database):
    from openg2p_registry_core.services import G2PActivitySampleService

    samples = G2PActivitySampleService()
    assert await samples.load(REG) == 0  # waits for the sample clusters

    sessions = async_sessionmaker(database, expire_on_commit=False)
    async with sessions() as session:
        session.add(G2PRegisterCluster(
            functional_record_id="CL-ET0101-001", cluster_name="Tahtay Adiyabo wheat cluster", crop="CROP_WHEAT",
            geo_lowest_level_value_id="ET010101", created_by="test", created_at=datetime(2026, 9, 26),
            last_approved_at=datetime(2026, 9, 26), last_approved_by="test",
        ))
        await session.commit()
    try:
        loaded = await samples.load(REG)
        assert loaded > 100
        assert await samples.load(REG) == 0  # idempotent

        async with database.connect() as conn:
            async def run(sql):
                return await conn.execute(text(sql))

            farmers = {r[0] for r in (await run("SELECT DISTINCT subject_id FROM g2p_activity_contexts")).all()}
            # The ten adults of the ETH pack's 21 sample people, as the Farmer Registry numbers them.
            assert farmers == {f"FR-{n:04d}" for n in (1, 2, 6, 7, 9, 10, 14, 16, 18, 19)}
            statuses = dict((await run(
                "SELECT status, count(*) FROM g2p_activity_crop_sown GROUP BY status")).all())
            assert statuses.get("SUPERSEDED") == 1
            verification = dict((await run(
                "SELECT verification_status, count(*) FROM g2p_activity_crop_sown "
                "WHERE status = 'ACTIVE' AND activity_type IN ('SOWN', 'HARVESTED') GROUP BY 1")).all())
            assert verification.get("VERIFIED") and verification.get("SUBMITTED")  # some await verification
            enrolled = (await run(
                "SELECT count(*) FROM g2p_activity_participants WHERE role = 'cluster' "
                "AND ref_id = 'CL-ET0101-001'")).scalar()
            assert enrolled == 4  # the four adults in Tahtay Adiyabo
    finally:
        async with database.begin() as conn:
            await conn.execute(text("DELETE FROM g2p_register_clusters WHERE functional_record_id = 'CL-ET0101-001'"))
