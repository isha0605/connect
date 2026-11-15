"""Partners, kept up to date on Frappe's CRM for the sales team.

Each approved partner is one CRM Partner on Frappe's CRM, with its tier, so the sales team sees the
same partner Connect does. This takes over from frappe.io's "Create or Update Partner on
crm.frappe.io" script, so nothing is sent until tier and listing changes are turned on.
"""

import json
from urllib.parse import quote

import frappe
from frappe.utils.synchronization import filelock

from connect.crm_enquiries import frappe_crm
from connect.crm_integration import crm_request
from connect.partner.doctype.partner.partner import VERIFIED
from connect.partner.doctype.partner_tier.tier_review import BEGINNER, ENTRY, is_applying_changes

CRM_PARTNER = "CRM Partner"
# The Partner fields the CRM shows. A change to any other field isn't sent.
SENT_FIELDS = ("tier", "enabled", "verification_status", "email", "partner_name", "country")


def queue_partner_sync(doc) -> None:
	"""on_update on Partner: sends the partner to Frappe's CRM in the background when something the
	CRM shows changed."""
	settings = frappe_crm()
	if not (settings and is_applying_changes() and is_sent(doc, settings)):
		return
	if any(doc.has_value_changed(fieldname) for fieldname in SENT_FIELDS):
		_queue(doc.name)


def is_sent(partner, settings) -> bool:
	"""An approved partner, or one already on the CRM, so it hears when the partner is turned off.
	Frappe itself is left out: it is a partner in Connect only to deliver Starter Packs."""
	if partner.name == settings.partner:
		return False
	return partner.verification_status == VERIFIED or bool(partner.frappe_crm_partner)


def _queue(partner: str) -> None:
	frappe.db.set_value("Partner", partner, "frappe_crm_sync_status", "Queued", update_modified=False)
	frappe.enqueue(
		"connect.crm_partners.sync_partner",
		queue="short",
		# Without this, the worker can run before the change is saved, and miss it.
		enqueue_after_commit=True,
		partner=partner,
	)


def sync_partner(partner: str) -> None:
	"""Background job: finds or makes the partner's CRM Partner, then writes Connect's values to it.
	One job per partner runs at a time, so two saves together can't make two CRM Partners."""
	settings = frappe_crm()
	if not (settings and is_applying_changes()):
		return
	with filelock(f"connect_crm_partner_sync_{partner}", timeout=120):
		_sync_partner(partner, settings)


def _sync_partner(partner: str, settings) -> None:
	doc = frappe.get_doc("Partner", partner)
	try:
		crm_partner = doc.frappe_crm_partner or _find_crm_partner(settings, doc.email)
		if crm_partner:
			path = f"/api/resource/{quote(CRM_PARTNER)}/{quote(crm_partner)}"
			crm_request(settings, "PUT", path, json=partner_payload(doc))
		else:
			body = {"name": doc.partner_name, **partner_payload(doc)}
			response = crm_request(settings, "POST", f"/api/resource/{quote(CRM_PARTNER)}", json=body)
			crm_partner = response.json()["data"]["name"]
	except Exception:
		if doc.frappe_crm_sync_status != "Failed":
			frappe.log_error(title=f"Frappe CRM sync failed for Partner {partner}")
		frappe.db.set_value(
			"Partner",
			partner,
			{"frappe_crm_sync_status": "Failed", "frappe_crm_sync_error": frappe.get_traceback()[:2000]},
			update_modified=False,
		)
		return

	frappe.db.set_value(
		"Partner",
		partner,
		{"frappe_crm_partner": crm_partner, "frappe_crm_sync_status": "Synced", "frappe_crm_sync_error": None},
		update_modified=False,
	)


def _find_crm_partner(settings, email: str | None) -> str | None:
	"""The CRM Partner frappe.io made for this partner, found by its email, so it isn't made twice."""
	if not email:
		return None
	response = crm_request(
		settings,
		"GET",
		f"/api/resource/{quote(CRM_PARTNER)}",
		params={"filters": json.dumps([["user", "=", email]]), "limit_page_length": 1},
	)
	rows = response.json()["data"]
	return rows[0]["name"] if rows else None


def partner_payload(doc) -> dict:
	"""What the CRM shows of the partner. The CRM keeps its own territory, state, parent partner and
	status: Connect has no values for them."""
	values = {
		"enabled": int(bool(doc.enabled) and doc.verification_status == VERIFIED),
		"partner_name": doc.partner_name,
		"company_name": doc.partner_name,
		# The CRM has no Beginner tier; like Entry, it is a partner with fewer than 2 certificates.
		"partner_type": ENTRY if doc.tier == BEGINNER else doc.tier,
		"country": doc.country,
	}
	if doc.email:
		values["user"] = doc.email
	return values
