# backend/route_handler/brand.py

from pydantic import BaseModel

from backend.db.externals.types import BrandPublicResponse
from backend.lib.giftcard.brands.registry import REGISTRY_SINGLETON
from backend.route_handler.base import (
    RouteHandler,
    enforce_response_model,
    unauthenticated_route,
)


class BrandsListAllResponse(BaseModel):
    brands: list[BrandPublicResponse]


class BrandsAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route("/api/brands", "brands_list_all", methods=["GET"])

    @unauthenticated_route
    @enforce_response_model
    async def brands_list_all(self) -> BrandsListAllResponse:
        # Pull from validated in-memory registry
        registry = self.app.giftcard_brand_registry
        all_brands = registry.get_all_brands()
        # Convert to public model and sort (optional) by display_name
        items = [
            BrandPublicResponse.from_entry(e, REGISTRY_SINGLETON)
            for e in all_brands.values()
        ]
        items.sort(key=lambda x: x.display_name.casefold())
        return BrandsListAllResponse(brands=items)
