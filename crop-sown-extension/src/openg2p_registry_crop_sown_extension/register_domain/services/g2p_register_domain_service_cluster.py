import logging

from openg2p_registry_core.errors import G2PRegistryErrorCodes, G2PRegistryException
from openg2p_registry_core.services import G2PRegisterDomainService

_logger = logging.getLogger("g2p-register-domain-service")


def _number(record: dict, key: str):
    value = record.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        _invalid(f"{key} must be a number")


def _invalid(message: str) -> None:
    raise G2PRegistryException(code=G2PRegistryErrorCodes.REQUEST_VALIDATION_ERROR.value[1], message=message)


class G2PRegisterDomainServiceCluster(G2PRegisterDomainService):
    async def validate_domain_attributes(self, records: list[dict]):
        for record in records:
            area = _number(record, "cluster_area_ha")
            if area is not None and area <= 0:
                _invalid("cluster_area_ha must be greater than zero when provided")
            smallholders = _number(record, "number_of_smallholders")
            if smallholders is not None and smallholders < 0:
                _invalid("number_of_smallholders must not be negative")
            year = _number(record, "established_year")
            if year is not None and not 1900 <= year <= 2100:  # Ethiopian calendar year
                _invalid("established_year must be an Ethiopian calendar year, e.g. 2016")

    def construct_search_text(self, payload: dict, extra: list[str] = None) -> str:
        _logger.info("Constructing search text for cluster")

        # The Cluster ID (functional_record_id) is added by G2PRegister. The name is
        # listed here because record_name is only derived after search_text on insert.
        keys = [
            "programme_cluster_code",
            "cluster_name",
            "crop",
            "geo_lowest_level_value_id",
            "coordinator_name",
            "coordinator_phone",
        ]
        search_text = []
        if extra:
            search_text.extend(str(value).strip() for value in extra if str(value).strip())
        search_text.extend(
            str(payload.get(key) or "").strip()
            for key in keys
            if str(payload.get(key) or "").strip()
        )

        return " ".join(search_text).strip()

    def construct_record_name(self, payload: dict, extra: list[str] = None) -> str:
        _logger.info("Constructing record name for cluster")

        record_name = []
        if extra:
            record_name.extend(str(item).strip() for item in extra if str(item).strip())
        name = str(payload.get("cluster_name") or "").strip()
        if name:
            record_name.append(name)

        return " ".join(record_name).strip()
