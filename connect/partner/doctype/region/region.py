# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Region(Document):
	def validate(self):
		self.validate_unique_countries()

	def on_update(self):
		self.set_partner_regions()

	def validate_unique_countries(self):
		countries = [row.country for row in self.countries]
		repeated = {country for country in countries if countries.count(country) > 1}
		if repeated:
			frappe.throw(_("{0} is listed more than once.").format(", ".join(sorted(repeated))))

		taken = frappe.get_all(
			"Region Country",
			filters={"parenttype": "Region", "parent": ["!=", self.name], "country": ["in", countries or [""]]},
			fields=["country", "parent"],
		)
		if taken:
			frappe.throw(
				_("A country can belong to one region only. {0}").format(
					", ".join(_("{0} is in {1}.").format(row.country, row.parent) for row in taken)
				)
			)

	def set_partner_regions(self):
		"""Partner.region is a stored copy for filtering, so keep it in step with this region's countries."""
		partner = frappe.qb.DocType("Partner")
		countries = [row.country for row in self.countries] or [""]
		frappe.qb.update(partner).set(partner.region, None).where(
			(partner.region == self.name) & partner.country.notin(countries)
		).run()
		frappe.qb.update(partner).set(partner.region, self.name).where(partner.country.isin(countries)).run()


def get_region_of_country(country: str | None) -> str | None:
	if not country:
		return None
	return frappe.db.get_value("Region Country", {"parenttype": "Region", "country": country}, "parent")


def get_filter_countries() -> dict[str, list[str]]:
	"""The directory's country filter: each region's countries marked Show in Directory Filter.
	Regions come in the order they were made, countries in table order."""
	region = frappe.qb.DocType("Region")
	row = frappe.qb.DocType("Region Country")
	rows = (
		frappe.qb.from_(row)
		.join(region)
		.on(region.name == row.parent)
		.select(row.parent, row.country)
		.where((row.parenttype == "Region") & (row.show_in_filter == 1))
		.orderby(region.creation)
		.orderby(row.idx)
		.run(as_dict=True)
	)

	countries_by_region = {}
	for country_row in rows:
		countries_by_region.setdefault(country_row.parent, []).append(country_row.country)
	return countries_by_region
