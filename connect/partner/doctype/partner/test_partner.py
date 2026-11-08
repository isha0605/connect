# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.partner.doctype.partner.partner import (
	PRIVATE_PROFILE_FIELDS,
	get_partner_document,
	get_partner_preview,
	list_directory_partners,
)
from connect.partner.doctype.partner_review.partner_review import list_partner_reviews

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
		{"verification_status": verification_status, "is_featured": 1, "profile_draft": '{"tagline": "Draft"}'},
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
