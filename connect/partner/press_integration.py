from collections import defaultdict
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate, now_datetime

# Frappe Cloud and frappe.io both convert partner revenue between rupees and dollars at this fixed
# rate. Connect uses the same, so all three show a partner the same number.
USD_TO_INR = 83
# Until this day, last month's invoices still being drawn up (drafts) count too, as frappe.io counts
# them: Frappe Cloud finalises a month's invoices in the first two weeks.
LAST_DAY_FOR_DRAFTS = 15
INVOICE_PAGE_SIZE = 500
INVOICE_FIELDS = ["partner_email", "due_date", "docstatus", "currency", "total_before_discount"]
FINALISED = 1


def _get_press_client():
	"""Returns a FrappeClient connected to Frappe Cloud using the Press credentials in Integration Settings."""
	from frappe.frappeclient import FrappeClient

	settings = frappe.get_cached_doc("Integration Settings")
	if not settings.press_enabled or not (
		settings.press_site_url and settings.press_api_key and settings.press_api_secret
	):
		frappe.throw(frappe._("Press integration isn't configured yet. Contact an administrator."))

	return FrappeClient(
		settings.press_site_url,
		api_key=settings.press_api_key,
		api_secret=settings.get_password("press_api_secret"),
	)


def is_press_enabled() -> bool:
	return bool(frappe.db.get_single_value("Integration Settings", "press_enabled"))


def update_all_partner_revenue() -> None:
	"""Daily: refreshes every partner's revenue. When Frappe Cloud can't be read, the saved numbers
	stay, so a Frappe Cloud outage never looks like a partner earning nothing."""
	if not is_press_enabled():
		return

	try:
		update_partner_revenue()
	except Exception:
		frappe.log_error(title="Could not read partner revenue from Frappe Cloud")


def update_partner_revenue(partners: list[str] | None = None) -> None:
	"""Saves each partner's revenue for last month and this month so far, from the Frappe Cloud
	invoices of the customers linked to it. Frappe Cloud marks those invoices with the partner's email,
	so a partner with no email is skipped; its Revenue Updated On stays empty."""
	filters = {"email": ["is", "set"], "currency": ["is", "set"]}
	if partners is not None:
		filters["name"] = ["in", partners or [""]]
	rows = frappe.get_all("Partner", filters=filters, fields=["name", "email", "currency"])
	if not rows:
		return

	# The daily run reads every partner's invoices at once; a single refresh reads only its own.
	emails = [row.email for row in rows] if partners is not None else None
	invoices_by_email = defaultdict(list)
	for invoice in _fetch_partner_invoices(emails):
		invoices_by_email[invoice["partner_email"].lower()].append(invoice)

	updated_on = now_datetime()
	for row in rows:
		last_month, this_month = get_revenue(invoices_by_email[row.email.lower()], row.currency)
		# Revenue is Frappe-side data: it is written for the partner, whatever the caller may edit.
		frappe.db.set_value(
			"Partner",
			row.name,
			{"revenue_last_month": last_month, "revenue_this_month": this_month, "revenue_updated_on": updated_on},
			update_modified=False,
		)


def _fetch_partner_invoices(emails: list[str] | None = None) -> list[dict]:
	"""Last month's and this month's subscription invoices of the customers linked to these partner
	emails, or to any partner, read a page at a time."""
	client = _get_press_client()
	filters = [
		["partner_email", "in", emails] if emails is not None else ["partner_email", "is", "set"],
		["type", "=", "Subscription"],
		["docstatus", "<", 2],
		["due_date", "between", [get_first_day(add_months(getdate(), -1)), get_last_day(getdate())]],
	]
	invoices, start = [], 0
	while True:
		page = client.get_list(
			"Invoice",
			fields=INVOICE_FIELDS,
			filters=filters,
			limit_start=start,
			limit_page_length=INVOICE_PAGE_SIZE,
			order_by="name asc",
		)
		invoices.extend(page)
		if len(page) < INVOICE_PAGE_SIZE:
			return invoices
		start += INVOICE_PAGE_SIZE


def get_revenue(invoices: list[dict], currency: str, on: date | None = None) -> tuple[float, float]:
	"""Last month's and this month's revenue in `currency`, counted as frappe.io's tier script counts
	it: last month every finalised invoice, paid or not (drafts too until the 15th), this month every
	invoice so far."""
	on = getdate(on)
	this_month_start = get_first_day(on)
	drafts_count = on.day <= LAST_DAY_FOR_DRAFTS
	last_month = this_month = 0.0

	for invoice in invoices:
		amount = _convert(flt(invoice["total_before_discount"]), invoice["currency"], currency)
		if getdate(invoice["due_date"]) >= this_month_start:
			this_month += amount
		elif invoice["docstatus"] == FINALISED or drafts_count:
			last_month += amount

	return flt(last_month, 2), flt(this_month, 2)


def _convert(amount: float, from_currency: str, to_currency: str) -> float:
	if from_currency == to_currency:
		return amount
	if to_currency == "INR":
		return amount * USD_TO_INR
	return amount / USD_TO_INR


def update_revenue_now(partner: str) -> None:
	"""Refreshes one partner's revenue, for staff in Desk and for a partner opening its application."""
	if not is_press_enabled():
		frappe.throw(_("The Frappe Cloud integration is turned off in Integration Settings."))
	if not frappe.db.get_value("Partner", partner, "email"):
		frappe.throw(_("Add the partner's Frappe Cloud partner email first. Revenue is found by it."))
	update_partner_revenue([partner])
