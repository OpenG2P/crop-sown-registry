"""Final figures: a farmer's season summary is final once the season is locked; and summaries across farmers."""

import importlib
import sys
from datetime import date, datetime

import pytest

from openg2p_registry_core.schemas.activity import ActivityInput, LockPeriodPayload, SearchAggregatesPayload
from openg2p_registry_core.services import G2PActivityOutboxService

pytestmark = pytest.mark.asyncio(loop_scope="session")

REG = "CropSown"
# Belg of crop year 2018 EC: Megabit 1 (10 Mar 2026) to the end of Pagume (10 Sep 2026).
BELG = {"crop_year": 2018, "season": "SEASON_BELG", "geo_lowest_level_value_id": "ET040611"}
WINDOW = (date(2026, 3, 10), date(2026, 9, 10))


def act(activity_type, when, farmer="FR-0051", plot="LAND-0051-1", **payload):
    return ActivityInput(register_mnemonic=REG, activity_type=activity_type, occurred_at=datetime.fromisoformat(when),
                         payload={**BELG, "farmer_id": farmer, "plot_id": plot, "crop": "CROP_WHEAT", **payload})


async def _season(service, farmer, plot, planned_on="2026-03-15"):
    await service.append(act("PLANNED", planned_on, farmer, plot, area_ha=1.0), "da", "STAFF_PORTAL", seeding=True)
    await service.append(act("SOWN", "2026-04-02", farmer, plot, area_ha=1.0, seed_type="SEED_LOCAL"),
                         "da", "STAFF_PORTAL", seeding=True)
    await service.append(act("HARVESTED", "2026-08-01", farmer, plot, area_ha=1.0, quantity_qt=25),
                         "da", "STAFF_PORTAL", seeding=True)


async def _summary(service, farmer):
    [summary] = await service.search_aggregates(SearchAggregatesPayload(register_mnemonic=REG, subject_id=farmer))
    return summary


async def test_summary_final_while_season_locked(service, clean):
    await _season(service, "FR-0051", "LAND-0051-1")
    await G2PActivityOutboxService().process_batch()
    assert not (await _summary(service, "FR-0051")).is_final

    lock = await service.lock_period(LockPeriodPayload(
        register_mnemonic=REG, period_start=WINDOW[0], period_end=WINDOW[1], reason="Belg 2018 closed"), "supervisor")
    summary = await _summary(service, "FR-0051")
    assert summary.is_final and summary.finalised_by == "supervisor"

    await service.unlock_period(REG, lock.lock_id, "late harvest reports", "supervisor")
    assert not (await _summary(service, "FR-0051")).is_final


async def test_lock_waits_for_pending_events(service, clean):
    await _season(service, "FR-0052", "LAND-0052-1")  # events not processed yet: no summary
    await service.lock_period(LockPeriodPayload(
        register_mnemonic=REG, period_start=WINDOW[0], period_end=WINDOW[1]), "supervisor")
    await G2PActivityOutboxService().process_batch()  # computes the summary, then finalises it
    assert (await _summary(service, "FR-0052")).is_final


async def test_late_change_outside_the_window_makes_it_provisional(service, clean):
    # Planned before the window opens: the lock does not cover the plan.
    await _season(service, "FR-0053", "LAND-0053-1", planned_on="2026-02-20")
    await G2PActivityOutboxService().process_batch()
    await service.lock_period(LockPeriodPayload(
        register_mnemonic=REG, period_start=WINDOW[0], period_end=WINDOW[1]), "supervisor")
    assert (await _summary(service, "FR-0053")).is_final

    from openg2p_registry_core.schemas.activity import SearchActivitiesPayload

    [plan], _ = await service.search(SearchActivitiesPayload(
        register_mnemonic=REG, subject_id="FR-0053", activity_types=["PLANNED"]), None)
    await service.supersede(REG, plan.activity_id, "area re-measured", "da", "STAFF_PORTAL",
                            payload={**plan.payload, "area_ha": 1.5}, seeding=True)
    await G2PActivityOutboxService().process_batch()
    assert not (await _summary(service, "FR-0053")).is_final  # never final and wrong


def _dci():
    sys.modules.setdefault("openg2p_registry_extensions",
                           importlib.import_module("openg2p_registry_crop_sown_extension"))
    from openg2p_registry_partner_api.search.dci.controller.g2p_dci_controller import G2PDciController
    from openg2p_registry_partner_api.search.dci.helpers import DciQueryHelper
    from openg2p_registry_partner_api.search.dci.schemas import DciSearchCriteria
    from openg2p_registry_partner_api.search.dci.services.g2p_dci_service import G2PDciService, _config

    return G2PDciService(), G2PDciController, DciQueryHelper, DciSearchCriteria, _config


def _bulk_criteria(DciSearchCriteria, query):
    return DciSearchCriteria.model_validate({
        "reg_type": REG, "reg_record_type": "spdci-extensions-agri:ActivityAggregate", "query_type": "expression",
        "query": {"type": "expression", "value": {"expression": {"query": query}}},
    })


async def test_final_summaries_across_farmers(service, clean):
    pytest.importorskip("openg2p_registry_partner_api")
    for n in (61, 62, 63):
        await _season(service, f"FR-00{n}", f"LAND-00{n}-1")
    await G2PActivityOutboxService().process_batch()
    await service.lock_period(LockPeriodPayload(
        register_mnemonic=REG, period_start=WINDOW[0], period_end=WINDOW[1]), "supervisor")

    dci, controller, helper, DciSearchCriteria, config = _dci()
    criteria = _bulk_criteria(DciSearchCriteria, {
        "aggregate_type": "FARMER_SEASON_SUMMARY", "crop_year": 2018, "season": "SEASON_BELG", "is_final": True})
    assert helper.is_bulk_aggregate_request(criteria)

    # Only allow-listed partners may search across farmers.
    from types import SimpleNamespace

    from openg2p_registry_core.errors import G2PRegistryException

    message = SimpleNamespace(search_request=[SimpleNamespace(reference_id="1", search_criteria=criteria)])
    saved = config.dci_bulk_aggregate_partners
    try:
        config.dci_bulk_aggregate_partners = {}
        with pytest.raises(G2PRegistryException):
            controller._authorise_bulk(SimpleNamespace(sender_id="someone"), message)
        # Allow-listed scopes are data scope IDs from the registry's catalogue.
        config.dci_bulk_aggregate_partners = {
            "benefits": ["crop-sown-registry.crop_season", "crop-sown-registry.measures"]}
        assert controller._authorise_bulk(SimpleNamespace(sender_id="benefits"), message) == {
            "1": ["crop-sown-registry.crop_season", "crop-sown-registry.measures"]}
    finally:
        config.dci_bulk_aggregate_partners = saved

    subject, filters = helper.parse_subject_query(criteria, allow_missing_subject=True)
    assert subject is None
    records, total = await dci._aggregate_search(REG, await dci._get_register_id(REG), None, filters, 1, 50)
    assert total == 3
    assert {r["farmer_reference"]["farmer_id"] for r in records} == {"FR-0061", "FR-0062", "FR-0063"}
    assert all(r["crop_season"]["is_final"] for r in records)

    # A search across farmers must name the aggregate type.
    with pytest.raises(G2PRegistryException):
        await dci._aggregate_search(REG, await dci._get_register_id(REG), None, {"crop_year": 2018}, 1, 50)
