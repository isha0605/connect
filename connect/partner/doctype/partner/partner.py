# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt

COUNTRY_TO_REGION = {
	"united states": "North America",
	"usa": "North America",
	"canada": "North America",
	"mexico": "North America",
	"united kingdom": "Europe",
	"uk": "Europe",
	"germany": "Europe",
	"france": "Europe",
	"netherlands": "Europe",
	"spain": "Europe",
	"italy": "Europe",
	"ireland": "Europe",
	"sweden": "Europe",
	"switzerland": "Europe",
	"india": "Asia Pacific",
	"china": "Asia Pacific",
	"japan": "Asia Pacific",
	"singapore": "Asia Pacific",
	"australia": "Asia Pacific",
	"new zealand": "Oceania",
	"indonesia": "Asia Pacific",
	"philippines": "Asia Pacific",
	"vietnam": "Asia Pacific",
	"malaysia": "Asia Pacific",
	"uae": "Middle East",
	"united arab emirates": "Middle East",
	"saudi arabia": "Middle East",
	"qatar": "Middle East",
	"israel": "Middle East",
	"south africa": "Africa",
	"nigeria": "Africa",
	"kenya": "Africa",
	"egypt": "Africa",
	"brazil": "Latin America",
	"argentina": "Latin America",
	"colombia": "Latin America",
	"chile": "Latin America",
}


DIMENSION_SCORE_FIELDS = (
	"business_understanding",
	"implementation_quality",
	"communication",
	"timeliness",
	"support",
	"technical_expertise",
)


class Partner(Document):
	def before_save(self):
		self.region = COUNTRY_TO_REGION.get((self.country or "").strip().lower(), "Other")


def recompute_rating_from_reviews(partner_name, exclude=None):
	"""Recompute a Partner's rating/reviews_count/dimension scores from its
	(now standalone) Partner Review records. Called via doc_events on Partner
	Review insert/update/trash — reviews are no longer a Partner child table,
	so this can't run inside Partner.before_save anymore.

	`exclude`: on_trash fires *before* the row is actually removed from the DB,
	so a plain re-query would still count the row being deleted. Pass the
	doc's own name there to exclude it from the recompute.
	"""
	filters = {"partner": partner_name}
	if exclude:
		filters["name"] = ["!=", exclude]
	reviews = frappe.get_all(
		"Partner Review",
		filters=filters,
		fields=["rating", *DIMENSION_SCORE_FIELDS],
	)

	values = {"reviews_count": len(reviews)}
	values["rating"] = sum(flt(r.rating) for r in reviews) / len(reviews) if reviews else 0

	for dimension in DIMENSION_SCORE_FIELDS:
		dim_values = [flt(r.get(dimension)) for r in reviews if r.get(dimension)]
		values[f"{dimension}_score"] = sum(dim_values) / len(dim_values) if dim_values else 0

	frappe.db.set_value("Partner", partner_name, values, update_modified=False)
