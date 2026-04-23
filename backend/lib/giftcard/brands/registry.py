# backend/lib/giftcard/brands/registry.py

import logging
from typing import Optional

from pydantic import BaseModel, Field

from backend.db.data_models import GiftcardProvider


class BrandRegistryEntry(BaseModel):
    brand_code: str = Field(min_length=1)  # our internal canonical code/slug
    display_name: str = Field(min_length=1)
    preferred_giftcard_provider: GiftcardProvider
    description: str
    terms_and_conditions: str
    giftbit_brand_code: Optional[str] = None
    main_placeholder_color: str = Field(description="Hex like #AABBCC")
    dark_background_color: str = Field(description="Hex like #AABBCC")
    giftcard_visual_filename: str


_AMAZON = BrandRegistryEntry(
    brand_code="amazon_us",
    display_name="Amazon",
    preferred_giftcard_provider=GiftcardProvider.AGCOD,
    description="""Amazon Gift Cards never expire and can be redeemed towards books, electronics, music, and more. Amazon.com is the place to find and discover almost any thing you want to buy online at a great price.""",
    terms_and_conditions="""Redeemable only for eligible items on Amazon.com or certain US affiliates. Other restrictions apply. No resale, replacements, or refunds, except as required by law. No expiration date or service fees. See full terms: www.amazon.com/gc-legal.""",
    giftbit_brand_code=None,
    main_placeholder_color="#252f3d",
    dark_background_color="#252f3d",
    giftcard_visual_filename="amazon_us.png",
)

_TARGET = BrandRegistryEntry(
    brand_code="target",
    display_name="Target",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""Target GiftCards are the rewarding choice, letting you shop for thousands of items at more than 1,800 Target stores in the U.S. and online at Target.com. From toys and electronics to clothing and housewares, find exactly what you're looking for at Target.""",
    terms_and_conditions="""Redeemable for merchandise or services (other than gift cards and prepaid cards) at Target stores in the U.S. or Target.com, and cannot be redeemed for cash or credit except where required by law. No value until purchased. For balance information, visit Target.com/giftcards or call 1-800-544-2943. To replace the remaining value on a lost, stolen or damaged card with the original purchase receipt, call 1-800-544-2943. ©2021 Target Brands, Inc. The Bullseye Design and Target are registered trademarks of Target Brands, Inc.\nTarget and the Bullseye Design are registered trademarks of Target Brands, Inc. Terms and conditions are applied to gift cards. Target is not a participating partner in or sponsor of this offer.""",
    giftbit_brand_code="target",
    main_placeholder_color="#CC0000",
    dark_background_color="#CC0000",
    giftcard_visual_filename="target.png",
)


_STARBUCKS = BrandRegistryEntry(
    brand_code="starbucks",
    display_name="Starbucks",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""Treat yourself - or someone else - to something special at Starbucks with a Starbucks card, which you can use towards premium coffee, tea, refreshers, lunch, pastries and more. And if you register your card with the Starbucks Rewards™ loyalty program (starbucks.com/rewards), you can earn even more free food and drinks.""",
    terms_and_conditions="""The Starbucks word mark and the Starbucks Logo are trademarks of Starbucks Corporation. Starbucks is also the owner of the Copyrights in the Starbucks Logo and the Starbucks Card designs. All rights reserved. Starbucks is not a participating partner or sponsor in this offer. The eGift amount reflects the balance of the card at the time of delivery and is not necessarily the current balance of the card. Reload your Card, check your balance and find out how to register and protect your Card balance at participating Starbucks stores, starbucks.com/card or 1-800-782-7282. Your Starbucks Card may only be used for making purchases at participating Starbucks stores. Cannot be redeemed for cash unless required by law. Refunds only provided for unused Cards with the original receipt. This card does not expire, nor does Starbucks charge fees. Complete terms and conditions available on our website. Use of this Card constitutes acceptance of these terms and conditions. Treat this eGift like Cash. Full Terms & Conditions: https://www.starbucks.com/gift-cards/manage/card-terms-and-conditions. Contact Us: https://customerservice.starbucks.com/app/contact/ask/. Privacy Policy: https://www.starbucks.com/about-us/company-information/online-policies/privacy-policy.""",
    giftbit_brand_code="starbucksus",
    main_placeholder_color="#326c3a",
    dark_background_color="#326c3a",
    giftcard_visual_filename="starbucks.png",
)

_WALMART = BrandRegistryEntry(
    brand_code="walmart",
    display_name="Walmart",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""With a Walmart eGift Card, you get low prices every day on thousands of popular products in stores or online at Walmart.com. You’ll find a wide assortment of top electronics, toys, home essentials and more. Plus, cards don’t expire and you never pay any fees.""",
    terms_and_conditions="""To report fraud or to check balance, call 1-888-537-5503. Terms, including a mandatory arbitration provision, apply to use of this card. See full terms, which may change without notice, at http://Walmart.com/giftcardterms. Use this card at any Walmart store or Sam’s Club in the U.S. or Puerto Rico, or online at https://www.walmart.com/, Samsclub.com, or at any location listed at http://Walmart.com/giftcardterms. Card balance is a liability of Wal-Mart Stores Arkansas, LLC. No cash redemption unless required by law. No replacement for lost/stolen cards. Walmart may refuse to accept this card and take action, including balance forfeiture, for fraud, abuse or violations of terms. Never give card numbers to someone you don’t know. For more information on how to protect yourself from fraud, visit https://Walmart.com/fraud.""",
    giftbit_brand_code="walmart",
    main_placeholder_color="#0053E2",
    dark_background_color="#0053E2",
    giftcard_visual_filename="walmart.png",
)

_DOORDASH = BrandRegistryEntry(
    brand_code="doordash",
    display_name="DoorDash",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""Give the gift of delivery with a DoorDash gift card. The DoorDash app connects your favorite people with the best of their neighborhood, including restaurants, convenience stores, grocery stores, pet supplies and more. Choose from more than 310,000 local and national restaurants and stores across 4,000 cities in the US & Canada. Giving the gift of delivery allows your loved ones to have easier evenings, happier days, and more time to enjoy the people and things they love.""",
    terms_and_conditions="""DoorDash gift card can be redeemed only for purchases of eligible orders placed on www.doordash.com or in the DoorDash app in the U.S. Must have a valid DoorDash account to redeem. Card cannot be returned or exchanged for cash unless required by law. Does not expire, and no fees are deducted. Not replaceable if lost, stolen or damaged. No value until activated. All card redemptions are final and may not be reversed. Use of this card constitutes acceptance of its terms and conditions. For full terms and conditions (including arbitration agreement and class action waiver), which are subject to change, please visit https://help.doordash.com/legal/document?locale=en-US&region=US&type=cx-giftcard-terms. Card is issued by and solely an obligation of DoorDash Giftcards LLC. For more information, please call us at 855-431-0459.""",
    giftbit_brand_code="doordashus",
    main_placeholder_color="#ffffff",
    dark_background_color="#ff3008",
    giftcard_visual_filename="doordash.png",
)

_UBER = BrandRegistryEntry(
    brand_code="uber",
    display_name="Uber",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""The Uber and Uber Eats apps connect you to a reliable ride in minutes and hundreds of your favorite local restaurants. Order the food you love, delivered to your door. Gift Uber rides to the people you care about, or add value to your Uber account.""",
    terms_and_conditions="""By using this gift card, you accept the following terms and conditions: This card is redeemable via the Uber® or Uber Eats app within the U.S. in cities where Uber or Uber Eats is available. Funds do not expire. The card is non-reloadable and, except where required by law, cannot be redeemed for cash, refunded, or returned. You may be required to add a secondary payment method to use this gift card with the Uber or Uber Eats app. The card is not redeemable outside the U.S. The issuer is not responsible for lost or stolen cards, or unauthorized use. This card is issued by The Bancorp Bank, N.A. For full terms and conditions and customer service, visit uber.com/legal/gift.""",
    giftbit_brand_code="uber",
    main_placeholder_color="#09091a",
    dark_background_color="#09091a",
    giftcard_visual_filename="uber.png",
)

_LYFT = BrandRegistryEntry(
    brand_code="lyft",
    display_name="Lyft",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""Ride, bike, scoot. There’s lots to do in your city, and we’ve got the rides to help you enjoy it all. Wherever you’re headed, download the Lyft app and get going.""",
    terms_and_conditions="""This gift card (“GC”) is redeemable only for eligible goods and services via the Lyft platform (“Lyft App”). The entire value will be credited to your Lyft account upon redemption in the Lyft App. Except where required by law, this GC is not reloadable, not redeemable for cash, not refundable, and cannot be resold. Safeguard the GC, it will not be replaced if lost, stolen, or misused. Lyft, Inc. is the GC issuer. Issuer duties may be delegated without recourse. For complete terms and conditions see https://lyft.com/terms/lyft-cash (“Terms”). Purchase, use, or acceptance of this GC constitutes acceptance of the Terms, including terms regarding dispute resolution. Alternative payment method required to use the Lyft App. No expiration date or service fees. Subject to Lyft Terms of Service available at https://lyft.com/terms. 2020 Lyft, Inc. LYFT and LYFT & Design are trademarks owned by Lyft, Inc. All rights reserved.""",
    giftbit_brand_code="lyftus",
    main_placeholder_color="#ff00bf",
    dark_background_color="#ff00bf",
    giftcard_visual_filename="lyft.png",
)

_HOME_DEPOT = BrandRegistryEntry(
    brand_code="home_depot",
    display_name="Home Depot",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""The Home Depot® is helping people do more with their hard earned money. From modest projects like updating your bath to small projects with a big impact like paint. The Home Depot can help you get more done in your home for less. That’s the power of the world’s largest home improvement retailer. The Home Depot. More saving. More doing.""",
    terms_and_conditions="""Gift Cards are redeemable any Home Depot store in the U.S. and at Homedepot.com. Kiind Inc. is not affiliated with The Home Depot®. The Home Depot® is not a sponsor of this promotion. The Home Depot® is a registered trademark of Homer TLC, Inc Giftbit Inc. and/or Giftbit, Corp. doing business through www.giftbit.com and/or through Giftbit's mobile application(s) and other services.""",
    giftbit_brand_code="homedepot",
    main_placeholder_color="#ffffff",
    dark_background_color="#f96302",
    giftcard_visual_filename="home_depot.png",
)

_LOWES = BrandRegistryEntry(
    brand_code="lowes",
    display_name="Lowe’s",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""Lowe’s®, one of the nation’s leading home improvement retailers, has more than 1,830 stores nationwide. Lowe’s offers everything from power tools and appliances to lighting and home décor. With over 40,000 in stock items to choose from, the Lowe’s Gift Card can help start any home project large or small.""",
    terms_and_conditions="""This is not a credit/debit card and has no implied warranties. This card is not redeemable for cash unless required by law and cannot be used to make payments on any charge account. Lowe’s® reserves the right to deactivate or reject any Gift Card issued or procured, directly or indirectly, in connection with fraudulent actions, unless prohibited by law. Lost or stolen Gift Cards can only be replaced upon presentation of original sales receipt for any remaining balance. It will be void if altered or defaced. To check your Lowe’s® Gift Card balance, visit Lowes.com/GiftCards, call 1-800-560-7172 or see the Customer Service Desk in any Lowe’s® store. LOWE'S® and the GABLE MANSARD DESIGN are registered trademarks and service marks of LF, LLC.""",
    giftbit_brand_code="lowes",
    main_placeholder_color="#ffffff",
    dark_background_color="#004990",
    giftcard_visual_filename="lowes.png",
)

_SEPHORA = BrandRegistryEntry(
    brand_code="sephora",
    display_name="Sephora",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""Available in the USA online and in store. Sephora is a visionary beauty-retail concept founded in France by Dominique Mandonnaud in 1970. Sephora's unique, open-sell environment features an ever-increasing amount of classic and emerging brands across a broad range of product categories including skincare, color, fragrance, body, smilecare, and haircare, in addition to Sephora's own private label. This gift is sent in US Currency.""",
    terms_and_conditions="""Use of this Gift Card constitutes acceptance of the following terms: Gift Cards are redeemable for merchandise sold in U.S. Sephora stores, on Sephora.com for U.S. orders only, through the Sephora catalog or at Sephora inside JCPenney stores. Gift Cards are not redeemable for cash (except as required by law). This Gift Card does not expire and is valid until redeemed.  The value of this Gift Card will not be replaced if the card is lost, stolen, altered or destroyed.  Treat this card as cash. If your purchase exceeds the unused balance of the Gift Card, you must pay the excess at the time of purchase. For questions regarding Gift Cards, please contact hello@giftbit.com or 1-877-554-2186. For Sephora store locations, to order, or for card balance, please visit Sephora.com or call 1.877.SEPHORA. Issued by Sephora USA, Inc. Giftbit Inc. and/or Giftbit, Corp. doing business through www.giftbit.com and/or through Giftbit's mobile application(s) and other services.""",
    giftbit_brand_code="sephora",
    main_placeholder_color="#ffffff",
    dark_background_color="#000000",
    giftcard_visual_filename="sephora.png",
)

_ULTA = BrandRegistryEntry(
    brand_code="ulta",
    display_name="Ulta Beauty",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""Ulta Beauty is the largest beauty retailer in the United States and the premier beauty destination for cosmetics, fragrance, skin care, hair care products, and salon services. Ulta Beauty offers more than 25,000 products from approximately 500 well-established and emerging beauty brands across all categories and price points, including Ulta Beauty’s own private label. Ulta Beauty also offers a full-service salon in every store featuring hair, skin, brow, and makeup services. Ulta Beauty eGift Cards are the perfect gift for any occasion, with no service fees and no expiration date. Ulta Beauty eGift Cards are accepted at Ulta Beauty stores nationwide and at Ulta.com.""",
    terms_and_conditions="""Protect this card like cash. The card is not valid for use until purchased and activated. Purchase, use, or acceptance of this card constitutes acceptance of the Terms. The card is usable up to the remaining balance to purchase goods or services at Ulta Beauty stores or at Ulta.com. It is not redeemable for cash except as required by applicable law and is not redeemable at Ulta Beauty at Target or on Target.com. The card does not expire or incur fees. If lost, stolen, or damaged, the card will not be replaced without proof of purchase. For balance inquiries, additional information, and changes to the Terms (Issuer reserves the right to change the Terms at any time), visit www.ulta.com/guestservices/gift-cards/faq or call 1-888-566-2736.""",
    giftbit_brand_code="ultabeauty",
    main_placeholder_color="#F47D39",
    dark_background_color="#F47D39",
    giftcard_visual_filename="ulta.png",
)

_APPLE = BrandRegistryEntry(
    brand_code="apple",
    display_name="Apple",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""For all things Apple - products, accessories, apps, games, music, movies, TV shows, iCloud+, and more. Use it at any Apple Store, apple.com, in the Apple Store app, the App Store, iTunes, Apple Music, Apple TV+, Apple News+, Apple Books, Apple Arcade, iCloud+, Fitness+, Apple One, and other Apple properties in the US only.""",
    terms_and_conditions="""Valid only for U.S. transactions in Apple properties. For assistance, visit support.apple.com/giftcard or call 1-800-275-2273. Not redeemable at Apple resellers or for cash, and no resale, refunds, or exchanges, except as required by law. Apple is not responsible for unauthorized use. Terms apply; see apple.com/us/go/legal/gc. Issued by Apple Value Services, LLC (AVS). ©2025 Apple Inc. All rights reserved.""",
    giftbit_brand_code="itunesus",
    main_placeholder_color="#ffffff",
    dark_background_color="#000000",
    giftcard_visual_filename="apple.png",
)


_GOOGLE_PLAY = BrandRegistryEntry(
    brand_code="google_play",
    display_name="Google Play",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""With millions of apps, games, and more to discover, there's something for everyone on Google Play. Use a Google Play gift code to explore a world of endless play, from your go-to games to the apps you can’t live without. No fees, no expiration dates, and no credit card required to start playing – which means it’s the perfect gift for anyone. Even if that person is you.""",
    terms_and_conditions="""See play.google.com/us-card-terms for full terms. Must be 13+ years of age, US resident. Google Play card is issued by Google Arizona LLC (“GAZ”). Requires Google Payments account and internet access to redeem. Redeemed balance is maintained by GAZ’s affiliate, Google Payment Corp. (“GPC”), in your Google Payments account. Usable for purchases of eligible items on Google Play only. Not usable for hardware and certain subscriptions. Other limits may apply. No fees or expiration dates. Except as required by law, card is not redeemable for cash or other cards; not reloadable or refundable; cannot be combined with other non-Google Play balances in your Google Payments account, resold, exchanged or transferred for value. User responsible for loss of card. For assistance or to view your Google Play card balance, visit support.google.com/googleplay/go/cardhelp.""",
    giftbit_brand_code="googleplay",
    main_placeholder_color="#ffffff",
    dark_background_color="#000000",
    giftcard_visual_filename="googleplay.png",
)

_NIKE = BrandRegistryEntry(
    brand_code="nike",
    display_name="Nike",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""Available in the USA. NIKE is the world’s leading innovator in athletic footwear, apparel, equipment, and accessories. Nike Gift Cards are redeemable online at Nike.com, Converse.com, and at any Nike-owned or Converse-owned retail location in the US and Puerto Rico. This card has a USD balance.""",
    terms_and_conditions="""This Gift Card is redeemable online at Nike.com, Converse.com, and at any Nike-owned or Converse-owned retail stores in the United States and Puerto Rico. Gift Cards may not be returned or redeemed for cash, except as required by law. Gift Cards will not be replaced if lost or stolen. No refunds or exchanges on Gift Cards. For complete terms and conditions, or balance inquiries, please visit Nike.com/GiftCards or call 1-800-806-6453. The purchase, acceptance, or use of this Gift Card constitutes acceptance of these terms and conditions.""",
    giftbit_brand_code="nike",
    main_placeholder_color="#fe4106",
    dark_background_color="#fe4106",
    giftcard_visual_filename="nike.png",
)

_ADIDAS = BrandRegistryEntry(
    brand_code="adidas",
    display_name="adidas",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""For over 60 years adidas has been part of the world of sports on every level, delivering state-of-the-art sports footwear, apparel and accessories. Today, the adidas Group is a global leader in the sporting goods industry and its brands offer a broad portfolio of innovative products. Use this gift card at adidas retail locations or online at www.adidas.com.""",
    terms_and_conditions="""This adidas gift card is intended for the purchase of adidas merchandise and is redeemable at adidas retail stores and online at adidas.com. It may not be redeemed for cash except where required by law. For account balance inquiry, please visit adidas.com/giftcard. This gift card will not be replaced if lost or stolen. Use of this card constitutes acceptance of the terms and conditions found on adidas.com.""",
    giftbit_brand_code="adidas",
    main_placeholder_color="#000000",
    dark_background_color="#000000",
    giftcard_visual_filename="adidas.png",
)

_LULULEMON = BrandRegistryEntry(
    brand_code="lululemon",
    display_name="lululemon",
    preferred_giftcard_provider=GiftcardProvider.GIFTBIT,
    description="""lululemon creates high-performance athletic apparel for yoga, running, training, and all your active pursuits. Redeem your eGift Card in-store or at lululemon.com for premium gear that supports your movement and lifestyle.""",
    terms_and_conditions="""This gift card can be used online at https://www.lululemon.com or in any lululemon store in the United States. It cannot be redeemed for cash except where required by law or when the remaining balance is under $10. lululemon is not responsible for lost, stolen, or misused cards. Gift cards cannot be used to purchase other gift cards. No expiration date or additional fees apply. For full terms and conditions, visit: https://info.lululemon.com/legal/terms-of-use.""",
    giftbit_brand_code="lululemonus",
    main_placeholder_color="#ffffff",
    dark_background_color="#D41935",
    giftcard_visual_filename="lululemon.png",
)


# brand_code -> entry
_AVAILABLE_BRANDS: dict[str, BrandRegistryEntry] = {
    "amazon_us": _AMAZON,
    "target": _TARGET,
    "starbucks": _STARBUCKS,
    "walmart": _WALMART,
    "doordash": _DOORDASH,
    "uber": _UBER,
    "lyft": _LYFT,
    "home_depot": _HOME_DEPOT,
    "lowes": _LOWES,
    "sephora": _SEPHORA,
    "ulta": _ULTA,
    "apple": _APPLE,
    "google_play": _GOOGLE_PLAY,
    "nike": _NIKE,
    "adidas": _ADIDAS,
    "lululemon": _LULULEMON,
}


class GiftcardBrandRegistry:
    def __init__(self) -> None:
        self._registry = self._validate_and_load_registry(_AVAILABLE_BRANDS)

    def get_brand_by_code(self, brand_code: str) -> Optional[BrandRegistryEntry]:
        return self._registry.get(brand_code, None)

    def get_all_brands(self) -> dict[str, BrandRegistryEntry]:
        return self._registry

    def get_s3_path_for_filename(self, filename: str) -> str:
        return f"public/giftcard/visual/{filename}"

    def get_public_url_for_filename(
        self,
        filename: str,
    ) -> str:
        return f"https://pensieve0618-public-assets.s3.us-east-2.amazonaws.com/{self.get_s3_path_for_filename(filename)}"

    def _validate_and_load_registry(
        self,
        source: dict[str, BrandRegistryEntry],
    ) -> dict[str, BrandRegistryEntry]:
        """
        Filters the input registry using these rules:
        1) If preferred_giftcard_provider == GiftcardProvider.GIFTBIT, giftbit_brand_code must be non-None.
        2) description and terms_and_conditions must contain the brand_code (case-insensitive).
        3) The dict key must match entry.brand_code exactly.

        Entries failing any rule are discarded. Returns the validated dict.
        """
        valid: dict[str, BrandRegistryEntry] = {}

        for key, entry in source.items():
            errors: list[str] = []

            # 1) Giftbit requires a giftbit_brand_code
            if (
                entry.preferred_giftcard_provider == GiftcardProvider.GIFTBIT
                and not entry.giftbit_brand_code
            ):
                errors.append("giftbit_brand_code is required when provider is GIFTBIT")

            # 2) description & terms must mention brand_code (case-insensitive)
            display_name_ci = entry.display_name.casefold()
            if display_name_ci not in entry.description.casefold():
                errors.append(
                    "description must contain display_name (case-insensitive)"
                )
            if display_name_ci not in entry.terms_and_conditions.casefold():
                errors.append(
                    "terms_and_conditions must contain display_name (case-insensitive)"
                )

            # 3) dict key must match entry.brand_code
            if key != entry.brand_code:
                errors.append(
                    f"dict key '{key}' does not match entry.brand_code '{entry.brand_code}'"
                )

            if errors:
                logging.warning(
                    "[brand-registry] Discarding brand '%s': %s",
                    key,
                    "; ".join(errors),
                )
                continue

            valid[key] = entry

        logging.info(
            "[brand-registry] Loaded %d/%d valid brand entries",
            len(valid),
            len(source),
        )
        return valid


REGISTRY_SINGLETON: GiftcardBrandRegistry = GiftcardBrandRegistry()
