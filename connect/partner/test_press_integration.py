# Copyright (c) 2026
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, get_last_day, getdate

from connect.partner import press_integration
from connect.partner.press_integration import get_revenue, update_all_partner_revenue, update_partner_revenue

INDIAN = "_Test Revenue India"
KENYAN = "_Test Revenue Kenya"
NO_EMAIL = "_Test Revenue No Email"
LAST_MONTH_END = "2026-10-31"
THIS_MONTH_END = "2026-11-30"


def invoice(email, due_date, status, amount, currency="USD"):
	"""A Frappe Cloud invoice: paid and unpaid ones are finalised, drafts are not."""
	return {
		"partner_email": email,
		"due_date": due_date,
		"docstatus": 0 if status == "Draft" else 1,
		"currency": currency,
		"total_before_discount": amount,
	}


class TestRevenueRules(IntegrationTestCase):
	"""Revenue is counted as frappe.io's tier script counts it."""

	invoices = [
		invoice("p@example.test", LAST_MONTH_END, "Paid", 100),
		invoice("p@example.test", LAST_MONTH_END, "Unpaid", 50),
		invoice("p@example.test", LAST_MONTH_END, "Draft", 20),
		invoice("p@example.test", THIS_MONTH_END, "Draft", 30),
	]

	def test_drafts_count_for_last_month_until_the_15th(self):
		self.assertEqual(get_revenue(self.invoices, "USD", on="2026-11-15"), (170, 30))

	def test_after_the_15th_every_finalised_invoice_counts_paid_or_not(self):
		self.assertEqual(get_revenue(self.invoices, "USD", on="2026-11-16"), (150, 30))

	def test_amounts_are_converted_to_the_partner_currency(self):
		dollars = [invoice("p@example.test", THIS_MONTH_END, "Paid", 10)]
		rupees = [invoice("p@example.test", THIS_MONTH_END, "Paid", 830, currency="INR")]

		self.assertEqual(get_revenue(dollars, "INR", on="2026-11-20"), (0, 830))
		self.assertEqual(get_revenue(rupees, "USD", on="2026-11-20"), (0, 10))


class TestUpdatePartnerRevenue(IntegrationTestCase):
	"""Each partner gets the revenue of the invoices that carry its email."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		make_partner(INDIAN, "India", "india@example.test")
		make_partner(KENYAN, "Kenya", "kenya@example.test")
		make_partner(NO_EMAIL, "India", None)
		last_month_end = get_last_day(add_months(getdate(), -1))
		self.invoices = [
			invoice("INDIA@example.test", last_month_end, "Paid", 10),
			invoice("kenya@example.test", last_month_end, "Paid", 830, currency="INR"),
			invoice("kenya@example.test", get_last_day(getdate()), "Draft", 5),
		]

	def test_each_partner_gets_its_own_revenue(self):
		with fake_press(self.invoices):
			update_partner_revenue()

		self.assertEqual(revenue_of(INDIAN), (830, 0))
		self.assertEqual(revenue_of(KENYAN), (10, 5))
		self.assertIsNotNone(frappe.db.get_value("Partner", INDIAN, "revenue_updated_on"))

	def test_a_partner_without_an_email_is_skipped(self):
		with fake_press(self.invoices):
			update_partner_revenue()

		self.assertIsNone(frappe.db.get_value("Partner", NO_EMAIL, "revenue_updated_on"))

	def test_invoices_are_read_a_page_at_a_time(self):
		with patch.object(press_integration, "INVOICE_PAGE_SIZE", 2), fake_press(self.invoices) as get_client:
			update_partner_revenue()

		self.assertEqual(get_client.return_value.get_list.call_count, 2)
		self.assertEqual(revenue_of(KENYAN), (10, 5))

	def test_saved_revenue_stays_when_frappe_cloud_cannot_be_read(self):
		frappe.db.set_value("Partner", INDIAN, "revenue_last_month", 500)
		failing = MagicMock()
		failing.get_list.side_effect = ConnectionError("Frappe Cloud is down")

		with (
			patch.object(press_integration, "is_press_enabled", return_value=True),
			patch.object(press_integration, "get_press_client", return_value=failing),
		):
			update_all_partner_revenue()

		self.assertEqual(revenue_of(INDIAN), (500, 0))


def make_partner(company_name, country, email):
	frappe.delete_doc("Partner", company_name, force=True, ignore_missing=True)
	frappe.get_doc(
		{
			"doctype": "Partner",
			"company_name": company_name,
			"tier": "Gold",
			"country": country,
			"email": email,
		}
	).insert()


def revenue_of(partner):
	return tuple(frappe.db.get_value("Partner", partner, ["revenue_last_month", "revenue_this_month"]))


def fake_press(invoices):
	"""A Frappe Cloud that returns `invoices` a page at a time."""
	client = MagicMock()
	client.get_list.side_effect = lambda *args, limit_start=0, limit_page_length=None, **kwargs: invoices[
		limit_start : limit_start + limit_page_length
	]
	return patch.object(press_integration, "get_press_client", return_value=client)
