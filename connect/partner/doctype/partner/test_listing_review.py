# Copyright (c) 2026
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from connect.customer.doctype.customer_project.test_hiring import make_partner_admin
from connect.partner import daily_review
from connect.partner.doctype.partner.listing_review import (
	PARTNER_FIELDS,
	review_listing,
	review_partner_listings,
)
from connect.partner.doctype.partner_tier.tier_review import TierLadder

PARTNER = "_Test Listing Partner"
APPLYING = "_Test Listing Applying Partner"
ADMIN = "listing.admin@example.test"


class TestListingReview(IntegrationTestCase):
	"""The directory shows an approved partner with the certificates its tier needs."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		make_listing_partner(PARTNER, "Verified")
		make_partner_admin(PARTNER, ADMIN)

	def review(self, apply_changes=True, **values):
		if values:
			frappe.db.set_value("Partner", PARTNER, values)
		row = frappe.get_all("Partner", filters={"name": PARTNER}, fields=PARTNER_FIELDS)[0]
		review_listing(TierLadder(), row, apply_changes)
		fields = ["show_in_website", "listing_review", "listed_on"]
		return frappe.db.get_value("Partner", PARTNER, fields, as_dict=True)

	def test_a_partner_with_the_certificates_its_tier_needs_is_listed(self):
		partner = self.review(certs_erpnext=2)

		self.assertEqual((partner.show_in_website, partner.listing_review), (1, "Show"))
		self.assertEqual(partner.listed_on, getdate(today()))
		self.assertIn("now in the Frappe partner directory", listing_emails()[0].message)

	def test_a_beginner_needs_entrys_certificates_to_be_listed(self):
		self.assertEqual(self.review(tier="Beginner", certs_erpnext=1).show_in_website, 0)
		self.assertEqual(self.review(tier="Beginner", certs_erpnext=2).show_in_website, 1)

	def test_a_partner_short_for_over_90_days_is_hidden(self):
		long_ago = add_days(today(), -91)

		partner = self.review(tier="Silver", certs_erpnext=2, show_in_website=1, listed_on=long_ago)

		self.assertEqual((partner.show_in_website, partner.listing_review), (0, "Hide"))
		message = listing_emails()[0].message
		self.assertIn("taken off the Frappe partner directory", message)
		self.assertIn("needs 3", message)

	def test_a_partner_short_within_90_days_stays_listed(self):
		recently = add_days(today(), -10)

		partner = self.review(tier="Silver", certs_erpnext=2, show_in_website=1, listed_on=recently)

		self.assertEqual((partner.show_in_website, partner.listing_review), (1, "Show"))
		self.assertFalse(listing_emails())

	def test_a_kept_listing_is_not_changed(self):
		partner = self.review(certs_erpnext=2, keep_listing=1, keep_listing_reason="Hidden after a complaint")

		self.assertEqual((partner.show_in_website, partner.listing_review), (0, "Show"))
		self.assertFalse(listing_emails())

	def test_keeping_a_listing_needs_a_reason(self):
		doc = frappe.get_doc("Partner", PARTNER)
		doc.keep_listing = 1

		with self.assertRaises(frappe.MandatoryError):
			doc.save()

	def test_with_changes_off_only_the_review_is_saved(self):
		partner = self.review(apply_changes=False, certs_erpnext=2)

		self.assertEqual((partner.show_in_website, partner.listing_review), (0, "Show"))
		self.assertFalse(listing_emails())

	def test_only_approved_partners_are_reviewed(self):
		make_listing_partner(APPLYING, "Pending Review")

		review_partner_listings()

		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "listing_review"), "Hide")
		self.assertFalse(frappe.db.get_value("Partner", APPLYING, "listing_review"))

	@patch.object(daily_review, "review_partner_listings")
	@patch.object(daily_review, "review_partner_tiers")
	@patch.object(daily_review, "update_all_partner_revenue")
	def test_the_daily_review_runs_revenue_then_tiers_then_listing(self, revenue, tiers, listings):
		order = []
		for step in (revenue, tiers, listings):
			step.side_effect = lambda step=step: order.append(step)

		daily_review.run_daily_review()

		self.assertEqual(order, [revenue, tiers, listings])


def make_listing_partner(partner_name, verification_status):
	"""An Entry partner off the directory, with no certificates."""
	frappe.delete_doc("Partner", partner_name, force=True, ignore_missing=True)
	frappe.get_doc(
		{"doctype": "Partner", "partner_name": partner_name, "tier": "Entry", "country": "India"}
	).insert()
	frappe.db.set_value("Partner", partner_name, "verification_status", verification_status)


def listing_emails():
	filters = {"reference_doctype": "Partner", "reference_name": PARTNER}
	return frappe.get_all("Email Queue", filters=filters, fields=["name", "message"])
