"""Every code list and code this registry names exists in the ETH pack Master Data loads.

The registry keeps no code lists; a STRICT reference rule to a list the pack
lacks rejects every activity, and a code literal the pack lacks never matches.
Neither shows up until a live install, so check them against the pack here.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import activity_definitions as d  # noqa: E402
from master_data_pack import codes, load_lists, pack_dir  # noqa: E402

PACK = pack_dir()
pytestmark = pytest.mark.skipif(PACK is None, reason="openg2p-data not found (set OPENG2P_DATA_DIR)")


@pytest.fixture(scope="module")
def lists():
    return load_lists(PACK)


def _attribute_rules():
    for activity_type in d.ACTIVITY_TYPES:
        for field, rule in (activity_type.get("reference_rules") or {}).items():
            if rule.get("kind") == "ATTRIBUTE":
                yield activity_type["activity_type"], field, rule["attribute"]


def test_every_referenced_list_is_in_the_pack(lists):
    missing = sorted({(t, f, a) for t, f, a in _attribute_rules() if a not in lists})
    assert not missing, f"reference rules name lists the ETH pack does not define: {missing}"


def test_indicator_filter_codes_are_in_the_pack(lists):
    # Indicator filters compare projection columns against codes, so a code the
    # list does not have silently filters everything out.
    column_list = {"max_infestation_severity": "INFESTATION_SEVERITY", "season": "CROP_SEASON",
                   "crop": "CROP_COMMODITY", "stage": None}
    for code, _name, _unit, definition, _order in d.INDICATORS:
        for column, wanted in (definition.get("filters") or {}).items():
            attribute = column_list.get(column)
            if attribute is None:
                continue
            unknown = set(wanted) - codes(lists[attribute])
            assert not unknown, f"{code} filters {column} on codes {attribute} lacks: {sorted(unknown)}"


def test_domain_service_severity_codes_are_in_the_pack(lists):
    service = pytest.importorskip(
        "openg2p_registry_crop_sown_extension.register_domain.services.crop_sown_domain_service"
    )
    assert set(service.SEVERITY_ORDER) == codes(lists["INFESTATION_SEVERITY"])
