# backend/lib/payments/stripe/sandbox.py

from stripe import StripeClient

from backend.env_loader import EnvLoader

from .base import AbstractBaseStripeClient


class StripeClientSandbox(AbstractBaseStripeClient):
    def __init__(self) -> None:
        self._client = StripeClient(
            EnvLoader.get("STRIPE_API_SK_SANDBOX"),
        )
