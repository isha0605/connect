import base64
import hashlib
import hmac

import frappe
from frappe import _

from connect.crm_integration import WEBHOOK_SECRET_HEADER, is_from_connect
from connect.crm_reply import record_crm_reply


def _verify_signature(partner):
	"""Confirms the request actually came from the partner's CRM, so nobody can forge a reply into someone else's thread."""
	if not frappe.db.exists("Partner CRM Settings", partner):
		frappe.throw(_("Unknown partner"), frappe.PermissionError)
	secret = frappe.utils.password.get_decrypted_password(
		"Partner CRM Settings", partner, "crm_reply_webhook_secret"
	)
	if not secret:
		frappe.throw(_("Reply sync isn't set up for this partner"), frappe.PermissionError)

	signature = frappe.get_request_header(WEBHOOK_SECRET_HEADER)
	expected = base64.b64encode(
		hmac.new(secret.encode("utf8"), frappe.request.get_data(), hashlib.sha256).digest()
	)
	if not signature or not hmac.compare_digest(signature.encode("utf8"), expected):
		frappe.throw(_("Invalid signature"), frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
def receive_crm_reply(
	reference_doctype=None, reference_name=None, sent_or_received=None, content=None, name=None,
	creation=None, sender=None, message_id=None,
):
	"""Called by the partner's CRM when they send a reply, so the reply also shows up in the Connect thread."""
	# Not read from the whitelisted kwargs above: the webhook sends a JSON body, and Frappe's
	# request parsing populates form_dict from that JSON alone, discarding the URL query string
	# entirely — so `?partner=...` has to be read from the raw query args instead.
	partner = frappe.local.request.args.get("partner")
	_verify_signature(partner)

	if is_from_connect(message_id):
		return  # Connect's own copy of a chat message: it is in the chat already
	record_crm_reply(partner, name, reference_doctype, reference_name, sent_or_received, content, sender)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive_crm_lead_owner(name=None, lead_owner=None):
	"""Called by the partner's CRM when a Lead is given to someone else, so the Connect lead
	follows. `partner` is read from the query string, as for replies."""
	from connect.crm_lead_owner import record_crm_lead_owner

	partner = frappe.local.request.args.get("partner")
	_verify_signature(partner)

	record_crm_lead_owner(partner, name, lead_owner)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive_crm_lead_status(name=None, status=None):
	"""Called by the partner's CRM when a Lead's status changes, so the Connect lead's stage
	follows. `partner` is read from the query string, as for replies."""
	from connect.crm_stage_sync import CRM_LEAD, record_crm_status

	partner = frappe.local.request.args.get("partner")
	_verify_signature(partner)

	record_crm_status(partner, CRM_LEAD, name, status)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive_crm_deal_status(name=None, status=None, lead=None, lost_reason=None):
	"""Called by the partner's CRM when a Deal is made from a Lead or its status changes."""
	from connect.crm_stage_sync import CRM_DEAL, record_crm_status

	partner = frappe.local.request.args.get("partner")
	_verify_signature(partner)

	record_crm_status(partner, CRM_DEAL, name, status, crm_lead=lead, lost_reason=lost_reason)
