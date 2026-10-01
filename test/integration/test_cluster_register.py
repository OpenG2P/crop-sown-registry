"""The Cluster entity register: its seeded metadata, and a record round-tripping through its table."""

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from openg2p_registry_crop_sown_extension.register_domain.models import G2PRegisterCluster

pytestmark = pytest.mark.asyncio(loop_scope="session")

CLUSTER = "c5000000-0000-4000-8000-0000000c0001"
LOADER = Path(__file__).resolve().parents[2] / "docker/db-seed/load_sample_data.py"


def _widgets(node):
    if isinstance(node, dict):
        if "widget-id" in node:
            yield node
        for value in node.values():
            yield from _widgets(value)
    elif isinstance(node, list):
        for item in node:
            yield from _widgets(item)


def _sample_loader():
    """docker/db-seed/load_sample_data.py, imported without psycopg2 (only the db-seed image has it)."""
    stub = types.ModuleType("psycopg2")
    stub.extras = types.SimpleNamespace(Json=lambda value: value)
    saved = {name: sys.modules.get(name) for name in ("psycopg2", "psycopg2.extras")}
    sys.modules.update({"psycopg2": stub, "psycopg2.extras": stub.extras})
    try:
        spec = importlib.util.spec_from_file_location("csr_load_sample_data", LOADER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


async def test_cluster_register_is_seeded(database):
    async with database.connect() as conn:
        definition = (await conn.execute(text(
            "SELECT register_mnemonic, register_subject, register_purpose, register_rank, "
            "functional_id_generation_required, dedup_is_enabled, completion_score_required, "
            "requires_registrant_authentication FROM g2p_register_definitions WHERE register_id = :r"),
            {"r": CLUSTER})).one()
        assert tuple(definition) == ("Cluster", "Clusters", "REGISTER", 2, False, False, False, False)

        schema = (await conn.execute(text(
            "SELECT search_result_schema FROM g2p_register_schemas WHERE register_id = :r"), {"r": CLUSTER})).one()
        assert schema.search_result_schema[0]["field_name"] == "functional_record_id"

        sections = (await conn.execute(text(
            "SELECT s.section_id, s.section_register_id, s.section_ui_schema, s.cr_auto_approve_for_staff_portal "
            "FROM g2p_register_ui_tab_sections ts JOIN g2p_register_sections s ON s.section_id = ts.section_id "
            "JOIN g2p_register_ui_tabs t ON t.tab_id = ts.tab_id "
            "WHERE t.register_id = :r ORDER BY ts.section_order"), {"r": CLUSTER})).all()
        assert [s.section_id for s in sections] == ["cluster_cluster_details_section_01",
                                                    "cluster_location_resources_section_02"]
        assert all(s.section_register_id == CLUSTER and not s.cr_auto_approve_for_staff_portal for s in sections)

        # Every widget writes a real Cluster column, and every dropdown names a Master Data list.
        columns = set(G2PRegisterCluster.__table__.columns.keys())
        attributes = set((await conn.execute(text("SELECT attribute_id FROM g2p_attributes"))).scalars())
        bound = {}
        for section in sections:
            for widget in _widgets(section.section_ui_schema):
                paths = widget["widget-data-path"]
                for path in paths.values() if isinstance(paths, dict) else [paths]:
                    register_id, field = path.split(".", 1)
                    assert register_id == CLUSTER and field in columns, path
                    bound[field] = widget
        assert {"functional_record_id", "cluster_name", "crop", "established_year", "coordinator_name",
                "coordinator_phone", "geo_lowest_level_value_id", "cluster_area_ha", "number_of_smallholders",
                "agro_ecological_zone", "water_source"} <= set(bound)
        assert bound["geo_lowest_level_value_id"]["widget"] == "geo-hierarchy"
        for field, attribute in (("crop", "CROP_COMMODITY"), ("agro_ecological_zone", "AGRO_ECOLOGICAL_ZONE"),
                                 ("water_source", "WATER_SOURCE")):
            assert bound[field]["widget-data-source"]["params"]["attribute_id"] == attribute
            assert attribute in attributes

        intake = (await conn.execute(text(
            "SELECT f.used_only_in_ingestion_pipeline, count(ts.section_id) FROM g2p_intake_form_definitions f "
            "JOIN g2p_intake_form_ui_tabs t ON t.form_id = f.form_id "
            "JOIN g2p_intake_form_ui_tab_sections ts ON ts.tab_id = t.tab_id "
            "WHERE f.register_id = :r GROUP BY f.used_only_in_ingestion_pipeline"), {"r": CLUSTER})).one()
        assert tuple(intake) == (False, 2)

        policies = (await conn.execute(text(
            "SELECT policy_scope, policy_key FROM g2p_registry_awe_policy_configurations WHERE register_id = :r "
            "ORDER BY policy_scope"), {"r": CLUSTER})).all()
        assert [tuple(p) for p in policies] == [("INTAKE_FORM", "registry.intake_form.cluster"),
                                                ("REGISTER", "registry.change_request.cluster")]


async def test_cluster_record_round_trips(database):
    sessions = async_sessionmaker(database, expire_on_commit=False)
    try:
        async with sessions() as session:
            session.add(G2PRegisterCluster(
                functional_record_id="CL-TEST-001", cluster_name="Test teff cluster", crop="CROP_TEFF",
                agro_ecological_zone="AEZ_WEYNA_DEGA", water_source="WS_RAINFED", cluster_area_ha=120,
                number_of_smallholders=85, established_year=2016, coordinator_name="Tadesse Bekele",
                coordinator_phone="+251911000101", geo_lowest_level_value_id="ET040611",
                created_by="test", created_at=datetime(2026, 9, 26), last_approved_at=datetime(2026, 9, 26),
                last_approved_by="test",
            ))
            await session.commit()
        async with sessions() as session:
            cluster = (await session.execute(
                select(G2PRegisterCluster).where(G2PRegisterCluster.functional_record_id == "CL-TEST-001"))).scalar_one()
        assert cluster.record_name == "Test teff cluster"  # record_name = cluster name
        assert {"CL-TEST-001", "CROP_TEFF", "ET040611"} <= set(cluster.search_text.split())
        assert (cluster.crop, cluster.geo_lowest_level_value_id, float(cluster.cluster_area_ha),
                cluster.number_of_smallholders, cluster.established_year, cluster.record_status) == (
            "CROP_TEFF", "ET040611", 120.0, 85, 2016, "ACTIVE")
    finally:
        async with database.begin() as conn:
            await conn.execute(text("DELETE FROM g2p_register_clusters WHERE functional_record_id = 'CL-TEST-001'"))


async def test_sample_clusters_use_master_data_codes_and_woredas(database):
    loader = _sample_loader()
    async with database.connect() as conn:
        codes = {(a, v) for a, v in (await conn.execute(
            text("SELECT attribute_id, value_id FROM g2p_attribute_values"))).all()}
        geo = {r.level_value_id: (r.level_mnemonic, r.level_value_mnemonic, r.parent_level_value_id)
               for r in (await conn.execute(text(
                   "SELECT v.level_value_id, l.level_mnemonic, v.level_value_mnemonic, v.parent_level_value_id "
                   "FROM g2p_geo_level_values v JOIN g2p_geo_levels l ON l.level_id = v.level_id"))).all()}

    assert [c["functional_record_id"] for c in loader.CLUSTERS] == ["CL-ET0406-001", "CL-ET0101-001"]
    for cluster in loader.CLUSTERS:
        for field, attribute in (("crop", "CROP_COMMODITY"), ("agro_ecological_zone", "AGRO_ECOLOGICAL_ZONE"),
                                 ("water_source", "WATER_SOURCE")):
            assert (attribute, cluster[field]) in codes, (cluster["functional_record_id"], field)
        assert set(loader.FIELDS) <= set(G2PRegisterCluster.__table__.columns.keys())

    hierarchy = loader.geo_hierarchy("ET040611", geo)["hierarchy"]
    assert [(h["level_mnemonic"], h["level_value_id"]) for h in hierarchy] == [
        ("country", "ET"), ("region", "ET04"), ("zone", "ET0406"), ("woreda", "ET040611")]
    assert hierarchy[-1]["level_value_mnemonic"] == "Sheno town"
