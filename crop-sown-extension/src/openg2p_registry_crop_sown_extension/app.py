# ruff: noqa: E402
import logging

from .config import Settings

_config = Settings.get_config()

from openg2p_fastapi_common.app import Initializer as BaseInitializer
from openg2p_registry_core.app import Initializer as CoreInitializer

from .register_domain.factory import G2PIdGeneratorFactory, G2PRegisterDomainFactory
from .register_domain.services import G2PActivityDomainServiceCropSown

_logger = logging.getLogger(_config.logging_default_logger_name)


class Initializer(BaseInitializer):
    def initialize(self, **kwargs):
        super().initialize()
        CoreInitializer().initialize()

        G2PRegisterDomainFactory()
        G2PIdGeneratorFactory()
        G2PActivityDomainServiceCropSown()

    def migrate_database(self, args):
        # Nothing to do: the Crop Sown Registry has no record registers, and the
        # platform's core migration creates every activity and projection table
        # an extension declares (partitioned, with the append-only guard).
        _logger.info("Crop Sown Registry: activity tables are migrated by the platform core")
