# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class StarterPack(Document):
	"""A fixed-price pack Frappe sells. Prices are Frappe's, not a partner's."""

	pass


def get_catalog():
	"""Active packs, each with its View details sections grouped by module, plus what
	the cost card needs to show a total: the GST rate and currency."""
	settings = frappe.get_cached_doc("Starter Pack Settings")
	packs = []
	for name in frappe.get_all("Starter Pack", filters={"is_active": 1}, pluck="name", order_by="creation"):
		pack = frappe.get_cached_doc("Starter Pack", name)
		modules = {}
		for row in pack.sections:
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
