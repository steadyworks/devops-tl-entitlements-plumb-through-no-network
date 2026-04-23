from backend.env_loader import EnvLoader

from .base import AbstractBaseGiftbitGiftcardClient
from .client import GiftbitAuth, GiftbitClient, GiftbitEndpoint, GiftbitRootURL


class GiftbitGiftcardClientLive(AbstractBaseGiftbitGiftcardClient):
    def _init_giftbit_client(self) -> GiftbitClient:
        return GiftbitClient(
            auth=GiftbitAuth(
                api_token=EnvLoader.get("GIFTBIT_API_KEY_TESTBED")
            ),  # FIXME
            endpoint=GiftbitEndpoint.TESTBED,  # FIXME
            gift_link_endpoint=GiftbitRootURL.TESTBED,  # FIXME
        )
