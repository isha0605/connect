# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, today

from connect.partner.doctype.partner.partner import (
	PRIVATE_PROFILE_FIELDS,
	VERIFIED,
	get_partner_document,
	get_partner_preview,
	list_directory_partners,
	list_partner_tiers,
	save_imported_partner,
	search_partners,
)
from connect.partner.doctype.partner_review.partner_review import list_partner_reviews
from connect.patches.move_partner_year_founded_to_foundation_date import execute as move_year_founded
from connect.patches.rename_partner_is_featured_to_show_in_website import execute as rename_is_featured
from connect.patches.set_partner_listed_on import execute as set_partner_listed_on
from connect.patches.set_partner_target_currency import execute as set_partner_target_currency
from connect.patches.use_press_team_size_ranges import execute as use_press_team_size_ranges

LISTED = "_Test Visibility Listed Partner"
PENDING = "_Test Visibility Pending Partner"
PENDING_MEMBER = "visibility.pending.member@example.test"


def make_partner(partner_name, verification_status):
	if not frappe.db.exists("Partner", partner_name):
		tier = "Gold"
		frappe.get_doc(
			{"doctype": "Partner", "partner_name": partner_name, "tier": tier, "country": "India", "enabled": 1}
		).insert(ignore_permissions=True)
	frappe.db.set_value(
		"Partner",
		partner_name,
		{"verification_status": verification_status, "show_in_website": 1, "profile_draft": '{"tagline": "Draft"}'},
	)


def make_member(partner, email):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Member"}).insert(ignore_permissions=True)
	if not frappe.db.exists("Connect Partner Member", {"partner": partner, "user": email}):
		frappe.get_doc({"doctype": "Connect Partner Member", "partner": partner, "user": email}).insert(
			ignore_permissions=True
		)


class IntegrationTestPartner(IntegrationTestCase):
	"""Guests see only listed partners, and only through Connect's own APIs."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		make_partner(LISTED, "Verified")
		make_partner(PENDING, "Pending Review")
		make_member(PENDING, PENDING_MEMBER)

	def test_guest_cannot_read_partner_or_review_records(self):
		frappe.set_user("Guest")

		self.assertFalse(frappe.has_permission("Partner", "read"))
		self.assertFalse(frappe.has_permission("Partner Review", "read"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("Partner")

	def test_guest_directory_lists_only_listed_partners(self):
		frappe.set_user("Guest")

		names = {row.name for row in list_directory_partners(limit=500)}

		self.assertIn(LISTED, names)
		self.assertNotIn(PENDING, names)

	def test_guest_opens_a_listed_profile_without_private_fields(self):
		frappe.set_user("Guest")

		doc = get_partner_document(LISTED)

		self.assertEqual(doc["partner_name"], LISTED)
		for fieldname in PRIVATE_PROFILE_FIELDS:
			self.assertNotIn(fieldname, doc)
		self.assertEqual(get_partner_preview(LISTED)["name"], LISTED)
		self.assertIsInstance(list_partner_reviews(LISTED), list)

	def test_guest_cannot_open_an_unlisted_profile(self):
		frappe.set_user("Guest")

		with self.assertRaises(frappe.DoesNotExistError):
			get_partner_document(PENDING)
		with self.assertRaises(frappe.DoesNotExistError):
			get_partner_preview(PENDING)

	def test_member_and_staff_can_open_an_unlisted_profile(self):
		frappe.set_user(PENDING_MEMBER)
		self.assertEqual(get_partner_document(PENDING)["partner_name"], PENDING)

		frappe.set_user("Administrator")
		self.assertEqual(get_partner_preview(PENDING)["name"], PENDING)


class IntegrationTestPartnerID(IntegrationTestCase):
	"""Partners who sign up are named by their display name. Imported partners keep their frappe.io ID,
	so only they may share a display name."""

	def setUp(self):
		frappe.set_user("Administrator")

	def test_signup_partner_is_named_by_its_trimmed_display_name(self):
		remove_partners("_Test Signup Partner")

		self.assertEqual(insert_signup_partner("  _Test Signup Partner  "), "_Test Signup Partner")

	def test_signup_partner_needs_a_display_name(self):
		for partner_name in (None, "   "):
			with self.assertRaises(frappe.MandatoryError):
				insert_signup_partner(partner_name)

	def test_signup_partner_cannot_take_a_used_name(self):
		remove_partners("_Test Taken Name", "_Test Imported Taken LLP")
		insert_signup_partner("_Test Taken Name")
		save_imported_partner("_Test Imported Taken LLP", partner_values("_Test Other"))

		for taken in ("_Test Taken Name", "_Test Imported Taken LLP"):
			with self.assertRaises(frappe.DuplicateEntryError):
				insert_signup_partner(taken)

	def test_imported_partner_keeps_its_frappe_io_id(self):
		remove_partners("_Test Apex Softnet Private Limited")

		name = save_imported_partner("_Test Apex Softnet Private Limited", partner_values("_Test Apex"))

		self.assertEqual(name, "_Test Apex Softnet Private Limited")
		self.assertEqual(frappe.db.get_value("Partner", name, "partner_name"), "_Test Apex")

	def test_importing_again_updates_the_same_partner(self):
		remove_partners("_Test Rerun Private Limited")
		save_imported_partner("_Test Rerun Private Limited", partner_values("_Test Rerun"))

		save_imported_partner("_Test Rerun Private Limited", partner_values("_Test Rerun Renamed"))

		self.assertEqual(frappe.db.count("Partner", {"name": "_Test Rerun Private Limited"}), 1)
		self.assertEqual(frappe.db.get_value("Partner", "_Test Rerun Private Limited", "partner_name"), "_Test Rerun Renamed")

	def test_imported_partners_can_share_a_display_name(self):
		remove_partners("_Test Shared Apex Softnet Private Limited", "_Test Shared Apex Enterprise LLP")

		save_imported_partner("_Test Shared Apex Softnet Private Limited", partner_values("_Test Shared Apex"))
		save_imported_partner("_Test Shared Apex Enterprise LLP", partner_values("_Test Shared Apex"))

		self.assertEqual(frappe.db.count("Partner", {"partner_name": "_Test Shared Apex"}), 2)


class IntegrationTestPartnerTier(IntegrationTestCase):
	"""Beginner is the lowest tier, below Bronze."""

	def setUp(self):
		frappe.set_user("Administrator")

	def test_beginner_comes_last_in_the_tier_filter(self):
		remove_partners("_Test Beginner Partner LLP")
		listed = {"tier": "Beginner", "enabled": 1, "show_in_website": 1, "verification_status": VERIFIED}
		save_imported_partner("_Test Beginner Partner LLP", {**partner_values("_Test Beginner"), **listed})

		tiers = list_partner_tiers()

		self.assertEqual(tiers[-1], "Beginner")
		self.assertEqual(tiers, [t for t in ("Gold", "Silver", "Bronze", "Beginner") if t in tiers])


class IntegrationTestShowInWebsitePatch(IntegrationTestCase):
	"""The rename patch moves each partner's listing switch before it drops the old column."""

	def setUp(self):
		frappe.set_user("Administrator")
		remove_partners("_Test Patch Listed LLP")
		save_imported_partner("_Test Patch Listed LLP", {**partner_values("_Test Patch Listed"), "show_in_website": 0})
		self.addCleanup(remove_test_column_and_partner)

	def test_patch_moves_the_listing_switch_and_drops_the_old_column(self):
		frappe.db.sql_ddl("alter table `tabPartner` add column `is_featured` int(1) not null default 0")
		frappe.client_cache.delete_value("table_columns::tabPartner")
		# Every partner keeps its current value, so the copy in the patch changes only the test partner.
		frappe.db.sql("update `tabPartner` set is_featured = show_in_website")
		frappe.db.sql("update `tabPartner` set is_featured = 1 where name = %s", "_Test Patch Listed LLP")

		rename_is_featured()

		self.assertEqual(frappe.db.get_value("Partner", "_Test Patch Listed LLP", "show_in_website"), 1)
		self.assertFalse(frappe.db.has_column("Partner", "is_featured"))


FOUNDED = "_Test Founded Partner LLP"


class IntegrationTestFoundationDate(IntegrationTestCase):
	"""A partner keeps the full date it was founded, and shows how many years ago that was."""

	def setUp(self):
		frappe.set_user("Administrator")
		remove_partners(FOUNDED)
		save_imported_partner(FOUNDED, partner_values("_Test Founded Partner"))
		self.addCleanup(remove_year_column_and_partner)

	def test_years_ago_comes_from_the_foundation_date(self):
		frappe.db.set_value("Partner", FOUNDED, "foundation_date", f"{getdate().year - 12}-06-30")

		self.assertEqual(get_partner_document(FOUNDED)["founded_years_ago"], 12)

	def test_patch_moves_the_year_to_a_date_and_drops_the_old_column(self):
		frappe.db.sql_ddl("alter table `tabPartner` add column `year_founded` int(11) not null default 0")
		frappe.client_cache.delete_value("table_columns::tabPartner")
		frappe.db.sql("update `tabPartner` set year_founded = 2015 where name = %s", FOUNDED)
		draft = frappe.as_json({"tagline": "Drafted", "year_founded": 2019})
		frappe.db.set_value("Partner", FOUNDED, "profile_draft", draft)

		move_year_founded()

		self.assertEqual(frappe.db.get_value("Partner", FOUNDED, "foundation_date"), getdate("2015-01-01"))
		moved_draft = frappe.parse_json(frappe.db.get_value("Partner", FOUNDED, "profile_draft"))
		self.assertEqual(moved_draft, {"tagline": "Drafted", "foundation_date": "2019-01-01"})
		self.assertFalse(frappe.db.has_column("Partner", "year_founded"))


def remove_year_column_and_partner():
	# Adding and dropping a column commits, so this test cleans up and commits by itself.
	if frappe.db.has_column("Partner", "year_founded"):
		frappe.db.sql_ddl("alter table `tabPartner` drop column `year_founded`")
		frappe.client_cache.delete_value("table_columns::tabPartner")
	remove_partners(FOUNDED)
	frappe.db.commit()  # nosemgrep: the DDL above already committed this test's rows


SERVING = "_Test Serving Partner LLP"


class IntegrationTestServedCountries(IntegrationTestCase):
	"""Countries Served is a list of countries. The count and the directory search follow the list."""

	def setUp(self):
		frappe.set_user("Administrator")
		remove_partners(SERVING)
		served = [{"country": "Kenya"}, {"country": "United Arab Emirates"}]
		save_imported_partner(SERVING, {**partner_values("_Test Serving Partner"), "served_countries": served})
		frappe.db.set_value("Partner", SERVING, {"verification_status": VERIFIED, "show_in_website": 1})
		self.addCleanup(remove_partners, SERVING)

	def test_count_follows_the_list(self):
		self.assertEqual(frappe.db.get_value("Partner", SERVING, "countries_served"), 2)

	def test_a_country_is_listed_once(self):
		partner = frappe.get_doc("Partner", SERVING)
		partner.append("served_countries", {"country": "Kenya"})
		with self.assertRaises(frappe.ValidationError):
			partner.save(ignore_permissions=True)

	def test_directory_finds_partners_by_a_served_country(self):
		self.assertIn(SERVING, [p.name for p in search_partners(served_country="Kenya")])
		self.assertNotIn(SERVING, [p.name for p in search_partners(served_country="Japan")])


INDIAN = "_Test Currency India"
KENYAN = "_Test Currency Kenya"


class IntegrationTestTierFields(IntegrationTestCase):
	"""A partner's target currency comes from its country, and its listed date from when it was listed."""

	def setUp(self):
		frappe.set_user("Administrator")
		remove_partners(INDIAN, KENYAN)
		self.addCleanup(remove_partners, INDIAN, KENYAN)

	def test_currency_follows_the_country(self):
		insert_signup_partner(INDIAN)
		frappe.get_doc({"doctype": "Partner", **partner_values(KENYAN), "country": "Kenya"}).insert()

		self.assertEqual(frappe.db.get_value("Partner", INDIAN, "currency"), "INR")
		self.assertEqual(frappe.db.get_value("Partner", KENYAN, "currency"), "USD")

	def test_a_set_currency_is_kept(self):
		frappe.get_doc({"doctype": "Partner", **partner_values(INDIAN), "currency": "USD"}).insert()

		self.assertEqual(frappe.db.get_value("Partner", INDIAN, "currency"), "USD")

	def test_listed_on_is_set_only_when_listing_turns_on(self):
		insert_signup_partner(INDIAN)
		partner = frappe.get_doc("Partner", INDIAN)
		self.assertIsNone(partner.listed_on)

		partner.show_in_website = 1
		partner.save()
		self.assertEqual(str(partner.listed_on), today())

		frappe.db.set_value("Partner", INDIAN, "listed_on", "2026-01-01")
		partner.reload()
		partner.tagline = "Still listed"
		partner.save()
		self.assertEqual(str(partner.listed_on), "2026-01-01")

	def test_imported_partner_keeps_its_listing_date(self):
		listed = {"show_in_website": 1, "listed_on": "2025-03-14"}
		save_imported_partner("_Test Listed Import LLP", {**partner_values("_Test Listed Import"), **listed})

		self.assertEqual(str(frappe.db.get_value("Partner", "_Test Listed Import LLP", "listed_on")), "2025-03-14")

	def test_one_frappe_io_page_belongs_to_one_partner(self):
		old_page = {"frappe_io_route": "partners/india/_test-old-page"}
		self.addCleanup(remove_partners, "_Test Old Page LLP", "_Test Same Page LLP", "_Test No Page LLP")
		save_imported_partner("_Test Old Page LLP", {**partner_values("_Test Old Page"), **old_page})

		with self.assertRaises(frappe.UniqueValidationError):
			save_imported_partner("_Test Same Page LLP", {**partner_values("_Test Same Page"), **old_page})

		# Partners that never had a frappe.io page don't clash with each other.
		insert_signup_partner("_Test No Page LLP")
		self.assertIsNone(frappe.db.get_value("Partner", "_Test No Page LLP", "frappe_io_route"))

	def test_currency_patch_fills_only_empty_currencies(self):
		insert_signup_partner(INDIAN)
		frappe.get_doc({"doctype": "Partner", **partner_values(KENYAN), "country": "Kenya"}).insert()
		frappe.db.set_value("Partner", INDIAN, "currency", None)
		frappe.db.set_value("Partner", KENYAN, "currency", "INR")

		set_partner_target_currency()

		self.assertEqual(frappe.db.get_value("Partner", INDIAN, "currency"), "INR")
		self.assertEqual(frappe.db.get_value("Partner", KENYAN, "currency"), "INR")

	def test_listed_on_patch_fills_only_empty_dates(self):
		insert_signup_partner(INDIAN)
		frappe.get_doc({"doctype": "Partner", **partner_values(KENYAN), "country": "Kenya"}).insert()
		frappe.db.set_value("Partner", INDIAN, {"show_in_website": 1, "listed_on": None})
		frappe.db.set_value("Partner", KENYAN, {"show_in_website": 1, "listed_on": "2026-01-01"})

		set_partner_listed_on()

		self.assertEqual(frappe.db.get_value("Partner", INDIAN, "listed_on"), getdate())
		self.assertEqual(frappe.db.get_value("Partner", KENYAN, "listed_on"), getdate("2026-01-01"))

	def test_team_size_patch_moves_only_sizes_above_200(self):
		insert_signup_partner(INDIAN)
		frappe.get_doc({"doctype": "Partner", **partner_values(KENYAN), "country": "Kenya"}).insert()
		frappe.db.set_value("Partner", INDIAN, "team_size", "500+")
		frappe.db.set_value("Partner", KENYAN, "team_size", "51-200")

		use_press_team_size_ranges()

		self.assertEqual(frappe.db.get_value("Partner", INDIAN, "team_size"), "201+")
		self.assertEqual(frappe.db.get_value("Partner", KENYAN, "team_size"), "51-200")


def partner_values(partner_name):
	tier = "Gold"
	return {"partner_name": partner_name, "tier": tier, "country": "India"}


def insert_signup_partner(partner_name):
	doc = frappe.get_doc({"doctype": "Partner", **partner_values(partner_name)})
	return doc.insert(ignore_permissions=True).name


def remove_partners(*names):
	for name in names:
		frappe.delete_doc("Partner", name, force=True, ignore_missing=True)


def remove_test_column_and_partner():
	# Adding and dropping a column commits, so this test cleans up and commits by itself.
	if frappe.db.has_column("Partner", "is_featured"):
		frappe.db.sql_ddl("alter table `tabPartner` drop column `is_featured`")
		frappe.client_cache.delete_value("table_columns::tabPartner")
	remove_partners("_Test Patch Listed LLP")
	frappe.db.commit()  # nosemgrep: the DDL above already committed this test's rows
