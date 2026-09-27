from openg2p_registry_core.config import Settings as CoreSettings
from pydantic_settings import SettingsConfigDict

from . import __version__


class Settings(CoreSettings):
    model_config = SettingsConfigDict(env_prefix="registry_extensions_", env_file=".env", extra="allow")

    openapi_title: str = "OpenG2P Crop Sown Registry"
    openapi_description: str = """
        Crop Sown Registry: an activity register of what farmers plan, sow,
        observe and harvest, plot by plot and season by season.
        """
    openapi_version: str = __version__
