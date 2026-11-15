# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.model.document import Document


class PartnerTier(Document):
	"""A partner level and what a partner needs to reach it. Its fields match Press's Partner Tier, so tiers
	copy across as they are."""


def get_tier_order() -> list[str]:
	"""Tiers, highest first. Entry and Beginner both need no revenue, so certificates break the tie."""
	return frappe.get_all(
		"Partner Tier", order_by="target_in_inr desc, certificates_required desc", pluck="name"
	)
