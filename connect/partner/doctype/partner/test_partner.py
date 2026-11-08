# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.partner.doctype.partner.partner import (
	PRIVATE_PROFILE_FIELDS,
	VERIFIED,
	get_partner_document,
	get_partner_preview,
	list_directory_partners,
	list_partner_tiers,
	save_imported_partner,
)
from connect.partner.doctype.partner_review.partner_review import list_partner_reviews
from connect.patches.rename_partner_is_featured_to_show_in_website import execute as rename_is_featured

LISTED = "_Test Visibility Listed Partner"
PENDING = "_Test Visibility Pending Partner"
PENDING_MEMBER = "visibility.pending.member@example.test"


def make_partner(partner_name, verification_status):
	if not frappe.db.exists("Partner", partner_name):
		tier = next(t for t in frappe.get_meta("Partner").get_field("tier").options.split("\n") if t)
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


def partner_values(partner_name):
	tier = next(t for t in frappe.get_meta("Partner").get_field("tier").options.split("\n") if t)
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
