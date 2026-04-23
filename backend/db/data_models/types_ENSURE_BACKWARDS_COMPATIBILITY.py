# backend/db/data_models/types_ENSURE_BACKWARDS_COMPATIBILITY.py

from datetime import datetime  # noqa: TC003
from typing import Annotated, Any, Optional, Self
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, Field, StringConstraints

from backend.db.data_models import (
    ShareChannelType,
)


class BaseModelSerializableToDB(BaseModel):
    def serialize(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def deserialize(cls, obj: dict[str, Any]) -> Self:
        return cls.model_validate(obj)


"""
Every model in this file is serialized into JSONs in DB.

Any changes must ensure backwards compatibility (NO breaking changes), 
or at the risk of breaking production behavior!
"""


class MessageOption(BaseModelSerializableToDB):
    tone: str
    message: str


class PageSchema(BaseModelSerializableToDB):
    page_photos: list[str]
    page_message: MessageOption
    page_message_alternatives: list[MessageOption]
    page_lightweight_title: str

    @classmethod
    def get_page_message_alternatives_key(cls) -> str:
        return "page_message_alternatives"

    @classmethod
    def serialize_page_message_alternatives(
        cls, page_message_alternatives: list[MessageOption]
    ) -> dict[str, list[dict[str, str]]]:
        return {
            cls.get_page_message_alternatives_key(): [
                alt.serialize() for alt in page_message_alternatives
            ]
        }

    @classmethod
    def deserialize_page_message_alternatives(
        cls, serialized_page_message_alternatives: Optional[dict[str, Any]]
    ) -> Optional[list[MessageOption]]:
        if not serialized_page_message_alternatives:
            return None

        key = cls.get_page_message_alternatives_key()
        if key not in serialized_page_message_alternatives:
            return None

        alternatives = serialized_page_message_alternatives[key]
        return [MessageOption.deserialize(alt) for alt in alternatives]


class PhotobookSchema(BaseModelSerializableToDB):
    photobook_title: str
    overall_gift_message: MessageOption
    overall_gift_message_alternatives: list[MessageOption]
    photobook_pages: list[PageSchema]

    @classmethod
    def get_overall_gift_message_alternatives_key(cls) -> str:
        return "overall_gift_message_alternatives"

    @classmethod
    def serialize_overall_gift_message_alternatives(
        cls, overall_gift_message_alternatives: list[MessageOption]
    ) -> dict[str, list[dict[str, str]]]:
        return {
            cls.get_overall_gift_message_alternatives_key(): [
                alt.serialize() for alt in overall_gift_message_alternatives
            ]
        }

    @classmethod
    def deserialize_overall_gift_message_alternatives(
        cls, serialized_overall_gift_message_alternatives: Optional[dict[str, Any]]
    ) -> Optional[list[MessageOption]]:
        if not serialized_overall_gift_message_alternatives:
            return None

        key = cls.get_overall_gift_message_alternatives_key()
        if key not in serialized_overall_gift_message_alternatives:
            return None

        alternatives = serialized_overall_gift_message_alternatives[key]
        return [MessageOption.deserialize(alt) for alt in alternatives]


class ExtractedExif(BaseModelSerializableToDB):
    make: str
    model: str
    datetime_original: str
    iso: int
    exposure_time: float  # seconds
    fnumber: float  # f-stop
    focal_length: float  # mm
    gps_latitude: Optional[float] = None  # decimal degrees
    gps_longitude: Optional[float] = None  # decimal degrees


class AssetMetadata(BaseModelSerializableToDB):
    exif_radar_formatted_address: Optional[str] = None
    exif_radar_place_label: Optional[str] = None
    exif_radar_state_code: Optional[str] = None
    exif_radar_country_code: Optional[str] = None


class ShareChannelSpec(BaseModelSerializableToDB):
    channel_type: ShareChannelType
    destination: str
    # If provided, ensures idempotent creation of this outbox row.
    idempotency_key: Optional[str] = None


class ShareRecipientSpec(BaseModelSerializableToDB):
    # One of (recipient_user_id) or (share_slug) must be present to make the share deterministically addressable.
    recipient_user_id: Optional[UUID] = None
    # Optional display metadata
    recipient_display_name: Optional[str] = None
    notes: Optional[str] = None

    # Per-recipient channels
    channels: list[ShareChannelSpec] = Field(default_factory=list[ShareChannelSpec])


class GiftcardGrantRequest(BaseModelSerializableToDB):
    amount_per_share: Annotated[
        int, Field(strict=True, gt=0)
    ]  # smallest currency unit (e.g., cents)
    currency: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, to_lower=True, min_length=3, max_length=3
        ),
    ]
    brand_code: Annotated[str, Field(min_length=1, description="Gift card brand code")]


class ShareCreateRequest(BaseModelSerializableToDB):
    # One or more recipients (recipient shares)
    recipients: list[ShareRecipientSpec] = Field(
        default_factory=list[ShareRecipientSpec]
    )
    sender_display_name: Optional[str] = None
    # If provided, we schedule; if omitted and send_now==False, we default to pending with no schedule.
    scheduled_for: Optional[datetime] = None
    giftcard_request: Optional[GiftcardGrantRequest] = None
