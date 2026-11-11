# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Lower

# Short names partners typed before country became a Country link.
ALIASES = {
	"uae": "United Arab Emirates",
	"usa": "United States",
	"us": "United States",
	"uk": "United Kingdom",
	"congo - kinshasa": "Congo, The Democratic Republic of the",
}


def execute():
	"""Turns each Partner.country into a Country name, then sets every partner's region from its Region.
	Stops and lists the values it cannot match, so no partner silently loses its country."""
	partner = frappe.qb.DocType("Partner")
	values = frappe.qb.from_(partner).select(partner.country).distinct().where(partner.country.isnotnull()).run(pluck=True)

	unmatched = []
	for value in values:
		if not value.strip():
			frappe.qb.update(partner).set(partner.country, None).where(partner.country == value).run()
			continue

		country = find_country(value)
		if not country:
			unmatched.append(value)
		elif country != value:
			frappe.qb.update(partner).set(partner.country, country).where(partner.country == value).run()

	if unmatched:
		frappe.throw(
			_("These Partner countries are not in the Country list: {0}. Correct them in Desk and run bench migrate again.").format(
				", ".join(repr(value) for value in unmatched)
			)
		)

	set_partner_regions()


def find_country(value: str) -> str | None:
	text = value.strip()
	country = frappe.qb.DocType("Country")
	match = (
		frappe.qb.from_(country)
		.select(country.name)
		.where((Lower(country.name) == text.lower()) | (Lower(country.code) == text.lower()))
		.run(pluck=True)
	)
	return match[0] if match else ALIASES.get(text.lower())


def set_partner_regions():
	partner = frappe.qb.DocType("Partner")
	frappe.qb.update(partner).set(partner.region, None).run()
	for region in frappe.get_all("Region", pluck="name"):
		frappe.get_doc("Region", region).set_partner_regions()
