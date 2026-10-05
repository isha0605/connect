import base64
import hashlib
import hmac
import html
import re

import frappe
from bs4 import BeautifulSoup
from frappe import _

from connect.crm_integration import WEBHOOK_SECRET_HEADER
from connect.permissions import _get_partner_admin


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
	creation=None,
):
	"""Called by the partner's CRM when they send a reply, so the reply also shows up in the Connect thread."""
	# Not read from the whitelisted kwargs above: the webhook sends a JSON body, and Frappe's
	# request parsing populates form_dict from that JSON alone, discarding the URL query string
	# entirely — so `?partner=...` has to be read from the raw query args instead.
	partner = frappe.local.request.args.get("partner")
	_verify_signature(partner)

	if reference_doctype != "CRM Lead" or sent_or_received != "Sent":
		return

	thread = frappe.db.get_value(
		"Connect Thread", {"partner": partner, "crm_lead_id": reference_name}, "name"
	)
	if not thread:
		return

	if frappe.db.exists("Connect Message", {"crm_source_communication": name, "message_type": ["!=", "System"]}):
		return  # already synced — the partner's CRM retried this webhook delivery

	settings = frappe.db.get_value(
		"Partner CRM Settings", partner, ["site_url", "api_key"], as_dict=True
	)
	try:
		attachments, failed_files = _fetch_crm_attachments(partner, settings, name) if settings else ([], [])
	except Exception:
		# A reachable-but-failing CRM (revoked key, File API denied) must not cost the partner their
		# text reply as well: throwing here would 500 the webhook, so the CRM retries the whole
		# delivery and — if the failure is permanent — reply sync stops dead instead of degrading.
		frappe.log_error(title=f"CRM attachment fetch failed for Communication {name}")
		attachments, failed_files = [], []

	reply_text = extract_reply_text(content or "")
	if not reply_text and not attachments and not failed_files:
		return  # an empty reply with no attachment — nothing worth showing in Connect

	admin = _get_partner_admin(partner)
	if not admin:
		return

	if reply_text:
		_insert_reply_message(thread, admin, name, "Text", reply_text)
	for attachment in attachments:
		_insert_reply_message(thread, admin, name, "File", attachment["file_name"], attachment=attachment)

	if failed_files:
		# A System line rather than silence: a reply that reads "here's the file" otherwise lands with
		# nothing attached, and the customer has no way to tell an empty-handed partner from a lost
		# file. Silent, because the only person who can re-send is the partner, and they are the
		# sender — so a notification would reach the one party who can't act on it.
		label = (
			_("Attachment couldn't be delivered")
			if len(failed_files) == 1
			else _("Attachments couldn't be delivered")
		)
		safe_names = ", ".join(html.escape(f or "(unnamed)") for f in failed_files)
		_insert_reply_message(
			thread, admin, name, "System", f"{label}: {safe_names}", silent=True
		)


def _insert_reply_message(
	thread, admin, communication_name, message_type, content, attachment=None, silent=False
):
	message = frappe.get_doc({
		"doctype": "Connect Message",
		"thread": thread,
		"sender": admin,
		"message_type": message_type,
		"content": content,
		"crm_source_communication": communication_name,
	})
	if attachment:
		message.attachment = attachment["file_url"]
		message.file_name = attachment["file_name"]
		message.file_type = attachment["file_type"]
		message.file_size = attachment["file_size"]
	message.flags.skip_crm_sync = True
	message.flags.silent = silent
	message.insert(ignore_permissions=True)


def _fetch_crm_attachments(partner, settings, communication_name):
	"""Downloads files the partner attached in their CRM so they show up as real attachments in Connect, not just filenames."""
	import mimetypes

	import requests
	from frappe.integrations.utils import make_get_request
	from frappe.utils.password import get_decrypted_password

	api_secret = get_decrypted_password("Partner CRM Settings", partner, "api_secret")
	headers = {"Authorization": f"token {settings.api_key}:{api_secret}"}
	base_url = settings.site_url.rstrip("/")

	files = make_get_request(
		f"{base_url}/api/resource/File",
		headers=headers,
		params={
			"filters": frappe.as_json(
				[["attached_to_doctype", "=", "Communication"], ["attached_to_name", "=", communication_name]]
			),
			"fields": frappe.as_json(["file_name", "file_url", "file_size"]),
			"limit_page_length": 500,
		},
	)["data"]

	attachments = []
	failed_files = []
	for f in files:
		try:
			response = requests.get(f"{base_url}{f['file_url']}", headers=headers)
			response.raise_for_status()

			file_doc = frappe.get_doc({
				"doctype": "File",
				"file_name": f["file_name"],
				"content": response.content,
				"is_private": 1,
			})
			file_doc.insert(ignore_permissions=True)
			attachments.append({
				"file_name": f["file_name"],
				"file_url": file_doc.file_url,
				"file_size": file_doc.file_size,
				"file_type": mimetypes.guess_type(f["file_name"])[0],
			})
		except Exception:
			frappe.log_error(title=f"CRM attachment download failed for Communication {communication_name}")
			failed_files.append(f["file_name"])

	return attachments, failed_files


# Matches a mail client's own "On <date>, <person> wrote:" line introducing quoted history,
# for clients that inline it as plain text rather than wrapping it in a recognizable element.
_QUOTE_HEADER_RE = re.compile(r"^\s*On .{0,120}wrote:\s*$", re.IGNORECASE | re.MULTILINE)

# Elements various mail clients use to wrap quoted history below a reply.
_QUOTE_SELECTORS = ["blockquote", ".gmail_quote", ".gmail_attr", ".yahoo_quoted", ".moz-cite-prefix"]


def extract_reply_text(html_content):
	"""Returns only the partner's new reply text, so replies don't re-post the whole quoted thread as a new message."""
	if not html_content:
		return ""

	soup = BeautifulSoup(html_content, "html.parser")

	# The compose editor marks where a reply's body ends and the user's configured signature
	# begins with an empty `<p class="signature">` boundary element — drop it and everything
	# after it (the signature itself is one or more sibling elements following that marker).
	signature_marker = soup.find(class_="signature")
	if signature_marker:
		for sibling in list(signature_marker.find_next_siblings()):
			sibling.decompose()
		signature_marker.decompose()

	for selector in _QUOTE_SELECTORS:
		for tag in soup.select(selector):
			tag.decompose()

	text = soup.get_text("\n")
	match = _QUOTE_HEADER_RE.search(text)
	if match:
		text = text[: match.start()]

	lines = [line.strip() for line in text.splitlines()]
	text = "\n".join(line for line in lines if line)
	return text.strip()
