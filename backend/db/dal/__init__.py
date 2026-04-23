from backend.db.data_models import (
    DAOAssets,
    DAOEntitlements,
    DAOGiftcardEvents,
    DAOGiftcards,
    DAOJobEvents,
    DAOJobs,
    DAONotificationDeliveryAttempts,
    DAONotificationOutbox,
    DAONotifications,
    DAOPages,
    DAOPagesAssetsRel,
    DAOPaymentEvents,
    DAOPayments,
    DAOPhotobookBookmarks,
    DAOPhotobookComments,
    DAOPhotobooks,
    DAOPhotobooksAssetsRel,
    DAOPhotobookSettings,
    DAOPhotobookShare,
    DAOShareChannels,
    DAOShares,
    DAOSubscriptionEvents,
    DAOUsers,
)

from .assets import DALAssets
from .base import (
    AsyncPostgreSQLDAL,
    FilterOp,
    InvalidFilterFieldError,
    OrderDirection,
    locked_row_by_id,
    safe_commit,
    safe_transaction,
)
from .job_events import DALJobEvents
from .payments import DALPayments
from .photobook_comments import DALPhotobookComments
from .schemas import (
    DAOAssetsCreate,
    DAOAssetsUpdate,
    DAOEntitlementsCreate,
    DAOEntitlementsUpdate,
    DAOGiftcardEventsCreate,
    DAOGiftcardEventsUpdate,
    DAOGiftcardsCreate,
    DAOGiftcardsUpdate,
    DAOJobEventsCreate,
    DAOJobsCreate,
    DAOJobsUpdate,
    DAONotificationDeliveryAttemptsCreate,
    DAONotificationDeliveryAttemptsUpdate,
    DAONotificationOutboxCreate,
    DAONotificationOutboxUpdate,
    DAONotificationsCreate,
    DAONotificationsUpdate,
    DAOPagesAssetsRelCreate,
    DAOPagesAssetsRelUpdate,
    DAOPagesCreate,
    DAOPagesUpdate,
    DAOPaymentEventsCreate,
    DAOPaymentEventsUpdate,
    DAOPaymentsCreate,
    DAOPaymentsUpdate,
    DAOPhotobookBookmarksCreate,
    DAOPhotobookBookmarksUpdate,
    DAOPhotobookCommentsCreate,
    DAOPhotobookCommentsUpdate,
    DAOPhotobooksAssetsRelCreate,
    DAOPhotobooksAssetsRelUpdate,
    DAOPhotobooksCreate,
    DAOPhotobookSettingsCreate,
    DAOPhotobookSettingsUpdate,
    DAOPhotobookShareCreate,
    DAOPhotobookShareUpdate,
    DAOPhotobooksUpdate,
    DAOShareChannelsCreate,
    DAOShareChannelsUpdate,
    DAOSharesCreate,
    DAOSharesUpdate,
    DAOSubscriptionEventsCreate,
    DAOSubscriptionEventsUpdate,
    DAOUsersCreate,
    DAOUsersUpdate,
)
from .share_channels import DALShareChannels


class DALJobs(AsyncPostgreSQLDAL[DAOJobs, DAOJobsCreate, DAOJobsUpdate]):
    model = DAOJobs


class DALPages(AsyncPostgreSQLDAL[DAOPages, DAOPagesCreate, DAOPagesUpdate]):
    model = DAOPages


class DALPagesAssetsRel(
    AsyncPostgreSQLDAL[
        DAOPagesAssetsRel, DAOPagesAssetsRelCreate, DAOPagesAssetsRelUpdate
    ]
):
    model = DAOPagesAssetsRel


class DALPhotobooks(
    AsyncPostgreSQLDAL[DAOPhotobooks, DAOPhotobooksCreate, DAOPhotobooksUpdate]
):
    model = DAOPhotobooks


class DALUsers(AsyncPostgreSQLDAL[DAOUsers, DAOUsersCreate, DAOUsersUpdate]):
    model = DAOUsers


class DALPhotobookBookmarks(
    AsyncPostgreSQLDAL[
        DAOPhotobookBookmarks,
        DAOPhotobookBookmarksCreate,
        DAOPhotobookBookmarksUpdate,
    ]
):
    model = DAOPhotobookBookmarks


class DALPhotobookSettings(
    AsyncPostgreSQLDAL[
        DAOPhotobookSettings,
        DAOPhotobookSettingsCreate,
        DAOPhotobookSettingsUpdate,
    ]
):
    model = DAOPhotobookSettings


class DALPhotobookShare(
    AsyncPostgreSQLDAL[
        DAOPhotobookShare, DAOPhotobookShareCreate, DAOPhotobookShareUpdate
    ]
):
    model = DAOPhotobookShare


class DALPhotobooksAssetsRel(
    AsyncPostgreSQLDAL[
        DAOPhotobooksAssetsRel,
        DAOPhotobooksAssetsRelCreate,
        DAOPhotobooksAssetsRelUpdate,
    ]
):
    model = DAOPhotobooksAssetsRel


class DALNotifications(
    AsyncPostgreSQLDAL[DAONotifications, DAONotificationsCreate, DAONotificationsUpdate]
):
    model = DAONotifications


class DALNotificationDeliveryAttempts(
    AsyncPostgreSQLDAL[
        DAONotificationDeliveryAttempts,
        DAONotificationDeliveryAttemptsCreate,
        DAONotificationDeliveryAttemptsUpdate,
    ]
):
    model = DAONotificationDeliveryAttempts


class DALNotificationOutbox(
    AsyncPostgreSQLDAL[
        DAONotificationOutbox,
        DAONotificationOutboxCreate,
        DAONotificationOutboxUpdate,
    ]
):
    model = DAONotificationOutbox


class DALShares(
    AsyncPostgreSQLDAL[
        DAOShares,
        DAOSharesCreate,
        DAOSharesUpdate,
    ]
):
    model = DAOShares


class DALPaymentEvents(
    AsyncPostgreSQLDAL[
        DAOPaymentEvents,
        DAOPaymentEventsCreate,
        DAOPaymentEventsUpdate,
    ]
):
    ENSURE_JSON_SAFETY_FIELDS = {"payload"}
    model = DAOPaymentEvents


class DALGiftcards(
    AsyncPostgreSQLDAL[
        DAOGiftcards,
        DAOGiftcardsCreate,
        DAOGiftcardsUpdate,
    ]
):
    model = DAOGiftcards


class DALGiftcardEvents(
    AsyncPostgreSQLDAL[
        DAOGiftcardEvents,
        DAOGiftcardEventsCreate,
        DAOGiftcardEventsUpdate,
    ]
):
    model = DAOGiftcardEvents


class DALEntitlements(
    AsyncPostgreSQLDAL[
        DAOEntitlements,
        DAOEntitlementsCreate,
        DAOEntitlementsUpdate,
    ]
):
    model = DAOEntitlements


class DALSubscriptionEvents(
    AsyncPostgreSQLDAL[
        DAOSubscriptionEvents, DAOSubscriptionEventsCreate, DAOSubscriptionEventsUpdate
    ]
):
    ENSURE_JSON_SAFETY_FIELDS = {"payload"}
    model = DAOSubscriptionEvents


__all__ = [
    ##########################################################
    # DALs
    ##########################################################
    "DALAssets",
    "DALJobs",
    "DALJobEvents",
    "DALEntitlements",
    "DALPages",
    "DALPagesAssetsRel",
    "DALPhotobooks",
    "DALPhotobookBookmarks",
    "DALPhotobookSettings",
    "DALPhotobookComments",
    "DALPhotobooksAssetsRel",
    "DALNotifications",
    "DALShareChannels",
    "DALNotificationDeliveryAttempts",
    "DALNotificationOutbox",
    "DALShares",
    "DALPayments",
    "DALPaymentEvents",
    "DALGiftcards",
    "DALGiftcardEvents",
    "DALSubscriptionEvents",
    ##########################################################
    # DAL base
    ##########################################################
    "AsyncPostgreSQLDAL",
    "FilterOp",
    "InvalidFilterFieldError",
    "OrderDirection",
    ##########################################################
    # ORM objects
    ##########################################################
    "DAOAssets",
    "DAOJobs",
    "DAOJobEvents",
    "DAOPages",
    "DAOPagesAssetsRel",
    "DAOPhotobooks",
    "DAOEntitlements",
    "DAOUsers",
    "DAOPhotobookBookmarks",
    "DAOPhotobookSettings",
    "DAOPhotobookComments",
    "DAOPhotobooksAssetsRel",
    "DAOShareChannels",
    "DAONotificationDeliveryAttempts",
    "DAOShares",
    "DAONotificationOutbox",
    "DAOPaymentEvents",
    "DAOPayments",
    "DAOGiftcards",
    "DAOGiftcardEvents",
    "DAOSubscriptionEvents",
    ##########################################################
    # Schemas
    ##########################################################
    "DAOAssetsCreate",
    "DAOAssetsUpdate",
    "DAOJobsCreate",
    "DAOJobsUpdate",
    "DAOJobEventsCreate",
    # "DAOJobEventsUpdate",   # Updating job events is not allowed, as it's an append-only log trail
    "DAOPagesCreate",
    "DAOPagesUpdate",
    "DAOPagesAssetsRelCreate",
    "DAOPagesAssetsRelUpdate",
    "DAOPhotobooksCreate",
    "DAOPhotobooksUpdate",
    "DAOUsersCreate",
    "DAOUsersUpdate",
    "DAOPhotobookBookmarksUpdate",
    "DAOPhotobookBookmarksCreate",
    "DAOPhotobookSettingsUpdate",
    "DAOPhotobookSettingsCreate",
    "DAOPhotobookCommentsUpdate",
    "DAOPhotobookCommentsCreate",
    "DAOPhotobooksAssetsRelUpdate",
    "DAOPhotobooksAssetsRelCreate",
    "DAOShareChannelsCreate",
    "DAOShareChannelsUpdate",
    "DAONotificationDeliveryAttemptsCreate",
    # "DAONotificationDeliveryAttemptsUpdate",  # Updating delivery attempts is not allowed, as it's an append-only log trail
    "DAOSharesCreate",
    "DAOSharesUpdate",
    "DAONotificationOutboxCreate",
    "DAONotificationOutboxUpdate",
    "DAOPaymentEventsCreate",
    # "DAOPaymentEventsUpdate",   # Updating is not allowed, as it's an append-only log trail
    "DAOPaymentsCreate",
    "DAOPaymentsUpdate",
    "DAOGiftcardsCreate",
    "DAOGiftcardsUpdate",
    "DAOGiftcardEventsCreate",
    "DAOGiftcardEventsUpdate",  # Updating is not allowed, as it's an append-only log trail
    "DAOSubscriptionEventsCreate",
    "DAOSubscriptionEventsUpdate",  # Updating is not allowed, as it's an append-only log trail
    "DAOEntitlementsCreate",
    "DAOEntitlementsUpdate",
    ##########################################################
    # Utils
    ##########################################################
    "safe_commit",
    "safe_transaction",
    "locked_row_by_id",
]
