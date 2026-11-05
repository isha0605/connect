# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.customer.doctype.project_quote.leads import add_lead_note, get_lead, log_lead_follow_up, update_lead
from connect.customer.doctype.project_quote.test_leads import make_member
from connect.partner.doctype.partner_customer.customers import get_customer, my_customers, update_customer

PARTNER = "_Test Records Partner"
OTHER_PARTNER = "_Test Records Other Partner"
OWNER = "records.owner@example.test"
SALES = "records.sales@example.test"
FINANCE = "records.finance@example.test"
MEMBER = "records.member@example.test"
OTHER_OWNER = "records.other.owner@example.test"
BUYER = "records.buyer@example.test"
COMPANY = "Records Buyer Co"


class TestPartnerCustomer(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		# The new-requirement email job runs at once in tests and commits; these tests check data, not mail.
		patch("connect.notifications.frappe.enqueue").start()
		self.addCleanup(patch.stopall)
		for partner, owner in ((PARTNER, OWNER), (OTHER_PARTNER, OTHER_OWNER)):
			make_partner(partner)
			make_partner_admin(partner, owner)
		make_member(PARTNER, SALES)
		make_member(PARTNER, FINANCE, "Finance")
		make_member(PARTNER, MEMBER, "Member")
		make_buyer(BUYER, COMPANY)

		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Dealer billing", "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		send_brief(project, COMPANY, PARTNER)
		self.quote, self.lead = frappe.db.get_value("Project Quote", {"customer_project": project.name}, ["name", "lead"])

	def as_user(self, user):
		frappe.set_user(user)

	def hire(self):
		quote = frappe.get_doc("Project Quote", self.quote)
		quote.status = "Hired"
		# Frappe skips Version history in tests by default; Activity reads it.
		quote.save(ignore_permissions=True, ignore_version=False)
		return frappe.db.get_value("Partner Customer", {"partner": PARTNER, "customer": COMPANY}, "name")

	def test_accepting_the_hire_wins_the_lead_and_adds_a_customer_who_wants_to_link(self):
		customer = self.hire()
		self.assertEqual(frappe.db.get_value("Partner Customer", customer, "stage"), "Wants to link")

		self.as_user(OWNER)
		lead = get_lead(self.lead)["lead"]
		self.assertEqual(lead["stage"], "Won")
		self.assertIn("converted the lead to a deal", [entry.get("text") for entry in lead["activity"]])
		self.assertIn(customer, [row["name"] for row in my_customers()["customers"]])

	def test_hiring_again_keeps_the_one_customer(self):
		first = self.hire()
		from connect.partner.doctype.partner_customer.partner_customer import add_won_customer

		self.assertEqual(add_won_customer(frappe.get_doc("Project Quote", self.quote)), first)

	def test_notes_and_follow_ups_follow_the_customer_from_lead_to_customer(self):
		self.as_user(OWNER)
		add_lead_note(self.lead, "Wants a Tally import")
		log_lead_follow_up(self.lead, {"followed_up_on": "2026-11-01 10:00:00", "mode": "Call", "spoke_to": "Meera"})
		update_lead(self.lead, probability="Hot")

		lead = get_lead(self.lead)["lead"]
		self.assertEqual([note["text"] for note in lead["notes"]], ["Wants a Tally import"])
		texts = [entry.get("text") or entry.get("field") for entry in lead["activity"]]
		self.assertIn("logged a call with Meera", texts)
		self.assertIn("Probability", texts)

		self.as_user("Administrator")
		customer = self.hire()
		self.as_user(OWNER)
		record = get_customer(customer)["customer"]
		self.assertEqual([note["text"] for note in record["notes"]], ["Wants a Tally import"])
		self.assertEqual(len(record["follow_ups"]), 1)

	def test_only_the_partners_team_reads_its_customers(self):
		customer = self.hire()
		self.as_user(OTHER_OWNER)
		self.assertRaises(frappe.DoesNotExistError, get_customer, customer)
		self.assertRaises(frappe.DoesNotExistError, add_lead_note, self.lead, "Peeking")
		self.as_user(BUYER)
		self.assertRaises(frappe.PermissionError, my_customers)

	def test_sales_sees_and_works_every_team_customer(self):
		customer = self.hire()
		self.as_user(SALES)
		update_customer(customer, stage="Onboarding")
		self.assertEqual(update_customer(customer, stage="Live")["stage"], "Live")

	# ---- Linking: Wants to link until the team approves, then Onboarding ----

	def test_a_customer_who_wants_to_link_has_no_sites_and_pays_themselves(self):
		customer = self.hire()
		self.as_user(OWNER)
		record = get_customer(customer)["customer"]
		self.assertEqual((record["sites"], record["mrr"], record["billing_by"]), ([], 0, "Customer"))
		self.assertIsNone(record["linked_on"])

	def test_approving_the_link_moves_to_onboarding_with_sites(self):
		customer = self.hire()
		self.as_user(OWNER)
		update_customer(customer, stage="Onboarding")

		record = get_customer(customer)["customer"]
		self.assertEqual(record["stage"], "Onboarding")
		self.assertIsNotNone(record["linked_on"])
		self.assertTrue(record["sites"])
		self.assertEqual(record["mrr"], sum(site["amount"] for site in record["sites"]))
		self.assertTrue(record["is_demo"])

	def test_the_link_is_approved_into_onboarding_only(self):
		customer = self.hire()
		self.as_user(OWNER)
		self.assertRaises(frappe.ValidationError, update_customer, customer, stage="Live")

	def test_a_linked_customer_cannot_go_back_to_wanting_to_link(self):
		customer = self.hire()
		self.as_user(OWNER)
		update_customer(customer, stage="Onboarding")
		self.assertRaises(frappe.ValidationError, update_customer, customer, stage="Wants to link")

	def test_a_member_or_another_partner_cannot_approve_the_link(self):
		customer = self.hire()
		for user in (MEMBER, OTHER_OWNER):
			self.as_user(user)
			with self.assertRaises((frappe.PermissionError, frappe.DoesNotExistError)):
				update_customer(customer, stage="Onboarding")
		self.assertEqual(frappe.db.get_value("Partner Customer", customer, "stage"), "Wants to link")

	# ---- Access levels: Finance sees customers; a Member doesn't ----

	def test_finance_sees_every_team_customer(self):
		customer = self.hire()
		self.as_user(FINANCE)
		self.assertIn(customer, [row["name"] for row in my_customers()["customers"]])

	def test_a_member_cannot_open_customers_or_be_given_one(self):
		customer = self.hire()
		self.as_user(MEMBER)
		self.assertRaises(frappe.PermissionError, my_customers)
		self.as_user(OWNER)
		self.assertRaises(frappe.ValidationError, update_customer, customer, assigned_to=MEMBER)
