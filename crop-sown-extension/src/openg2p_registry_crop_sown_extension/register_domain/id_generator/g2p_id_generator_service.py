from openg2p_fastapi_common.service import BaseService
from openg2p_registry_core.interfaces import G2PIdGeneratorInterface, IdAffix
from openg2p_registry_core.models.g2p_register import G2PRegister


class G2PIdGeneratorService(BaseService, G2PIdGeneratorInterface):
    """The Crop Sown Registry issues no functional IDs (it holds only an activity
    register); this exists because the platform resolves an ID generator by name."""

    def generate_prefix_suffix(self, g2p_register: G2PRegister, register_mnemonic: str) -> IdAffix:
        return IdAffix(prefix="CSR-", suffix="")
