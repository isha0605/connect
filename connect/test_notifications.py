from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.customer.doctype.project_quote.test_leads import make_member
from connect.notifications import notify_thread_members

PARTNER = "_Test Requirement Email Partner"
OWNER = "requirement.owner@example.test"
SALES = "requirement.sales@example.test"
BUYER = "requirement.buyer@example.test"
COMPANY = "Requirement Email Buyer Co"


def notified(message_type: str, content: str = "", file_name: str | None = None) -> dict | None:
	message = frappe._dict(
		name="MSG-1",
		thread="THREAD-1",
		sender="partner@example.com",
		message_type=message_type,
		content=content,
		file_name=file_name,
		flags=frappe._dict(),
	)
	message.as_dict = lambda: message
	with (
		patch("connect.notifications._notification_targets", return_value=["customer@example.com"]),
		patch("connect.notifications.enqueue_create_notification") as enqueue,
		patch("frappe.publish_realtime"),
	):
		notify_thread_members(message)

	return enqueue.call_args.args[1] if enqueue.called else None


def notified_subject(message_type: str, content: str = "", file_name: str | None = None) -> str | None:
	notification = notified(message_type, content, file_name)
	return notification and notification["subject"]


class UnitTestNotifications(UnitTestCase):
	def test_a_quote_message_is_left_to_the_project_notification(self):
		self.assertIsNone(notified_subject("Quote", frappe.as_json({"amount": 1700000})))

	def test_a_file_notification_names_the_file(self):
		self.assertEqual(notified_subject("File", file_name="scope.pdf"), "📎 scope.pdf")

	def test_a_text_notification_shows_the_message_without_markup(self):
		self.assertEqual(notified_subject("Text", "<p>Can we talk <b>today</b>?</p>"), "Can we talk today?")

	def test_a_message_notification_opens_the_thread_at_that_message(self):
		self.assertEqual(notified("Text", "Hello")["link"], "/messaging?thread=THREAD-1&message=MSG-1")


class TestNewRequirementEmail(IntegrationTestCase):
	"""Every requirement a customer sends is emailed to the partner's owners and the lead's assignee."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		make_partner(PARTNER)
		make_partner_admin(PARTNER, OWNER)
		make_member(PARTNER, SALES)
		make_buyer(BUYER, COMPANY)
		self.enqueue = patch("connect.notifications.frappe.enqueue").start()
		self.addCleanup(patch.stopall)

	def send_requirement(self, project_name):
		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": project_name, "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		self.enqueue.reset_mock()
		return send_brief(project, COMPANY, PARTNER)

	def emailed(self):
		return [
			call.kwargs["admin"]
			for call in self.enqueue.call_args_list
			if call.args == ("connect.notifications._send_new_requirement_email",)
		]

	def test_a_second_requirement_in_the_same_thread_is_emailed(self):
		thread = self.send_requirement("Stock and expiry")
		self.assertEqual(self.emailed(), [OWNER])

		self.assertEqual(self.send_requirement("Payroll"), thread)
		self.assertEqual(self.emailed(), [OWNER])

	def test_whoever_has_the_lead_is_emailed_too(self):
		thread = self.send_requirement("Stock and expiry")
		frappe.db.set_value("Partner Lead", {"thread": thread}, "assigned_to", SALES)

		self.send_requirement("Payroll")
		self.assertEqual(self.emailed(), [OWNER, SALES])

	def test_a_starter_pack_card_is_not_emailed(self):
		thread = self.send_requirement("Stock and expiry")
		self.enqueue.reset_mock()
		message = frappe.get_doc(
			{"doctype": "Connect Message", "thread": thread, "sender": BUYER, "message_type": "Requirement", "content": "{}"}
		)
		message.flags.from_starter_pack = True
		message.insert(ignore_permissions=True)
		self.assertEqual(self.emailed(), [])

	def test_a_card_from_the_partner_side_is_not_emailed(self):
		thread = self.send_requirement("Stock and expiry")
		self.enqueue.reset_mock()
		frappe.get_doc(
			{"doctype": "Connect Message", "thread": thread, "sender": SALES, "message_type": "Requirement", "content": "{}"}
		).insert(ignore_permissions=True)
		self.assertEqual(self.emailed(), [])
