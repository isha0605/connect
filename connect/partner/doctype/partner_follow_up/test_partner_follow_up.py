# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from connect.customer.doctype.project_quote.leads import log_lead_follow_up
from connect.customer.doctype.project_quote import test_leads
from connect.customer.doctype.project_quote.test_leads import OTHER_OWNER, OWNER
from connect.partner.doctype.partner_follow_up.partner_follow_up import (
	_calendar_file,
)


class TestMeetingInvites(IntegrationTestCase):
	# The same partner, buyer and lead as the Leads tests. Imported as a module so those tests
	# don't run again here.
	setUp = test_leads.TestLeads.setUp
	send = test_leads.TestLeads.send

	def schedule(self, starts_at=None, link="https://meet.google.com/abc-defg-hij"):
		frappe.set_user(OWNER)
		patch("connect.partner.doctype.partner_follow_up.partner_follow_up.frappe.enqueue").start()
		values = {
			"followed_up_on": str(starts_at or add_days(now_datetime(), 1)),
			"mode": "Meeting",
			"title": "Intro call",
			"meeting_link": link,
			"duration_minutes": 30,
			"notes": "Walk through the brief",
		}
		log_lead_follow_up(self.lead, values)
		return frappe.get_last_doc("Partner Follow Up", filters={"customer": self.customer})

	def test_scheduling_posts_an_invite_card_in_the_thread(self):
		invite = self.schedule()

		self.assertEqual(invite.mode, "Meeting")
		card = frappe.get_doc("Connect Message", invite.message)
		self.assertEqual((card.thread, card.message_type, card.sender), (self.thread, "Meeting", OWNER))
		self.assertEqual(frappe.parse_json(card.content)["follow_up"], invite.name)

	def test_a_meeting_must_be_still_to_come_with_a_https_link(self):
		with self.assertRaises(frappe.ValidationError):
			self.schedule(starts_at=add_days(now_datetime(), -1))
		with self.assertRaises(frappe.ValidationError):
			self.schedule(link="meet.google.com/abc")

	def test_another_partner_cannot_schedule_on_the_lead(self):
		self.schedule()
		frappe.set_user(OTHER_OWNER)
		with self.assertRaises(frappe.DoesNotExistError):
			log_lead_follow_up(self.lead, {"meeting_link": "https://meet.google.com/x", "title": "Call"})

	def test_the_calendar_file_is_in_utc(self):
		with patch(
			"connect.starter_packs.doctype.starter_pack_order.starter_pack_order.get_system_timezone",
			return_value="Asia/Kolkata",
		):
			invite = self.schedule(starts_at="2030-01-15 15:00:00")
			calendar = _calendar_file(invite)

		self.assertIn("DTSTART:20300115T093000Z", calendar)
		self.assertIn("DTEND:20300115T100000Z", calendar)
