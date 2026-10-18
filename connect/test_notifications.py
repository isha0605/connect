from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from connect.notifications import notify_thread_members


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
