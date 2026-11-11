# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.partner.doctype.region.region import get_filter_countries, get_region_of_country
from connect.patches.link_partner_country_to_country import execute as link_partner_country, find_country

REGION = "_Test Region"
LISTED_COUNTRY = "_Test Land Listed"
OTHER_COUNTRY = "_Test Land Other"
NO_REGION_COUNTRY = "_Test Land Without Region"
PARTNER = "_Test Region Partner"


def make_country(name):
	# Every real country already has a region, and Country.validate accepts only real ISO codes,
	# so the test countries skip validation.
	if not frappe.db.exists("Country", name):
		country = frappe.get_doc({"doctype": "Country", "country_name": name})
		country.name = name
		country.db_insert()


def make_region(name, rows):
	region = frappe.new_doc("Region")
	region.region_name = name
	for country, show_in_filter in rows:
		region.append("countries", {"country": country, "show_in_filter": show_in_filter})
	return region.insert(ignore_permissions=True)


def make_partner(country):
	if frappe.db.exists("Partner", PARTNER):
		partner = frappe.get_doc("Partner", PARTNER)
		partner.country = country
		return partner.save(ignore_permissions=True)

	tier = next(t for t in frappe.get_meta("Partner").get_field("tier").options.split("\n") if t)
	return frappe.get_doc(
		{"doctype": "Partner", "partner_name": PARTNER, "tier": tier, "country": country, "enabled": 1}
	).insert(ignore_permissions=True)


class TestRegion(IntegrationTestCase):
	def setUp(self):
		for country in (LISTED_COUNTRY, OTHER_COUNTRY, NO_REGION_COUNTRY):
			make_country(country)
		if not frappe.db.exists("Region", REGION):
			make_region(REGION, [(LISTED_COUNTRY, 1), (OTHER_COUNTRY, 0)])

	def test_partner_gets_the_region_of_its_country(self):
		partner = make_partner(OTHER_COUNTRY)
		self.assertEqual(partner.region, REGION)

		partner.country = NO_REGION_COUNTRY
		partner.save(ignore_permissions=True)
		self.assertIsNone(partner.region)

	def test_editing_a_region_updates_its_partners(self):
		partner = make_partner(NO_REGION_COUNTRY)
		region = frappe.get_doc("Region", REGION)

		region.append("countries", {"country": NO_REGION_COUNTRY})
		region.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Partner", partner.name, "region"), REGION)

		region.countries = [row for row in region.countries if row.country != NO_REGION_COUNTRY]
		region.save(ignore_permissions=True)
		self.assertIsNone(frappe.db.get_value("Partner", partner.name, "region"))

	def test_country_belongs_to_one_region_only(self):
		with self.assertRaises(frappe.ValidationError):
			make_region("_Test Second Region", [(LISTED_COUNTRY, 0)])

		with self.assertRaises(frappe.ValidationError):
			make_region("_Test Repeated Region", [(NO_REGION_COUNTRY, 0), (NO_REGION_COUNTRY, 1)])

	def test_filter_lists_only_marked_countries(self):
		self.assertEqual(get_filter_countries()[REGION], [LISTED_COUNTRY])
		self.assertEqual(get_region_of_country(OTHER_COUNTRY), REGION)


class TestLinkPartnerCountryPatch(IntegrationTestCase):
	def test_matches_names_codes_and_aliases(self):
		self.assertEqual(find_country(" india "), "India")
		self.assertEqual(find_country("IN"), "India")
		self.assertEqual(find_country("UAE"), "United Arab Emirates")
		self.assertIsNone(find_country("Atlantis"))

	def test_fixes_country_and_region_of_old_values(self):
		partner = make_partner("India")
		frappe.db.set_value("Partner", partner.name, {"country": "uae", "region": None})

		link_partner_country()
		self.assertEqual(
			frappe.db.get_value("Partner", partner.name, ["country", "region"]),
			("United Arab Emirates", get_region_of_country("United Arab Emirates")),
		)

	def test_stops_on_a_country_it_cannot_match(self):
		partner = make_partner("India")
		frappe.db.set_value("Partner", partner.name, "country", "Atlantis")

		with self.assertRaises(frappe.ValidationError):
			link_partner_country()
		self.assertEqual(frappe.db.get_value("Partner", partner.name, "country"), "Atlantis")
