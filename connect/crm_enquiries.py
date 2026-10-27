"""Contact us enquiries, sent to Frappe's CRM as Leads for the sales team.

Each enquiry becomes a Lead with no owner, for the sales team (or a CRM assignment rule) to
assign, and the visitor's message is added to it as a received email with everything they told us.
Frappe's CRM is the one set up for Frappe in Partner CRM Settings: Frappe is the Starter Pack
partner, so its chats and its enquiries land in the same place.
"""

import frappe
from frappe.utils import add_to_date, escape_html, now_datetime

from connect.crm_integration import (
	RETRY_AFTER_MINUTES,
	crm_has,
	crm_request,
	crm_settings,
	lead_source,
	text_html,
)

ENQUIRY_LEAD_SOURCE = "Connect Contact Form"

# The company sizes the CRM has too. The others (Connect's "500+") go in the email instead.
CRM_COMPANY_SIZES = ("1-10", "11-50", "51-200", "201-500")


def frappe_crm():
	"""Frappe's own CRM settings, when it has a CRM and sync is on."""
	partner = frappe.db.get_single_value("Starter Pack Settings", "implementation_partner")
	return partner and crm_settings(partner)


def queue_enquiry_sync(doc, method=None):
	"""after_insert on Enquiry: sends it to Frappe's CRM in the background, so the visitor never
	waits on the CRM."""
	if not frappe_crm():
		return
	doc.db_set("crm_sync_status", "Queued", update_modified=False)
	frappe.enqueue(
		"connect.crm_enquiries.sync_enquiry",
		queue="short",
		# Without this, the worker can run before the enquiry is saved, and not find it.
		enqueue_after_commit=True,
		enquiry=doc.name,
	)


def sync_enquiry(enquiry):
	"""Background job: makes the enquiry's Lead, then adds the visitor's message to it."""
	doc = frappe.get_doc("Enquiry", enquiry)
	settings = frappe_crm()
	if not settings or doc.crm_sync_status == "Synced":
		return

	try:
		if not doc.crm_lead_id:
			lead = crm_request(settings, "POST", "/api/resource/CRM Lead", json=lead_payload(doc, settings))
			doc.db_set("crm_lead_id", lead.json()["data"]["name"], update_modified=False)
			frappe.db.commit()  # the Lead is made: a failure below mustn't make another
		crm_request(settings, "POST", "/api/resource/Communication", json=email_payload(doc))
	except Exception:
		frappe.db.rollback()
		# Logged once, not every hour the retry meets the same broken CRM.
		if doc.crm_sync_status != "Failed":
			frappe.log_error(title=f"CRM sync failed for Enquiry {enquiry}")
		doc.db_set(
			{"crm_sync_status": "Failed", "crm_sync_error": frappe.get_traceback()[:2000]},
			update_modified=False,
		)
		return

	doc.db_set({"crm_sync_status": "Synced", "crm_sync_error": None}, update_modified=False)


def lead_payload(doc, settings):
	"""The Lead's fields. Industry and company size are fixed lists on the CRM, which refuses a
	Lead with a value it doesn't have: those not on its lists are left for the email."""
	payload = {
		"first_name": doc.first_name,
		"last_name": doc.last_name,
		"email": doc.email,
		"mobile_no": doc.phone,
		"organization": doc.company_name,
		"job_title": doc.designation,
		"no_of_employees": doc.employees if doc.employees in CRM_COMPANY_SIZES else None,
		"industry": doc.industry
		if doc.industry and crm_has(settings, "CRM Industry", doc.industry)
		else None,
		"source": lead_source(settings, ENQUIRY_LEAD_SOURCE),
		"status": settings.default_lead_status,
	}
	return {k: v for k, v in payload.items() if v}


def email_payload(doc):
	"""The visitor's message as a received email on the Lead, with every answer on the form below
	it, so nothing they told us is lost to the CRM's fixed lists."""
	details = [
		("Company", doc.company_name),
		("Role", doc.designation),
		("Company size", doc.employees),
		("Industry", doc.industry),
		("Uses now", doc.current_software),
		("State", doc.state),
		("Phone", doc.phone),
	]
	content = (
		text_html(doc.message)
		+ "<br><br>"
		+ "<br>".join(f"{escape_html(label)}: {escape_html(value)}" for label, value in details if value)
	)
	return {
		"communication_type": "Communication",
		"communication_medium": "Email",
		"sent_or_received": "Received",
		"status": "Open",
		"subject": f"Contact us: {doc.company_name or doc.first_name}",
		"sender": doc.email,
		"sender_full_name": " ".join(filter(None, [doc.first_name, doc.last_name])),
		"content": content,
		"communication_date": str(doc.creation),
		"reference_doctype": "CRM Lead",
		"reference_name": doc.crm_lead_id,
	}


def retry_enquiry_sync():
	"""Hourly: sends the enquiries a failed or missed sync left behind."""
	if not frappe_crm():
		return
	for enquiry in frappe.get_all(
		"Enquiry",
		filters={
			"crm_sync_status": ["in", ["Queued", "Failed"]],
			"creation": ["<", add_to_date(now_datetime(), minutes=-RETRY_AFTER_MINUTES)],
		},
		order_by="creation asc",
		pluck="name",
	):
		sync_enquiry(enquiry)
		frappe.db.commit()
