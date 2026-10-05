# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.partner.pmm_sync import comparable, match_partners, parse_page, sync_pmm_levels

URL = "https://frappe.io/partners/india/_test-pmm-partner-private-limited"


def page_html(rating, name="_Test PMM Partner Private Limited"):
	"""Just enough of a frappe.io partner page: the header name, the rating, the contact link."""
	return (
		'<section class="a"><section class="b"><div class="c"><div class="d __text_block__">India</div>'
		f'</section><div class="e"><div class="f __text_block__">{name}</div></div></section>'
		f"<p>MATURITY</p><div><svg></svg></div></a>{rating}"
		f'<a href="https://frappe.io/contact-partner/new?partner={name.replace(" ", "+")}&lead_source=x">'
	)


LEVEL_4 = '<picture><img src="https://frappe.io/files/pml-4.svg"/></picture>'
TBD = '<div class="x __text_block__">TBD</div>'


class UnitTestPMMPages(IntegrationTestCase):
	def test_reads_the_level_from_its_image(self):
		self.assertEqual(parse_page(URL, page_html(LEVEL_4)).level, 4)

	def test_tbd_means_not_rated(self):
		self.assertEqual(parse_page(URL, page_html(TBD)).level, 0)

	def test_an_unreadable_rating_is_not_a_zero(self):
		self.assertIsNone(parse_page(URL, page_html("<div>Coming soon</div>")).level)

	def test_names_come_from_the_contact_link_and_the_header(self):
		self.assertIn("_Test PMM Partner Private Limited", parse_page(URL, page_html(LEVEL_4)).names)

	def test_legal_suffixes_do_not_matter_when_matching(self):
		self.assertEqual(comparable("Tridots Tech"), comparable("Tridots Tech Private Limited"))
		self.assertEqual(comparable("Craft Interactive"), comparable("Craft Interactive Technology LLC"))

	def test_the_country_decides_between_two_pages_with_one_name(self):
		pages = [
			frappe._dict(url="u-egypt", country="egypt", names=["Go-Live Solutions"], level=4),
			frappe._dict(url="u-ksa", country="saudi arabia", names=["Golive Solutions"], level=3),
		]
		partner = frappe._dict(name="Golive Solutions", country="Saudi Arabia", pmm_listing_url=None)
		self.assertEqual(match_partners([partner], pages)["Golive Solutions"].url, "u-ksa")

	def test_a_kept_page_link_wins_over_the_name(self):
		pages = [frappe._dict(url="u-1", country="india", names=["Someone Else"], level=5)]
		partner = frappe._dict(name="Renamed Partner", country="India", pmm_listing_url="u-1")
		self.assertEqual(match_partners([partner], pages)["Renamed Partner"].url, "u-1")


class IntegrationTestPMMSync(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("Partner", "_Test PMM Partner"):
			frappe.get_doc(
				{"doctype": "Partner", "partner_name": "_Test PMM Partner", "tier": "Gold", "country": "India"}
			).insert(ignore_permissions=True)
		frappe.db.set_value("Partner", "_Test PMM Partner", {"pmm_level": 2, "pmm_listing_url": None})

	def run_sync(self, rating, dry_run=False):
		listing = f'<a href="{URL}">'
		with patch("connect.partner.pmm_sync.fetch", side_effect=lambda url: listing if url.endswith("/list") else page_html(rating)), patch(
			"connect.partner.pmm_sync.PAUSE_SECONDS", 0
		), patch("frappe.db.commit"):
			return sync_pmm_levels(dry_run=dry_run)

	def test_updates_the_level_and_keeps_the_page_link(self):
		report = self.run_sync(LEVEL_4)
		self.assertIn("_Test PMM Partner: 2 -> 4", report.updated)
		self.assertEqual(
			frappe.db.get_value("Partner", "_Test PMM Partner", ["pmm_level", "pmm_listing_url"]), (4, URL)
		)

	def test_an_unreadable_page_leaves_the_level_alone(self):
		report = self.run_sync("<div>Coming soon</div>")
		self.assertIn(URL, report.unreadable)
		self.assertEqual(frappe.db.get_value("Partner", "_Test PMM Partner", "pmm_level"), 2)

	def test_a_dry_run_changes_nothing(self):
		self.run_sync(LEVEL_4, dry_run=True)
		self.assertEqual(frappe.db.get_value("Partner", "_Test PMM Partner", "pmm_level"), 2)
