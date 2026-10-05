import frappe
from frappe.utils import flt


def _get_press_client():
	"""Returns a FrappeClient connected to Frappe Cloud using Press Settings credentials."""
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
	"""Fetches the partner's current MRR from Frappe Cloud so the application shows live numbers, not stale ones."""
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
	"""Refreshes MRR from Press onto the partner's active application draft so their eligibility is up to date."""
	if not frappe.db.get_single_value("Press Settings", "enabled"):
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
		doc.save()


def sync_all_partner_mrrs():
	"""Nightly job that keeps every draft application's MRR fresh without waiting for a user to open the page."""
	if not frappe.db.get_single_value("Press Settings", "enabled"):
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
