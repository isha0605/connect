import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.messaging.doctype.connect_feedback.connect_feedback import MAX_MESSAGE_LENGTH, submit_feedback

PARTNER = "_Test Feedback Partner"
ADMIN = "feedback.admin@example.test"
BUYER = "feedback.buyer@example.test"


class IntegrationTestConnectFeedback(IntegrationTestCase):
	"""Give feedback, from the sidebar's company menu."""

	def setUp(self):
		make_partner(PARTNER)
		make_partner_admin(PARTNER, ADMIN)
		make_buyer(BUYER, "_Test Feedback Buyer Co")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_feedback_keeps_who_sent_it_their_company_and_page(self):
		frappe.set_user(ADMIN)
		name = submit_feedback("  The leads list should sort by date.  ", "/leads")

		frappe.set_user("Administrator")
		saved = frappe.db.get_value("Connect Feedback", name, ["user", "partner", "customer", "page", "message", "status"], as_dict=True)
		self.assertEqual(
			saved,
			{"user": ADMIN, "partner": PARTNER, "customer": None, "page": "/leads",
				"message": "The leads list should sort by date.", "status": "New"},
		)

	def test_a_customer_feedback_names_their_company(self):
		frappe.set_user(BUYER)
		name = submit_feedback("Show partners' prices earlier.", "/home")
		self.assertEqual(frappe.db.get_value("Connect Feedback", name, ["partner", "customer"]), (None, "_Test Feedback Buyer Co"))

	def test_empty_or_long_feedback_and_guests_are_refused(self):
		frappe.set_user(ADMIN)
		for message in ("   ", "x" * (MAX_MESSAGE_LENGTH + 1)):
			with self.subTest(length=len(message)), self.assertRaises(frappe.ValidationError):
				submit_feedback(message)

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			submit_feedback("Hello")
