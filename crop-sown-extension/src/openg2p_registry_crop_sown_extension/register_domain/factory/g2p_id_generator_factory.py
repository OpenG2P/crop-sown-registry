import logging
import importlib

from openg2p_fastapi_common.service import BaseService
from openg2p_registry_core.interfaces import G2PIdGeneratorInterface

_logger = logging.getLogger('g2p-id-generator-factory')


class G2PIdGeneratorFactory(BaseService):

    g2p_id_generator: G2PIdGeneratorInterface = None

    def get_id_generator(self) -> G2PIdGeneratorInterface:
        try:
            module = importlib.import_module("openg2p_registry_extensions.register_domain.id_generator")
            implementation_class = getattr(module, "G2PIdGeneratorService")
            g2p_id_generator: G2PIdGeneratorInterface = implementation_class.get_component()
            if not g2p_id_generator:
                g2p_id_generator = implementation_class()
            return g2p_id_generator
        except (AttributeError, ModuleNotFoundError) as error:
            _logger.warning(f"Could not find specific implementation: {error}. Falling back to default implementations.")
            return None
