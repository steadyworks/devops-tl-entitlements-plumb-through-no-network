from backend.env_loader import EnvLoader

from .base import AbstractBaseAGCODGiftcardClient
from .client import AGCODClient, AGCODEndpoint, AWSRegion, Credentials


# TODO / FIXME: Swap to real live configs
class AGCODGiftcardClientLive(AbstractBaseAGCODGiftcardClient):
    def _init_agcod_client(self) -> AGCODClient:
        return AGCODClient(
            partner_id=EnvLoader.get("AGCOD_PARTNER_ID"),
            credentials=Credentials(
                access_key_id=EnvLoader.get("AGCOD_ACCESS_KEY_ID_SANDBOX"),
                secret_access_key=EnvLoader.get("AGCOD_ACCESS_SECRET_SANDBOX"),
            ),
            endpoint=AGCODEndpoint.NA_SANDBOX,
            region=AWSRegion.US_EAST_1,
        )
