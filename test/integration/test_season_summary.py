"""The farmer's season summary across plots and crops."""

from datetime import datetime, timedelta

import pytest

from openg2p_registry_core.schemas.activity import ActivityInput, SearchAggregatesPayload
from openg2p_registry_core.services import G2PActivityOutboxService

pytestmark = pytest.mark.asyncio(loop_scope="session")

REG = "CropSown"
BASE = {"farmer_id": "FR-000000000123", "fayda_fan": "1234567890123456", "plot_id": "LND-7781",
        "crop_year": 2019, "season": "SEASON_MEHER", "crop": "CROP_TEFF"}


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
    # Crop year 2019 EC runs from Meskerem 1 (11 Sep 2026) to Pagume 6 (11 Sep 2027): a leap year.
    assert summary.period_start.isoformat() == "2026-09-11" and summary.period_end.isoformat() == "2027-09-11"
    value = summary.aggregate_value
    assert value["crop_seasons"] == 2 and value["plots"] == 2
    assert value["area_sown_ha"] == 3.0 and value["quantity_harvested_qt"] == 18.0
    assert value["yield_qt_per_ha"] == 18.0
    assert value["by_crop"]["CROP_TEFF"]["yield_qt_per_ha"] == 18.0
    assert value["by_crop"]["CROP_WHEAT"]["area_harvested_ha"] == 0.0

