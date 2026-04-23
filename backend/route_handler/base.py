from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ParamSpec,
    TypeVar,
    get_type_hints,
)

from fastapi import APIRouter, Request

from backend.db.data_models import GiftcardProvider
from backend.lib.giftcard.base import AbstractBaseGiftcardClient
from backend.lib.payments.stripe.base import AbstractBaseStripeClient
from backend.lib.pricing.pricer import RequestPricer
from backend.lib.request.context import RequestContext

from .mixins import DAORetrieveAssertingOwnershipMixin

if TYPE_CHECKING:
    from backend.app import TimelensApp  # Avoids circular import


T = TypeVar("T", bound=Callable[..., Any])
_response_model_registry: dict[Callable[..., Any], type[Any]] = {}


P = ParamSpec("P")
R = TypeVar("R")


def unauthenticated_route(func: Callable[P, R]) -> Callable[P, R]:
    setattr(func, "_allow_unauthenticated", True)
    return func


def enforce_response_model(func: T) -> T:
    hints = get_type_hints(func)
    return_type = hints.get("return")
    if return_type is None:
        raise ValueError(f"{func.__name__} must have a return type annotation")

    # Normalize to underlying function (unbound)
    key = getattr(func, "__func__", func)
    _response_model_registry[key] = return_type
    return func


def get_response_model(func: Callable[..., Any]) -> type[Any]:
    # Normalize to underlying function (unbound)
    key = getattr(func, "__func__", func)
    return _response_model_registry[key]


class RouteHandler(DAORetrieveAssertingOwnershipMixin):
    unauthenticated_routes: set[str] = set()

    def __init__(self, app: "TimelensApp") -> None:
        self.app = app
        self.router = APIRouter()
        self.register_routes()

    def register_routes(self) -> None:
        pass

    def get_router(self) -> APIRouter:
        return self.router

    async def get_request_context(self, request: Request) -> RequestContext:
        return await self.app.get_request_context(request)

    def route(self, path: str, method_name: str, methods: list[str]) -> None:
        # Retrieve method
        if not hasattr(self, method_name):
            raise RuntimeError(
                f"Method {method_name} not found on handler class {self.__class__.__name__}"
            )

        method = getattr(self, method_name)

        if not callable(method):
            raise TypeError(
                f"Attribute {method_name} on {self.__class__.__name__} is not callable"
            )

        try:
            response_model = get_response_model(method)
        except KeyError:
            raise RuntimeError(
                f"Method {method_name} is not decorated with @enforce_response_model"
            )

        self.router.add_api_route(
            path,
            method,
            methods=methods,
            response_model=response_model,
        )

        if getattr(method, "_allow_unauthenticated", False):
            RouteHandler.unauthenticated_routes.add(path)

    def websocket_route(self, path: str, method_name: str) -> None:
        # Retrieve method
        if not hasattr(self, method_name):
            raise RuntimeError(
                f"WebSocket method {method_name} not found on handler class {self.__class__.__name__}"
            )

        method = getattr(self, method_name)

        if not callable(method):
            raise TypeError(
                f"Attribute {method_name} on {self.__class__.__name__} is not callable"
            )

        self.router.add_api_websocket_route(path, method)

        if getattr(method, "_allow_unauthenticated", False):
            RouteHandler.unauthenticated_routes.add(path)

    def get_stripe_client_for_request(
        self, request: Request
    ) -> AbstractBaseStripeClient:
        return self.app.stripe_clients[self.app.get_effect_mode(request)]

    def get_giftcard_client_for(
        self, *, request: Request, giftcard_provider: GiftcardProvider
    ) -> AbstractBaseGiftcardClient:
        return self.app.giftcard_clients[self.app.get_effect_mode(request)][
            giftcard_provider
        ]

    def get_request_pricer(self, request: Request) -> RequestPricer:
        return self.app.request_pricer
