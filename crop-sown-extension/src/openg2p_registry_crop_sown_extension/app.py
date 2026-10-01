# ruff: noqa: E402
import asyncio
import logging

from .config import Settings

_config = Settings.get_config()

from openg2p_fastapi_common.app import Initializer as BaseInitializer
from openg2p_registry_core.app import Initializer as CoreInitializer

from .register_domain.factory import G2PIdGeneratorFactory, G2PRegisterDomainFactory
from .register_domain.models import G2PIntakeFormCluster, G2PRegisterCluster, G2PRegisterHistoryCluster
from .register_domain.services import G2PActivityDomainServiceCropSown, G2PRegisterDomainServiceCluster

_logger = logging.getLogger(_config.logging_default_logger_name)


class Initializer(BaseInitializer):
    def initialize(self, **kwargs):
        super().initialize()
        CoreInitializer().initialize()

        G2PRegisterDomainFactory()
        G2PIdGeneratorFactory()
        G2PActivityDomainServiceCropSown()
        G2PRegisterDomainServiceCluster()

    def migrate_database(self, args):
        # The platform's core migration creates every activity and projection
        # table an extension declares (partitioned, with the append-only guard),
        # so CropSown needs nothing here. Record registers are this extension's
        # to create: the Cluster register, its history and its intake form.
        async def migrate():
            _logger.info("Migrating extensions database")

            await G2PRegisterCluster.create_migrate()
            await G2PRegisterHistoryCluster.create_migrate()
            await G2PIntakeFormCluster.create_migrate()

        asyncio.run(migrate())
