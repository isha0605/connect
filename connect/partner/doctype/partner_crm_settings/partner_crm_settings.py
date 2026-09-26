# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PartnerCRMSettings(Document):
	pass


def _my_partner_as_admin():
	"""The partner this user administers. CRM credentials are partner-wide and drive lead sync
	for every thread the partner owns, so only a partner admin may see or change them --
	the same rule permissions.has_partner_crm_settings_permission enforces on the doctype."""
	from connect.permissions import _my_company_membership

	doctype, partner, row = _my_company_membership(frappe.session.user)
	if doctype != "Connect Partner Member" or not row or not row.get("is_admin"):
		frappe.throw(_("Only a partner admin can manage CRM settings"), frappe.PermissionError)
	return partner


def get_my_settings():
	"""Never returns api_secret. The form shows whether one is stored and lets it be replaced,
	so the credential is never sent to the browser."""
	partner = _my_partner_as_admin()
	name = frappe.db.get_value("Partner CRM Settings", {"partner": partner})
	if not name:
		return {
			"partner": partner,
			"configured": 0,
			"enabled": 0,
			"crm_type": "Frappe CRM",
			"site_url": "",
			"api_key": "",
			"default_lead_status": "",
			"api_secret_set": 0,
			"reply_webhook_connected": 0,
		}

	doc = frappe.get_doc("Partner CRM Settings", name)
	return {
		"partner": partner,
		"configured": 1,
		"enabled": int(doc.enabled or 0),
		"crm_type": doc.crm_type,
		"site_url": doc.site_url or "",
		"api_key": doc.api_key or "",
		"default_lead_status": doc.default_lead_status or "",
		"api_secret_set": 1 if doc.get_password("api_secret", raise_exception=False) else 0,
		# written by crm_integration.sync_reply_webhook once the remote Webhook is registered
		"reply_webhook_connected": 1 if doc.crm_reply_webhook_id else 0,
	}


def save_my_settings(site_url, api_key, default_lead_status, api_secret=None, enabled=0):
	"""Create or update this partner's CRM credentials.

	`api_secret` is write-only: blank means "keep what is stored", so changing the site URL
	doesn't require re-entering the secret. The Connect Partner role has read and write but
	no `create`, so the first save is done with ignore_permissions -- the partner-admin check
	above is what authorises it."""
	partner = _my_partner_as_admin()

	site_url = (site_url or "").strip().rstrip("/")
	api_key = (api_key or "").strip()
	default_lead_status = (default_lead_status or "").strip()
	api_secret = (api_secret or "").strip()
	enabled = int(enabled or 0)

	if not site_url or not api_key or not default_lead_status:
		frappe.throw(_("Site URL, API key and default lead status are all required"))
	if not site_url.startswith(("http://", "https://")):
		frappe.throw(_("Site URL must start with http:// or https://"))

	name = frappe.db.get_value("Partner CRM Settings", {"partner": partner})
	if name:
		doc = frappe.get_doc("Partner CRM Settings", name)
	else:
		if not api_secret:
			frappe.throw(_("An API secret is required to connect a CRM"))
		doc = frappe.new_doc("Partner CRM Settings")
		doc.partner = partner
		doc.crm_type = "Frappe CRM"

	doc.site_url = site_url
	doc.api_key = api_key
	doc.default_lead_status = default_lead_status
	doc.enabled = enabled
	if api_secret:
		doc.api_secret = api_secret

	doc.save(ignore_permissions=True)
	return get_my_settings()


def disconnect_my_crm():
	"""Turns sync off without discarding the credentials, so it can be switched back on.

	The remote Webhook is deliberately left registered -- see
	crm_integration.sync_reply_webhook: with nothing syncing, no lead ever matches it."""
	partner = _my_partner_as_admin()
	name = frappe.db.get_value("Partner CRM Settings", {"partner": partner})
	if name:
		frappe.db.set_value("Partner CRM Settings", name, "enabled", 0)
	return get_my_settings()
