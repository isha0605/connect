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
		make_buyer(BUYER, COMPANY)

		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Dealer billing", "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		send_brief(project, COMPANY, PARTNER)
		self.lead = frappe.db.get_value("Project Quote", {"customer_project": project.name}, "name")

	def as_user(self, user):
		frappe.set_user(user)

	def hire(self):
		quote = frappe.get_doc("Project Quote", self.lead)
		quote.status = "Hired"
		# Frappe skips Version history in tests by default; Activity reads it.
		quote.save(ignore_permissions=True, ignore_version=False)
		return frappe.db.get_value("Partner Customer", {"partner": PARTNER, "customer": COMPANY}, "name")

	def test_accepting_the_hire_wins_the_lead_and_adds_an_onboarding_customer(self):
		customer = self.hire()
		self.assertEqual(frappe.db.get_value("Partner Customer", customer, "stage"), "Onboarding")

		self.as_user(OWNER)
		lead = get_lead(self.lead)["lead"]
		self.assertEqual(lead["stage"], "Won")
		self.assertIn("converted the lead to a deal", [entry.get("text") for entry in lead["activity"]])
		self.assertIn(customer, [row["name"] for row in my_customers()["customers"]])

	def test_hiring_again_keeps_the_one_customer(self):
		first = self.hire()
		from connect.partner.doctype.partner_customer.partner_customer import add_won_customer

		self.assertEqual(add_won_customer(frappe.get_doc("Project Quote", self.lead)), first)

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

	def test_a_member_sees_a_customer_once_it_is_assigned_to_them(self):
		customer = self.hire()
		self.as_user(SALES)
		self.assertRaises(frappe.DoesNotExistError, get_customer, customer)

		self.as_user(OWNER)
		update_customer(customer, assigned_to=SALES, stage="Live")
		self.as_user(SALES)
		self.assertEqual(get_customer(customer)["customer"]["stage"], "Live")
