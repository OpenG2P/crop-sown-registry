"""A crop season end to end: plan → prepare → sow → observe → infestation → harvest."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from openg2p_registry_core.errors import G2PRegistryException
from openg2p_registry_core.helpers.ethiopian_calendar import format_ethiopian_date
from openg2p_registry_core.schemas.activity import ActivityInput, SearchActivitiesPayload, WorkListPayload

pytestmark = pytest.mark.asyncio(loop_scope="session")

REG = "CropSown"
BASE = {"farmer_id": "FR-000000000123", "fayda_fan": "1234567890123456", "plot_id": "LND-7781",
        "crop_year": 2019, "season": "SEASON_MEHER", "crop": "CROP_TEFF"}


def act(activity_type, days_ago, **payload):
    return ActivityInput(register_mnemonic=REG, activity_type=activity_type,
                         occurred_at=datetime.utcnow().replace(microsecond=0) - timedelta(days=days_ago),
                         payload={**BASE, **payload})


async def _code(awaitable):
    with pytest.raises(G2PRegistryException) as info:
        await awaitable
    return info.value.code


async def test_full_season(service, clean, database):
    planned, _ = await service.append(
        act("PLANNED", 110, area_ha=1.0, variety="VAR_TEFF_QUNCHO", cropping_system="CSYS_PURE",
            planned_sowing_date_ec=format_ethiopian_date(date.today() - timedelta(days=100)),
            expected_yield_qt_per_ha=18), "da-01", "STAFF_PORTAL")
    assert planned.subject_type == "FARMER_ID" and planned.subject_id == BASE["farmer_id"]
    assert planned.payload["planned_sowing_date"] == (date.today() - timedelta(days=100)).isoformat()
    assert planned.display["season"] == "Meher (main rains)"

    await service.append(act("LAND_PREPARED", 105, preparation_method="LPM_OXEN", soil_fertility="SF_MEDIUM"),
                         "da-01", "STAFF_PORTAL")
    sown, _ = await service.append(
        act("SOWN", 100, area_ha=0.9, seed_type="SEED_IMPROVED", seed_source="SEEDSRC_COOPERATIVE", seed_kg=15,
            sowing_method="SOW_ROW", fertilizers=[{"fertilizer_type": "FERT_NPS", "quantity_kg": 100}],
            machinery_used=["MACH_ROW_PLANTER"]), "da-01", "ODK")
    assert sown.verification_status == "SUBMITTED"
    await service.verify(REG, sown.activity_id, "supervisor-1", "photo checked")

    await service.append(act("GROWTH_OBSERVED", 55, growth_stage="GS_VEGETATIVE", crop_condition="CC_GOOD", area_ha=0.9),
                         "da-01", "STAFF_PORTAL")
    await service.append(act("INFESTATION_REPORTED", 45, infestation_type="INFT_PEST", agent="AGENT_FALL_ARMYWORM",
                             severity="SEV_MEDIUM", area_ha=0.2, damage_percent=10, action_taken="CTRL_CHEMICAL"),
                         "da-01", "STAFF_PORTAL")
    harvest, _ = await service.append(
        act("HARVESTED", 2, area_ha=0.9, quantity_qt=15.3, stored_qt=8, sold_qt=5, consumed_qt=2),
        "da-01", "STAFF_PORTAL")
    assert harvest.payload["yield_qt_per_ha"] == 17.0
    assert not harvest.rule_warnings

    async with database.connect() as conn:
        row = (await conn.execute(text("SELECT * FROM g2p_activity_projection_crop_sown"))).mappings().one()
    assert row["stage"] == "HARVESTED" and row["activity_count"] == 6
    assert float(row["area_sown_ha"]) == 0.9 and row["sowing_verified"] is True
    assert row["infestation_count"] == 1 and row["max_infestation_severity"] == "SEV_MEDIUM"
    assert float(row["yield_qt_per_ha"]) == 17.0 and row["pending_verification_count"] == 1
    assert row["context_key"] == "LND-7781|2019|SEASON_MEHER|CROP_TEFF"


async def test_rules_for_the_crop_season(service, clean):
    # Growth observed before anything is sown is blocked (BLOCK sequence).
    assert await _code(service.append(act("GROWTH_OBSERVED", 5, growth_stage="GS_EMERGENCE", crop_condition="CC_GOOD"),
                                      "da-01", "STAFF_PORTAL")) == "ACT-ERR-009"
    # Codes outside Master Data's lists are rejected: an unknown crop, a season
    # the ETH pack does not have, and an unprefixed code. A crop year out of
    # range fails the payload schema.
    assert await _code(service.append(act("PLANNED", 5, crop="CROP_QAT", area_ha=1), "da", "S")) == "ACT-ERR-005"
    assert await _code(service.append(act("PLANNED", 5, season="SEASON_SUMMER", area_ha=1), "da", "S")) == "ACT-ERR-005"
    assert await _code(service.append(act("PLANNED", 5, crop="TEFF", area_ha=1), "da", "S")) == "ACT-ERR-005"
    assert await _code(service.append(act("PLANNED", 5, crop_year=1990, area_ha=1), "da", "S")) == "ACT-ERR-004"
    # A fertiliser row with an unknown code is rejected (nested code-list rule).
    assert await _code(service.append(act("SOWN", 5, area_ha=1, seed_type="SEED_LOCAL",
                                          fertilizers=[{"fertilizer_type": "FERT_GUANO", "quantity_kg": 5}]),
                                      "da", "S")) == "ACT-ERR-005"
    # Sown without a plan is accepted with a warning; sowing twice is not.
    sown, _ = await service.append(act("SOWN", 5, area_ha=1, seed_type="SEED_LOCAL"), "da", "STAFF_PORTAL")
    assert any("PLANNED" in w for w in sown.rule_warnings)
    assert await _code(service.append(act("SOWN", 4, area_ha=1, seed_type="SEED_LOCAL"), "da", "S")) == "ACT-ERR-010"
    # Intercropping: a second crop on the same plot is a separate crop season.
    maize, _ = await service.append(act("SOWN", 4, crop="CROP_MAIZE", area_ha=0.3, seed_type="SEED_HYBRID"), "da", "S")
    assert maize.context_id != sown.context_id


async def test_plausibility_warnings(service, clean):
    await service.append(act("PLANNED", 30, area_ha=1.0), "da", "STAFF_PORTAL")
    sown, _ = await service.append(act("SOWN", 20, area_ha=2.0, seed_type="SEED_LOCAL"), "da", "STAFF_PORTAL")
    assert any("1.5" in w for w in sown.rule_warnings)
    harvest, _ = await service.append(act("HARVESTED", 1, area_ha=2.0, quantity_qt=400, sold_qt=500),
                                      "da", "STAFF_PORTAL")
    assert any("implausibly high" in w for w in harvest.rule_warnings)
    assert any("add up to more" in w for w in harvest.rule_warnings)


async def test_work_list_and_indicators(service, clean):
    from openg2p_registry_core.services import G2PActivityIndicatorService

    await service.append(act("PLANNED", 150, area_ha=1.0), "da", "STAFF_PORTAL")
    await service.append(act("SOWN", 120, area_ha=1.0, seed_type="SEED_IMPROVED"), "da", "STAFF_PORTAL")
    other = {"plot_id": "LND-9", "crop": "CROP_WHEAT"}
    await service.append(act("PLANNED", 100, area_ha=2.0, **other), "da", "STAFF_PORTAL")
    await service.append(act("SOWN", 95, area_ha=2.0, seed_type="SEED_LOCAL", **other), "da", "STAFF_PORTAL")

    items, _ = await service.work_list(WorkListPayload(register_mnemonic=REG, activity_type="HARVESTED"), None)
    assert {(i.context_key, i.due_status) for i in items} == {
        ("LND-7781|2019|SEASON_MEHER|CROP_TEFF", "DUE"), ("LND-9|2019|SEASON_MEHER|CROP_WHEAT", "DUE")}

    area = await G2PActivityIndicatorService().compute(REG, "SOWN_AREA_BY_CROP")
    assert {r["crop"]: r["value"] for r in area.rows} == {"CROP_TEFF": 1.0, "CROP_WHEAT": 2.0}
    farmers = await G2PActivityIndicatorService().compute(REG, "FARMERS_REPORTING")
    assert farmers.rows == [{"crop_year": 2019, "season": "SEASON_MEHER", "value": 1}]

    found, total = await service.search(SearchActivitiesPayload(register_mnemonic=REG, activity_types=["SOWN"]), None)
    assert total == 2
