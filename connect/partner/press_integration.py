import frappe
from frappe.utils import flt


def _get_press_client():
	"""Returns a FrappeClient connected to Frappe Cloud (Press) using credentials stored in
	Press Settings, or throws a clear error if not configured yet."""
	from frappe.frappeclient import FrappeClient

	settings = frappe.get_cached_doc("Press Settings")
	if not settings.enabled or not (settings.site_url and settings.api_key and settings.api_secret):
		frappe.throw(frappe._("Press integration isn't configured yet. Contact an administrator."))

	return FrappeClient(
		settings.site_url,
		api_key=settings.api_key,
		api_secret=settings.get_password("api_secret"),
	)


def fetch_mrr_from_press(company_email: str) -> float:
	"""Fetches the partner's current MRR from Frappe Cloud (Press) by their company email.

	Press identifies a partner team by the email of the team owner / account. The API endpoint
	`press.api.partner.get_partner_details` returns a dict that includes `billing.monthly_revenue`
	(the same value the Press dashboard shows as the partner's Frappe Cloud MRR).

	When you have the key, verify the exact field path via:
	    client.get_api("press.api.partner.get_partner_details", {"partner": company_email})
	and adjust the extraction below if the shape differs."""
	client = _get_press_client()
	try:
		result = client.get_api("press.api.partner.get_partner_details", {"partner": company_email})
	except Exception:
		frappe.log_error(title=f"Press MRR fetch failed for {company_email}")
		frappe.throw(frappe._("Could not reach Frappe Cloud right now. Please try again shortly."))

	# Press returns monthly_revenue inside a nested billing dict — adjust path if their API shape differs.
	billing = (result or {}).get("billing") or {}
	return flt(billing.get("monthly_revenue") or (result or {}).get("monthly_revenue") or 0)


def sync_partner_mrr(partner: str):
	"""Fetches the latest MRR from Press for `partner` and writes it onto their active
	Partner Application. No-ops gracefully if Press isn't configured or no application exists."""
	settings = frappe.get_cached_doc("Press Settings")
	if not settings.enabled:
		return

	from connect.partner.doctype.partner_application.partner_application import _get_partner_application

	doc = _get_partner_application(partner)
	if not doc or doc.docstatus != 0:
		return

	company_email = doc.company_email
	if not company_email:
		return

	try:
		mrr = fetch_mrr_from_press(company_email)
	except Exception:
		return

	if flt(doc.monthly_revenue) != mrr:
		doc.monthly_revenue = mrr
		doc.save(ignore_permissions=True)


def sync_all_partner_mrrs():
	"""Daily scheduled job: refreshes MRR from Press for every partner with a Draft application."""
	settings = frappe.get_cached_doc("Press Settings")
	if not settings.enabled:
		return

	partners = frappe.get_all(
		"Partner Application",
		filters={"docstatus": 0, "company_email": ["is", "set"]},
		pluck="partner",
	)
	for partner in partners:
		try:
			sync_partner_mrr(partner)
		except Exception:
			frappe.log_error(title=f"Press MRR sync failed for partner {partner}")
