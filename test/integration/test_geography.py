"""Crop seasons by geography: the plot's woreda as the location, indicators and reporting views by level."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from openg2p_registry_core.errors import G2PRegistryException
from openg2p_registry_core.schemas.activity import ActivityInput
from openg2p_registry_core.services import G2PActivityIndicatorService

pytestmark = pytest.mark.asyncio(loop_scope="session")

REG = "CropSown"
SHENO = "ET040611"      # Sheno town — North Shewa (OR), Oromia
TAHTAY = "ET010101"     # a woreda in Tigray


def act(activity_type, days_ago, plot, woreda=None, farmer="FR-1", **payload):
    body = {"farmer_id": farmer, "plot_id": plot, "crop_year": 2019, "season": "SEASON_MEHER",
            "crop": "CROP_TEFF", **payload}
    if woreda:
        body["geo_lowest_level_value_id"] = woreda
    return ActivityInput(register_mnemonic=REG, activity_type=activity_type,
                         occurred_at=datetime.utcnow().replace(microsecond=0) - timedelta(days=days_ago),
                         payload=body)


async def test_location_is_required_named_and_carried_through_the_season(service, clean, database):
    with pytest.raises(G2PRegistryException) as missing:
        await service.append(act("PLANNED", 60, "LND-1", area_ha=1.0), "da", "S")
    assert missing.value.code == "ACT-ERR-004"  # the plot's woreda is required when planning
    with pytest.raises(G2PRegistryException) as zone:
        await service.append(act("PLANNED", 60, "LND-1", woreda="ET0406", area_ha=1.0), "da", "S")
    assert zone.value.code == "ACT-ERR-005"  # a zone is not a woreda

    planned, _ = await service.append(act("PLANNED", 60, "LND-1", woreda=SHENO, area_ha=1.0), "da", "S")
    assert planned.geo_dimensions["woreda"] == {"code": SHENO, "name": "Sheno town"}
    assert planned.geo_dimensions["zone"]["name"] == "North Shewa (OR)"
    assert planned.display["geo_lowest_level_value_id"] == "Sheno town"

    # Sowing repeats the woreda (required); growth observation does not, and takes the season's.
    await service.append(act("SOWN", 50, "LND-1", woreda=SHENO, area_ha=1.0, seed_type="SEED_LOCAL"), "da", "S")
    observed, _ = await service.append(
        act("GROWTH_OBSERVED", 20, "LND-1", growth_stage="GS_VEGETATIVE", crop_condition="CC_GOOD"), "da", "S")
    assert observed.geo_dimensions["woreda"]["code"] == SHENO


async def test_indicators_and_views_by_region_zone_woreda(service, clean, database):
    for plot, woreda, farmer, area in (("LND-1", SHENO, "FR-1", 1.0), ("LND-2", SHENO, "FR-2", 2.0),
                                       ("LND-3", TAHTAY, "FR-3", 4.0)):
        await service.append(act("PLANNED", 60, plot, woreda=woreda, farmer=farmer, area_ha=area), "da", "S")
        await service.append(act("SOWN", 50, plot, woreda=woreda, farmer=farmer, area_ha=area,
                                 seed_type="SEED_LOCAL"), "da", "S")
    await service.append(act("HARVESTED", 1, "LND-1", farmer="FR-1", area_ha=1.0, quantity_qt=20), "da", "S")

    by_region = await G2PActivityIndicatorService().compute(REG, "SOWN_AREA_BY_REGION")
    assert {(r["geo:region_name"], r["value"]) for r in by_region.rows} == {("Oromia", 3.0), ("Tigray", 4.0)}
    farmers = await G2PActivityIndicatorService().compute(REG, "FARMERS_REPORTING_BY_WOREDA")
    assert {r["geo:woreda"]: r["value"] for r in farmers.rows}[SHENO] == 2

    async with database.connect() as conn:
        region = (await conn.execute(text(
            "SELECT region_name, crop_seasons, farmers, area_sown_ha, production_qt, yield_qt_per_ha "
            "FROM csr_rpt_crop_performance_region ORDER BY region_name"))).all()
        woreda = (await conn.execute(text(
            "SELECT woreda_code, zone_name, area_sown_ha FROM csr_rpt_crop_performance_woreda "
            "WHERE woreda_code = :w"), {"w": SHENO})).one()
    assert [(r.region_name, r.crop_seasons, r.farmers, float(r.area_sown_ha)) for r in region] == [
        ("Oromia", 2, 2, 3.0), ("Tigray", 1, 1, 4.0)]
    assert float(region[0].production_qt) == 20.0 and float(region[0].yield_qt_per_ha) == 20.0
    assert woreda.zone_name == "North Shewa (OR)" and float(woreda.area_sown_ha) == 3.0
