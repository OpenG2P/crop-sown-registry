"""The questions a partner (through the API gateway) asks of the crop seasons, one synchronous DCI call each.

"Total area of wheat sown by farmer FR-… this season": the farmer's season
summary for that crop year and season (measures.by_crop), or the farmer's wheat
crop seasons for it (one per plot).
"""

import importlib
import sys
from datetime import datetime, timedelta

import pytest

from openg2p_registry_core.schemas.activity import ActivityInput
from openg2p_registry_core.services import G2PActivityOutboxService

pytestmark = pytest.mark.asyncio(loop_scope="session")

REG = "CropSown"
FARMER = "FR-0042"
BASE = {"farmer_id": FARMER, "crop_year": 2019, "season": "SEASON_MEHER", "geo_lowest_level_value_id": "ET040611"}


def act(activity_type, days_ago, **payload):
    return ActivityInput(register_mnemonic=REG, activity_type=activity_type,
                         occurred_at=datetime.utcnow().replace(microsecond=0) - timedelta(days=days_ago),
                         payload={**BASE, **payload})


def _dci():
    """The partner API's DCI service, with this extension as the platform's extension module (as main.py does)."""
    sys.modules.setdefault("openg2p_registry_extensions",
                           importlib.import_module("openg2p_registry_crop_sown_extension"))
    from openg2p_registry_partner_api.search.dci.helpers import DciQueryHelper
    from openg2p_registry_partner_api.search.dci.schemas import DciSearchCriteria
    from openg2p_registry_partner_api.search.dci.services.g2p_dci_service import G2PDciService

    return G2PDciService(), DciQueryHelper, DciSearchCriteria


def criteria(DciSearchCriteria, record_type: str, query: dict) -> object:
    return DciSearchCriteria.model_validate({
        "reg_type": REG, "reg_record_type": record_type, "query_type": "expression",
        "query": {"type": "expression", "value": {"expression": {"query": query}}},
    })


async def _sow(service, plot, crop, area, season="SEASON_MEHER", crop_year=2019):
    keys = {"plot_id": plot, "crop": crop, "season": season, "crop_year": crop_year}
    await service.append(act("PLANNED", 40, area_ha=area, **keys), "da", "STAFF_PORTAL")
    await service.append(act("SOWN", 30, area_ha=area, seed_type="SEED_IMPROVED", **keys), "da", "STAFF_PORTAL")


async def test_wheat_area_sown_this_season(service, clean):
    pytest.importorskip("openg2p_registry_partner_api")
    await _sow(service, "LAND-0042-1", "CROP_WHEAT", 1.5)
    await _sow(service, "LAND-0042-2", "CROP_WHEAT", 0.5)
    await _sow(service, "LAND-0042-3", "CROP_TEFF", 2.0)
    await _sow(service, "LAND-0042-1", "CROP_WHEAT", 0.7, season="SEASON_BELG", crop_year=2018)
    await G2PActivityOutboxService().process_batch()

    dci, helper, DciSearchCriteria = _dci()
    register_id = await dci._get_register_id(REG)

    # The season summary: one record, the wheat total under measures.by_crop.
    subject, filters = helper.parse_subject_query(criteria(
        DciSearchCriteria, "spdci-extensions-agri:ActivityAggregate",
        {"subject_id": FARMER, "aggregate_type": "FARMER_SEASON_SUMMARY", "crop_year": 2019,
         "season": "SEASON_MEHER"}))
    records, total = await dci._aggregate_search(REG, register_id, subject, filters, 1, 10)
    assert total == 1
    assert records[0]["measures"]["by_crop"]["CROP_WHEAT"]["area_sown_ha"] == 2.0
    assert records[0]["measures"]["area_sown_ha"] == 4.0

    # The crop seasons themselves: the farmer's wheat this season, one per plot.
    subject, filters = helper.parse_subject_query(criteria(
        DciSearchCriteria, "spdci-extensions-agri:CropSeason",
        {"subject_id": FARMER, "crop_year": 2019, "season": "SEASON_MEHER", "crop": "CROP_WHEAT"}))
    seasons, total = await dci._state_search(REG, register_id, "CROP_SEASON", subject, filters, 1, 10)
    assert total == 2
    assert sum(s["measures"]["area_sown_ha"] for s in seasons) == 2.0

    # An idtype-value query still returns every season of the farmer, as before.
    _, all_seasons = await dci._state_search(REG, register_id, "CROP_SEASON", FARMER, {}, 1, 10)
    assert all_seasons == 4

    # A field the view does not have is a clear error, not an empty answer.
    from openg2p_registry_core.errors import G2PRegistryException

    with pytest.raises(G2PRegistryException):
        await dci._state_search(REG, register_id, "CROP_SEASON", FARMER, {"no_such_field": 1}, 1, 10)


async def test_farmer_activities_filtered(service, clean):
    pytest.importorskip("openg2p_registry_partner_api")
    await _sow(service, "LAND-0042-1", "CROP_WHEAT", 1.5)
    await _sow(service, "LAND-0042-3", "CROP_TEFF", 2.0)
    await _sow(service, "LAND-0099-1", "CROP_WHEAT", 1.0)  # another plot, same farmer

    dci, helper, DciSearchCriteria = _dci()
    from openg2p_registry_core.services import G2PActivityRegistryService
    from openg2p_registry_partner_api.search.dci.helpers.query_helper import DciQueryResult
    from openg2p_registry_partner_api.search.dci.services.g2p_dci_service import _plain_columns

    model, _ = G2PActivityRegistryService().resolve_classes(REG)
    since = (datetime.utcnow() - timedelta(days=35)).isoformat()
    subject, filters = helper.parse_subject_query(criteria(
        DciSearchCriteria, "spdci-extensions-agri:CropActivity",
        {"subject_id": FARMER, "activity_type": "SOWN", "crop": "CROP_WHEAT", "occurred_at": {"$gte": since}}))
    query = DciQueryResult(filter_conditions=[
        model.subject_id == subject, *helper.translate_filters(filters, _plain_columns(model, {"search_text"}))])
    rows, total = await dci._activity_search(model, query, 1, 10, None)
    assert total == 2 and {r.model_dump()["plot_id"] for r in rows} == {"LAND-0042-1", "LAND-0099-1"}

    # The last 10 activities, newest first: the same search with no filters.
    rows, total = await dci._activity_search(model, DciQueryResult(filter_conditions=[model.subject_id == FARMER]),
                                             1, 10, None)
    assert total == 6
    dates = [r.model_dump()["occurred_at"] for r in rows]
    assert dates == sorted(dates, reverse=True)


async def test_consent_subject_must_be_the_farmer_searched(service, clean):
    pytest.importorskip("openg2p_registry_partner_api")
    from openg2p_registry_core.errors import G2PRegistryException

    await _sow(service, "LAND-0042-1", "CROP_WHEAT", 1.0)
    # The same farmer's FAN, recorded on one of their activities.
    await service.append(act("PLANNED", 40, plot_id="LAND-0042-9", crop="CROP_TEFF", area_ha=1.0,
                             fayda_fan="123456789012"), "da", "STAFF_PORTAL")
    dci, _, _ = _dci()

    await dci._require_subject_link(REG, FARMER, FARMER)                # consent by farmer ID
    await dci._require_subject_link(REG, FARMER, "123456789012")        # consent by FAN, linked by the data
    with pytest.raises(G2PRegistryException):
        await dci._require_subject_link(REG, FARMER, "999999999999")    # another person's consent
    with pytest.raises(G2PRegistryException):
        await dci._require_subject_link(REG, None, "123456789012")      # no subject searched

    from openg2p_registry_core.schemas import DeepSearchResultData

    record = DeepSearchResultData(internal_record_id="r1", foundational_id="123456789012", functional_record_id="FR-0042")
    dci._require_records_of_subject([record], "FR-0042")
    dci._require_records_of_subject([record], "123456789012")
    with pytest.raises(G2PRegistryException):
        dci._require_records_of_subject([record], "FR-0099")
