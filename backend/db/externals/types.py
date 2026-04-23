from typing import Self

from pydantic import BaseModel

from backend.lib.giftcard.brands.registry import (
    BrandRegistryEntry,
    GiftcardBrandRegistry,
)


class BrandPublicResponse(BaseModel):
    brand_code: str
    display_name: str
    description: str
    terms_and_conditions: str
    main_placeholder_color: str
    dark_background_color: str
    giftcard_visual_asset_key: str
    giftcard_visual_public_url: str

    @classmethod
    def from_entry(cls, e: BrandRegistryEntry, registry: GiftcardBrandRegistry) -> Self:
        return cls(
            brand_code=e.brand_code,
            display_name=e.display_name,
            description=e.description,
            terms_and_conditions=e.terms_and_conditions,
            main_placeholder_color=e.main_placeholder_color,
            dark_background_color=e.dark_background_color,
            giftcard_visual_asset_key=registry.get_s3_path_for_filename(
                e.giftcard_visual_filename
            ),
            giftcard_visual_public_url=registry.get_public_url_for_filename(
                e.giftcard_visual_filename
            ),
        )
