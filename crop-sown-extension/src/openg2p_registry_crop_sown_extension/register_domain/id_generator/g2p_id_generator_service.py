from openg2p_fastapi_common.service import BaseService
from openg2p_registry_core.interfaces import G2PIdGeneratorInterface, IdAffix
from openg2p_registry_core.models.g2p_register import G2PRegister


class G2PIdGeneratorService(BaseService, G2PIdGeneratorInterface):
    """Prefixes for generated functional IDs. Only the Cluster register mints IDs
    (pool ``cluster`` in the ID generator: the register mnemonic in lowercase);
    CropSown is an activity register and needs none."""

    def generate_prefix_suffix(self, g2p_register: G2PRegister, register_mnemonic: str) -> IdAffix:
        mnemonic = (register_mnemonic or "").lower()

        if mnemonic == "cluster":
            return IdAffix(prefix="CL-", suffix="")

        return IdAffix(prefix="DEFAULT-", suffix="")
