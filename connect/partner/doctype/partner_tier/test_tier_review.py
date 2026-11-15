# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, now_datetime, today

from connect.customer.doctype.customer_project.test_hiring import make_partner_admin
from connect.partner.doctype.partner_tier.tier_review import (
	PARTNER_FIELDS,
	TierLadder,
	get_earned_tier,
	review_partner,
	review_partner_tiers,
)

PARTNER = "_Test Tier Review Partner"
APPLYING = "_Test Tier Review Applying Partner"
ADMIN = "tier.review.admin@example.test"


class TestEarnedTier(IntegrationTestCase):
	"""The tier a partner earns follows frappe.io's rules."""

	def earned(self, current, revenue, certificates, pmm, currency="INR"):
		return get_earned_tier(TierLadder(), current, revenue, currency, certificates, pmm)

	def test_the_lower_of_the_revenue_and_certificate_tiers(self):
		self.assertEqual(self.earned("Silver", 630000, 2, 5), "Bronze")

	def test_usd_partners_are_measured_against_usd_targets(self):
		self.assertEqual(self.earned("Entry", 3150, 3, 4, currency="USD"), "Silver")

	def test_pmm_holds_back_a_move_up_past_emerging(self):
		self.assertEqual(self.earned("Emerging", 630000, 4, 2), "Emerging")
		self.assertEqual(self.earned("Entry", 630000, 4, 2), "Emerging")

	def test_pmm_never_moves_a_partner_down(self):
		self.assertEqual(self.earned("Gold", 630000, 4, 0), "Gold")

	def test_a_partner_at_entry_or_above_never_drops_to_beginner(self):
		self.assertEqual(self.earned("Emerging", 0, 0, 0), "Entry")

	def test_a_beginner_moves_up_to_entry_at_two_certificates(self):
		self.assertEqual(self.earned("Beginner", 0, 2, 0), "Entry")
		self.assertEqual(self.earned("Beginner", 0, 1, 0), "Beginner")

	def test_unknown_revenue_never_moves_a_partner_down(self):
		self.assertEqual(self.earned("Silver", None, 0, 0), "Silver")
		self.assertEqual(self.earned("Beginner", None, 4, 5), "Entry")


class TestTierReview(IntegrationTestCase):
	"""The review saves the earned tier, and moves the partner there only when tier changes are on."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		make_reviewed_partner(PARTNER, "Verified")
		make_partner_admin(PARTNER, ADMIN)

	def review(self, apply_changes):
		row = frappe.get_all("Partner", filters={"name": PARTNER}, fields=PARTNER_FIELDS)[0]
		review_partner(TierLadder(), row, apply_changes)
		return frappe.db.get_value("Partner", PARTNER, ["tier", "reviewed_tier", "previous_tier"], as_dict=True)

	def test_with_changes_off_only_the_reviewed_tier_is_saved(self):
		partner = self.review(apply_changes=False)

		self.assertEqual((partner.tier, partner.reviewed_tier), ("Silver", "Entry"))
		self.assertFalse(tier_emails())

	def test_with_changes_on_the_tier_moves_and_the_admins_hear(self):
		partner = self.review(apply_changes=True)

		self.assertEqual((partner.tier, partner.previous_tier), ("Entry", "Silver"))
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "tier_changed_on"), getdate(today()))
		emails = tier_emails()
		self.assertEqual(len(emails), 1)
		self.assertIn("changed to Entry", emails[0].message)
		self.assertIn(ADMIN, frappe.get_all("Email Queue Recipient", {"parent": emails[0].name}, pluck="recipient"))

	def test_a_kept_tier_is_not_changed(self):
		frappe.db.set_value("Partner", PARTNER, {"keep_tier": 1, "keep_tier_reason": "Legacy contract"})

		partner = self.review(apply_changes=True)

		self.assertEqual((partner.tier, partner.reviewed_tier), ("Silver", "Entry"))
		self.assertFalse(tier_emails())

	def test_keeping_a_tier_needs_a_reason(self):
		doc = frappe.get_doc("Partner", PARTNER)
		doc.keep_tier = 1

		with self.assertRaises(frappe.MandatoryError):
			doc.save()

	def test_revenue_not_read_today_never_moves_a_partner_down(self):
		frappe.db.set_value("Partner", PARTNER, "revenue_updated_on", add_days(now_datetime(), -1))

		partner = self.review(apply_changes=True)

		self.assertEqual((partner.tier, partner.reviewed_tier), ("Silver", "Silver"))

	def test_only_approved_partners_are_reviewed(self):
		make_reviewed_partner(APPLYING, "Pending Review")

		review_partner_tiers()

		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "reviewed_tier"), "Entry")
		self.assertIsNone(frappe.db.get_value("Partner", APPLYING, "reviewed_tier"))


def make_reviewed_partner(partner_name, verification_status):
	"""A Silver partner whose revenue was read today and came to nothing, with no certificates."""
	frappe.delete_doc("Partner", partner_name, force=True, ignore_missing=True)
	frappe.get_doc(
		{"doctype": "Partner", "partner_name": partner_name, "tier": "Silver", "country": "India"}
	).insert()
	frappe.db.set_value(
		"Partner",
		partner_name,
		{
			"verification_status": verification_status,
			"revenue_last_month": 0,
			"revenue_this_month": 0,
			"revenue_updated_on": now_datetime(),
		},
	)


def tier_emails():
	filters = {"reference_doctype": "Partner", "reference_name": PARTNER}
	return frappe.get_all("Email Queue", filters=filters, fields=["name", "message"])
