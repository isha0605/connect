# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Max, Min


class StarterPack(Document):
	"""A fixed-price pack Frappe sells. Prices are Frappe's, not a partner's."""


# Sections kept on the pack for Frappe's own reference, not shown to buyers.
HIDDEN_SECTION_LABELS = {"Not included"}


def get_catalog():
	"""Active packs, each with its View details sections grouped by module, plus what
	the cost card needs to show a total: the GST rate and currency."""
	settings = frappe.get_cached_doc("Starter Pack Settings")
	packs = []
	for name in frappe.get_all("Starter Pack", filters={"is_active": 1}, pluck="name", order_by="creation"):
		pack = frappe.get_cached_doc("Starter Pack", name)
		modules = {}
		for row in pack.sections:
			if row.label in HIDDEN_SECTION_LABELS:
				continue
			modules.setdefault(row.module_name, []).append({"label": row.label, "content": row.content})
		packs.append(
			{
				"pack_key": pack.pack_key,
				"pack_name": pack.pack_name,
				"price": pack.price,
				"total_hours": pack.total_hours,
				"delivery_days": pack.delivery_days,
				"modules": [{"module_name": m, "sections": s} for m, s in modules.items()],
			}
		)
	return {"packs": packs, "gst_rate": settings.gst_rate, "currency": settings.currency}


def get_hours_range() -> dict | None:
	"""The fewest and most hours across active packs, or None when no pack is active."""
	pack = frappe.qb.DocType("Starter Pack")
	fewest, most = (
		frappe.qb.from_(pack)
		.select(Min(pack.total_hours), Max(pack.total_hours))
		.where(pack.is_active == 1)
		.run()[0]
	)
	if most is None:
		return None

	return {"min": fewest, "max": most}
