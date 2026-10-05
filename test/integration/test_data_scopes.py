"""The registry's data scope catalogue (meta_data/data-scopes/) and DCI records filtered to it.

A consent names data scopes (``crop-sown-registry.<name>``); the partner API
filters each internal record to the scopes' fields before it is rendered. These
tests publish the shipped catalogue against this extension's models and
sections, and check what a partner gets for a few consents.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text

from openg2p_registry_core.config import Settings
from openg2p_registry_core.helpers.template_helper import template_environment
from openg2p_registry_core.models import G2PDataScope, G2PDataScopeVersion
from openg2p_registry_core.services import DataScopeCatalogueError, G2PActivityOutboxService, G2PDataScopeService

from test_dci_queries import _dci
from test_season_summary import BASE, REG, act

pytestmark = pytest.mark.asyncio(loop_scope="session")

CONTROLLER = "crop-sown-registry"
FARMER = BASE["farmer_id"]
EXTENSION = Path(__file__).resolve().parents[2] / "crop-sown-extension/src/openg2p_registry_crop_sown_extension"
ACTIVITY_TEMPLATE = EXTENSION / "templates/crop_sown_activity_to_dci.json.j2"


def scope(*names):
    return [f"{CONTROLLER}.{name}" for name in names]


@pytest_asyncio.fixture(loop_scope="session")
async def scopes(database):
    for model in (G2PDataScope, G2PDataScopeVersion):
        await model.create_migrate()
    service = G2PDataScopeService.get_component() or G2PDataScopeService()
    await service.ensure_guards()
    async with database.begin() as conn:
        await conn.execute(text("TRUNCATE g2p_data_scopes, g2p_data_scope_versions"))
    config = Settings.get_config(strict=False)
    saved = (config.consent_data_controller, config.data_scopes_catalogue_path)
    config.consent_data_controller = CONTROLLER
    config.data_scopes_catalogue_path = ""  # the extension's own meta_data/data-scopes
    try:
        outcome = await service.sync()
        yield service, outcome
    finally:
        config.consent_data_controller, config.data_scopes_catalogue_path = saved


async def test_the_catalogue_publishes_against_the_extension(scopes):
    service, outcome = scopes
    assert service.catalogue_dir() == EXTENSION / "meta_data/data-scopes"
    assert outcome == {name: "created" for name in (
        "activity", "crop_season", "measures", "farmer_reference", "location",
        "csr_cluster_details", "csr_cluster_location_resources", "cluster_profile")}

    listed = {s["scope_id"]: s for s in await service.list_scopes()}
    assert set(listed) == set(scope(*outcome))
    assert listed[f"{CONTROLLER}.crop_season"]["label"] == "Crop season"
    # Section scopes keep their section reference; the shipped label replaces the section description.
    details = listed[f"{CONTROLLER}.csr_cluster_details"]
    assert details["versions"][0]["fields"] == ["section:csr_cluster_details"]
    assert details["label"] == "Cluster details (with coordinator contact)"
    assert "Cluster.coordinator_phone" in details["versions"][0]["resolved_fields"]
    profile = listed[f"{CONTROLLER}.cluster_profile"]["versions"][0]["resolved_fields"]
    assert "Cluster.functional_record_id" in profile and "Cluster.coordinator_phone" not in profile
    # Aggregates are column-level: the figures are one JSON column.
    assert listed[f"{CONTROLLER}.measures"]["versions"][0]["resolved_fields"][0] == "CropSown.activity.area_ha"
    assert "CropSown.aggregate.aggregate_value" in listed[f"{CONTROLLER}.measures"]["versions"][0]["resolved_fields"]

    # Publishing again changes nothing (scope versions are immutable; same fields → same version).
    assert set((await service.sync()).values()) == {"unchanged"}


async def test_a_field_reference_outside_the_models_refuses_the_catalogue(scopes, database):
    service, _ = scopes
    catalogue, _ = service.load_catalogue()
    catalogue["scopes"] = catalogue["scopes"] + [
        {"name": "broken", "fields": ["CropSown.context.no_such_field", "CropSown.aggregate.payload"]}]
    async with service._session_maker()() as session:
        registers, sections = await service._registry_metadata(session)
    with pytest.raises(DataScopeCatalogueError) as refused:
        service.build_catalogue(catalogue, registers, sections)
    assert len(refused.value.problems) == 2


async def _season(service):
    await service.append(act("PLANNED", 150, area_ha=1.0), "da", "STAFF_PORTAL")
    await service.append(act("SOWN", 120, area_ha=1.0, seed_type="SEED_IMPROVED"), "da", "STAFF_PORTAL")
    await service.append(act("HARVESTED", 2, area_ha=1.0, quantity_qt=18), "da", "STAFF_PORTAL")
    await G2PActivityOutboxService().process_batch()


async def test_dci_records_are_filtered_to_the_consented_scopes(scopes, service, clean):
    data_scopes, _ = scopes
    await _season(service)
    dci, _helper, _criteria = _dci()
    register_id = await dci._get_register_id(REG)
    now = datetime.utcnow() + timedelta(seconds=1)

    # A lender's minimum: which crop season, and whose.
    allowed = await data_scopes.resolve(scope("crop_season", "farmer_reference"), now)
    [state], _ = await dci._state_search(REG, register_id, "CROP_SEASON", FARMER, {}, 1, 10, allowed=allowed)
    assert state["farmer_reference"] == {"farmer_id": FARMER, "fayda_fan": BASE["fayda_fan"]}
    assert state["crop_season"]["stage"] == "HARVESTED" and state["crop_season"]["plot_id"] == BASE["plot_id"]
    assert state["measures"] is None and state["location"] is None

    [summary], _ = await dci._aggregate_search(REG, register_id, FARMER, {}, 1, 10, allowed=allowed)
    assert summary["farmer_reference"] == {"farmer_id": FARMER}
    assert summary["crop_season"]["period_key"] == "2019|SEASON_MEHER"
    assert summary["crop_season"]["season"] == "SEASON_MEHER" and summary["crop_season"]["is_final"] is False
    assert summary["measures"] is None and summary["location"] is None

    # Figures only: no farmer, no crop season, so no is_final either (null, not false).
    allowed = await data_scopes.resolve(scope("measures"), now)
    [summary], _ = await dci._aggregate_search(REG, register_id, FARMER, {}, 1, 10, allowed=allowed)
    assert summary["measures"]["quantity_harvested_qt"] == 18.0
    assert summary["crop_season"] is None and summary["farmer_reference"] is None

    # Another registry's scope, or one this registry does not have, grants nothing.
    allowed = await data_scopes.resolve(["farmer-registry.crop_season", f"{CONTROLLER}.nope"], now)
    [state], _ = await dci._state_search(REG, register_id, "CROP_SEASON", FARMER, {}, 1, 10, allowed=allowed)
    assert {key: value for key, value in state.items() if key != "@type"} == {
        "farmer_reference": None, "crop_season": None, "measures": None, "location": None}


async def test_an_activity_renders_only_its_consented_fields(scopes, service, clean):
    data_scopes, _ = scopes
    await _season(service)
    dci, _helper, _criteria = _dci()
    from openg2p_registry_crop_sown_extension.register_domain.models import G2PActivityCropSown

    allowed = await data_scopes.resolve(scope("crop_season", "measures"), datetime.utcnow() + timedelta(seconds=1))
    rows, total = await dci._activity_search(
        G2PActivityCropSown, SimpleNamespace(filter_conditions=None, search_text=FARMER), 1, 10, "occurred_at")
    assert total == 3
    filtered = dci._filter_record(dci._deep_search_result_data_to_dict(rows[-1]), allowed, REG, True, {})
    record = json.loads(template_environment().from_string(ACTIVITY_TEMPLATE.read_text()).render(expanded=filtered))

    assert record["crop_season"]["plot_id"] == BASE["plot_id"] and record["crop_season"]["crop"] == "CROP_TEFF"
    assert record["measures"]["quantity_qt"] == 18.0 and record["measures"]["details"]["quantity_qt"] == 18
    assert "farmer_id" not in record["measures"]["details"] and "latitude" not in record["measures"]["details"]
    # Not consented: the farmer, the location and the activity's own details.
    assert record["farmer_reference"] == {"farmer_id": None, "fayda_fan": None}
    assert set(record["location"].values()) == {None}
    assert set(record["activity"].values()) == {None}
