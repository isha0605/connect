from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_partner

PARTNER = "_Test Notified Partner"
BUYER = "notified.buyer@example.test"


class TestProjectNotifications(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.enqueue = patch(
			"connect.customer.doctype.customer_project.project_notifications.enqueue_create_notification"
		).start()
		self.addCleanup(patch.stopall)
		make_partner(PARTNER)
		if not frappe.db.exists("User", BUYER):
			frappe.get_doc({"doctype": "User", "email": BUYER, "first_name": "Buyer"}).insert(
				ignore_permissions=True
			)

		frappe.set_user(BUYER)
		self.project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Warehouse rollout", "verdict": "Custom"}
		).insert(ignore_permissions=True)
		frappe.set_user("Administrator")

	def subjects(self):
		return [call.args[1]["subject"] for call in self.enqueue.call_args_list]

	def make_quote(self, status="Awaiting"):
		return frappe.get_doc(
			{
				"doctype": "Project Quote",
				"customer_project": self.project.name,
				"partner": PARTNER,
				"status": status,
				"amount": 450000,
				"timeline_weeks": 6,
			}
		).insert(ignore_permissions=True)

	def test_a_new_project_tells_its_owner_and_links_to_its_page(self):
		users, notification = self.enqueue.call_args.args
		self.assertEqual(users, [BUYER])
		self.assertEqual(notification["subject"], "Project created")
		self.assertEqual(notification["link"], f"/custom-implementation?project={self.project.name}")

	def test_sharing_is_announced_only_the_first_time(self):
		self.project.update({"status": "Shared", "shared_count": 3})
		self.project.save(ignore_permissions=True)
		self.project.update({"status": "Hiring", "partner": PARTNER})
		self.project.save(ignore_permissions=True)
		# A declined hire puts the project back to Shared; that isn't a new share.
		self.project.update({"status": "Shared", "partner": None})
		self.project.save(ignore_permissions=True)

		self.assertEqual(
			self.subjects(),
			["Project created", "Requirements sent to 3 partners", f"Hire request sent to {PARTNER}"],
		)

	def test_a_saved_project_without_a_new_status_stays_quiet(self):
		self.project.project_name = "Warehouse and retail rollout"
		self.project.save(ignore_permissions=True)
		self.assertEqual(self.subjects(), ["Project created"])

	def test_a_new_quote_tells_the_customer_the_amount(self):
		quote = self.make_quote()
		quote.status = "Quoted"
		quote.save(ignore_permissions=True)

		notification = self.enqueue.call_args.args[1]
		self.assertEqual(notification["subject"], f"New quote from {PARTNER}")
		self.assertEqual(notification["email_content"], "Warehouse rollout · ₹4,50,000 · 6 weeks")

	def test_a_declined_hire_tells_the_customer_why(self):
		quote = self.make_quote(status="Hire Requested")
		quote.update({"status": "Hire Declined", "decline_reason": "We're fully booked until March."})
		quote.save(ignore_permissions=True)

		notification = self.enqueue.call_args.args[1]
		self.assertEqual(notification["subject"], f"{PARTNER} declined your hire request")
		self.assertEqual(notification["email_content"], "We're fully booked until March.")
