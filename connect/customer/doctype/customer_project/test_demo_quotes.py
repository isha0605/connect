# Copyright (c) 2026, Isha and contributors
# See license.txt

from frappe.tests import UnitTestCase

from connect.customer.doctype.customer_project.demo_quotes import quote_range
from connect.partner.press_integration import USD_TO_INR


class UnitTestDemoQuotes(UnitTestCase):
	"""Demo quotes fall within the customer's budget, in the partner's own currency."""

	def test_a_budget_in_the_quotes_currency_is_used_as_it_is(self):
		self.assertEqual(quote_range("$6k to $18k", "USD"), (7000, 17000))
		self.assertEqual(quote_range("₹5 to 15 lakh", "INR"), (600000, 1400000))

	def test_a_budget_in_the_other_currency_is_converted(self):
		self.assertEqual(quote_range("$6k to $18k", "INR"), (7000 * USD_TO_INR, 17000 * USD_TO_INR))
		self.assertEqual(quote_range("₹5 to 15 lakh", "USD"), (600000 / USD_TO_INR, 1400000 / USD_TO_INR))

	def test_no_budget_counts_as_not_decided(self):
		self.assertEqual(quote_range(None, "INR"), quote_range("Not decided yet", "INR"))
