# Copyright (c) 2026
# For license information, please see license.txt

from connect.partner.doctype.partner.listing_review import review_partner_listings
from connect.partner.doctype.partner_tier.tier_review import review_partner_tiers
from connect.partner.press_integration import update_all_partner_revenue


def run_daily_review() -> None:
	"""Daily, in this order: each partner's revenue from Frappe Cloud, then its tier from that revenue,
	then whether the directory shows it, by the certificates its new tier needs."""
	update_all_partner_revenue()
	review_partner_tiers()
	review_partner_listings()
