"""The farmer's season summary across plots and crops."""

from datetime import datetime, timedelta

import pytest

from openg2p_registry_core.schemas.activity import ActivityInput, SearchAggregatesPayload
from openg2p_registry_core.services import G2PActivityOutboxService

pytestmark = pytest.mark.asyncio(loop_scope="session")

REG = "CropSown"
BASE = {"farmer_id": "FR-000000000123", "fayda_fan": "1234567890123456", "plot_id": "LND-7781",
        "crop_year": 2019, "season": "SEASON_MEHER", "crop": "CROP_TEFF",
        "geo_lowest_level_value_id": "ET040611"}


def act(activity_type, days_ago, **payload):
    return ActivityInput(register_mnemonic=REG, activity_type=activity_type,
                         occurred_at=datetime.utcnow().replace(microsecond=0) - timedelta(days=days_ago),
                         payload={**BASE, **payload})


async def test_farmer_season_summary(service, clean):
    await service.append(act("PLANNED", 150, area_ha=1.0), "da", "STAFF_PORTAL")
    await service.append(act("SOWN", 120, area_ha=1.0, seed_type="SEED_IMPROVED"), "da", "STAFF_PORTAL")
    await service.append(act("HARVESTED", 2, area_ha=1.0, quantity_qt=18), "da", "STAFF_PORTAL")
    wheat = {"plot_id": "LND-9", "crop": "CROP_WHEAT"}
    await service.append(act("PLANNED", 100, area_ha=2.0, **wheat), "da", "STAFF_PORTAL")
    await service.append(act("SOWN", 95, area_ha=2.0, seed_type="SEED_LOCAL", **wheat), "da", "STAFF_PORTAL")
    await G2PActivityOutboxService().process_batch()

    [summary] = await service.search_aggregates(
        SearchAggregatesPayload(register_mnemonic=REG, subject_id=BASE["farmer_id"])
    )
    assert summary.aggregate_type == "FARMER_SEASON_SUMMARY" and summary.period_key == "2019|SEASON_MEHER"
    # Meher of crop year 2019 EC: Meskerem 1 (11 Sep 2026) to the end of Yekatit (9 Mar 2027).
    assert summary.period_start.isoformat() == "2026-09-11" and summary.period_end.isoformat() == "2027-03-09"
    # Both plots are in Sheno town, so the summary is located down to the woreda.
    assert summary.geo_dimensions["woreda"] == {"code": "ET040611", "name": "Sheno town"}
    assert summary.geo_dimensions["region"] == {"code": "ET04", "name": "Oromia"}
    value = summary.aggregate_value
    assert value["crop_seasons"] == 2 and value["plots"] == 2
    assert value["area_sown_ha"] == 3.0 and value["quantity_harvested_qt"] == 18.0
    assert value["yield_qt_per_ha"] == 18.0
    assert value["by_crop"]["CROP_TEFF"]["yield_qt_per_ha"] == 18.0
    assert value["by_crop"]["CROP_WHEAT"]["area_harvested_ha"] == 0.0



async def test_dci_records_group_farmer_season_measures_location(service, clean, database):
    """Crop season state and season summary, as partners get them over DCI, keyed by farmer ID."""
    from sqlalchemy import select

    from openg2p_registry_core.services import G2PActivityRegistryService
    from openg2p_registry_crop_sown_extension.register_domain.models import G2PActivityProjectionCropSown

    await service.append(act("PLANNED", 150, area_ha=1.0), "da", "STAFF_PORTAL")
    await service.append(act("SOWN", 120, area_ha=1.0, seed_type="SEED_IMPROVED"), "da", "STAFF_PORTAL")
    await service.append(act("HARVESTED", 2, area_ha=1.0, quantity_qt=18), "da", "STAFF_PORTAL")
    await G2PActivityOutboxService().process_batch()
    domain = G2PActivityRegistryService().domain_service(REG)
    groups = {"@type", "farmer_reference", "crop_season", "measures", "location"}

    async with database.connect() as conn:
        row = (await conn.execute(select(G2PActivityProjectionCropSown.__table__))).mappings().one()
    state = domain.dci_state_record({k: (v.isoformat() if hasattr(v, "isoformat") else
                                         float(v) if hasattr(v, "as_integer_ratio") and not isinstance(v, (int, bool))
                                         else v) for k, v in row.items()})
    assert set(state) == groups
    assert state["farmer_reference"]["farmer_id"] == BASE["farmer_id"]
    assert state["crop_season"]["stage"] == "HARVESTED" and state["measures"]["yield_qt_per_ha"] == 18.0
    assert state["location"]["woreda"]["code"] == "ET040611"

    [summary] = await service.search_aggregates(SearchAggregatesPayload(register_mnemonic=REG,
                                                                        subject_id=BASE["farmer_id"]))
    record = domain.dci_aggregate_record(summary.model_dump(mode="json"))
    assert set(record) == groups
    assert record["crop_season"]["period_key"] == "2019|SEASON_MEHER" and record["crop_season"]["season"] == "SEASON_MEHER"
    assert record["measures"]["quantity_harvested_qt"] == 18.0
