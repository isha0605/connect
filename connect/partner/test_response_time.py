# Copyright (c) 2026
# See license.txt

from datetime import datetime

from frappe.tests import UnitTestCase

from connect.partner.response_time import aggregate_samples, get_business_minutes, get_replies

WEEKDAYS_NINE_TO_SIX = {
	"work_start": "09:00",
	"work_end": "18:00",
	"work_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
}


def at(day: int, hour: int, minute: int = 0) -> datetime:
	"""A time in the week of Monday 12 October 2026."""
	return datetime(2026, 10, day, hour, minute)


class TestBusinessMinutes(UnitTestCase):
	def test_counts_time_inside_working_hours(self):
		self.assertEqual(get_business_minutes(at(12, 10), at(12, 11, 30), WEEKDAYS_NINE_TO_SIX), 90)

	def test_skips_the_night(self):
		# 17:00 Monday to 10:00 Tuesday: one hour each side of the night
		self.assertEqual(get_business_minutes(at(12, 17), at(13, 10), WEEKDAYS_NINE_TO_SIX), 120)

	def test_skips_the_weekend(self):
		# 17:00 Friday to 10:00 Monday
		self.assertEqual(get_business_minutes(at(16, 17), at(19, 10), WEEKDAYS_NINE_TO_SIX), 120)

	def test_message_after_hours_starts_counting_next_morning(self):
		self.assertEqual(get_business_minutes(at(12, 23), at(13, 9, 30), WEEKDAYS_NINE_TO_SIX), 30)

	def test_reply_outside_working_hours_counts_nothing(self):
		self.assertEqual(get_business_minutes(at(12, 19), at(12, 23), WEEKDAYS_NINE_TO_SIX), 0)


class TestReplies(UnitTestCase):
	def test_partner_reply_after_customer_message(self):
		turns = [("Customer", "customer@x.com", at(12, 10)), ("Partner", "partner@x.com", at(12, 11))]
		self.assertEqual(get_replies(turns), [(at(12, 10), "partner@x.com", at(12, 11))])

	def test_clock_starts_at_the_customers_last_message(self):
		turns = [
			("Customer", "customer@x.com", at(12, 10)),
			("Customer", "customer@x.com", at(12, 15)),
			("Partner", "partner@x.com", at(12, 16)),
		]
		self.assertEqual(get_replies(turns), [(at(12, 15), "partner@x.com", at(12, 16))])

	def test_only_the_first_reply_counts(self):
		turns = [
			("Customer", "customer@x.com", at(12, 10)),
			("Partner", "partner@x.com", at(12, 11)),
			("Partner", "partner@x.com", at(12, 12)),
		]
		self.assertEqual(len(get_replies(turns)), 1)

	def test_partner_message_without_a_question_is_not_a_reply(self):
		self.assertEqual(get_replies([("Partner", "partner@x.com", at(12, 10))]), [])

	def test_sender_without_a_side_is_skipped(self):
		turns = [
			("Customer", "customer@x.com", at(12, 10)),
			(None, "former@x.com", at(12, 10, 30)),
			("Partner", "partner@x.com", at(12, 11)),
		]
		self.assertEqual(get_replies(turns), [(at(12, 10), "partner@x.com", at(12, 11))])


class TestAggregateSamples(UnitTestCase):
	def test_needs_enough_samples(self):
		self.assertIsNone(aggregate_samples([60, 120]))

	def test_median_in_whole_hours(self):
		self.assertEqual(aggregate_samples([60, 240, 600]), 4)

	def test_fast_replies_show_as_one_hour(self):
		self.assertEqual(aggregate_samples([1, 2, 3]), 1)
