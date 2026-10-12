import mimetypes
import re

import frappe
import requests
from bs4 import BeautifulSoup
from frappe import _
from frappe.integrations.utils import make_get_request
from frappe.utils.password import get_decrypted_password

from connect.permissions import _get_partner_admin

# Seconds to wait on the partner's CRM before giving up on a request.
CRM_REQUEST_TIMEOUT = 30

# Matches a mail client's own "On <date>, <person> wrote:" line introducing quoted history,
# for clients that inline it as plain text rather than wrapping it in a recognizable element.
_QUOTE_HEADER_RE = re.compile(r"^\s*On .{0,120}wrote:\s*$", re.IGNORECASE | re.MULTILINE)

# Elements various mail clients use to wrap quoted history below a reply.
_QUOTE_SELECTORS = ["blockquote", ".gmail_quote", ".gmail_attr", ".yahoo_quoted", ".moz-cite-prefix"]


def record_crm_reply(
	partner: str,
	communication: str,
	reference_doctype: str | None,
	reference_name: str | None,
	sent_or_received: str | None,
	content: str | None,
) -> None:
	"""Posts a partner's CRM reply into its Connect thread.

	The text goes in now; attachments follow from a background job, because the CRM's
	webhook gives up after a few seconds and would retry a delivery that already landed.
	"""
	if reference_doctype != "CRM Lead" or sent_or_received != "Sent":
		return

	thread = frappe.db.get_value("Connect Thread", {"partner": partner, "crm_lead_id": reference_name}, "name")
	if not thread:
		return

	if frappe.db.exists("Connect Message", {"crm_source_communication": communication}):
		return  # already synced — the partner's CRM retried this webhook delivery

	admin = _get_partner_admin(partner)
	if not admin:
		frappe.log_error(
			title=f"CRM reply dropped: Partner {partner} has no admin",
			message=f"Communication {communication} for Connect Thread {thread} had no one to post as.",
		)
		return

	reply_text = extract_reply_text(content or "")
	if reply_text:
		_insert_reply_message(thread, admin, communication, "Text", reply_text)

	frappe.enqueue(
		sync_reply_attachments,
		queue="long",
		job_id=f"crm-reply-attachments::{communication}",
		deduplicate=True,
		enqueue_after_commit=True,
		partner=partner,
		thread=thread,
		admin=admin,
		communication=communication,
	)


def sync_reply_attachments(partner: str, thread: str, admin: str, communication: str) -> None:
	"""Copies the files on a CRM reply into the thread, and names any that couldn't be copied."""
	if frappe.db.exists(
		"Connect Message", {"crm_source_communication": communication, "message_type": ["in", ["File", "System"]]}
	):
		return  # a redelivered reply whose files were already handled

	try:
		attachments, failed_files = _fetch_crm_attachments(partner, communication)
	except Exception:
		# A reachable-but-failing CRM (revoked key, File API denied) leaves the text reply standing.
		frappe.log_error(title=f"CRM attachment fetch failed for Communication {communication}")
		return

	for attachment in attachments:
		_insert_reply_message(thread, admin, communication, "File", attachment["file_name"], attachment=attachment)

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
		# Plain text: the thread shows System lines as text, which escapes them itself.
		names = ", ".join(f or _("(unnamed)") for f in failed_files)
		_insert_reply_message(thread, admin, communication, "System", f"{label}: {names}", silent=True)


def extract_reply_text(html_content: str) -> str:
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


def _insert_reply_message(thread, admin, communication, message_type, content, attachment=None, silent=False):
	message = frappe.get_doc({
		"doctype": "Connect Message",
		"thread": thread,
		"sender": admin,
		"message_type": message_type,
		"content": content,
		"crm_source_communication": communication,
	})
	if attachment:
		message.attachment = attachment["file_url"]
		message.file_name = attachment["file_name"]
		message.file_type = attachment["file_type"]
		message.file_size = attachment["file_size"]
	message.flags.skip_crm_sync = True
	message.flags.silent = silent
	# the webhook is a guest request; its signature, not the session, proves who is posting
	message.insert(ignore_permissions=True)


def _fetch_crm_attachments(partner, communication):
	"""Downloads files the partner attached in their CRM so they show up as real attachments in Connect, not just filenames."""
	settings = frappe.db.get_value("Partner CRM Settings", partner, ["site_url", "api_key"], as_dict=True)
	if not settings:
		return [], []

	api_secret = get_decrypted_password("Partner CRM Settings", partner, "api_secret")
	headers = {"Authorization": f"token {settings.api_key}:{api_secret}"}
	base_url = settings.site_url.rstrip("/")

	files = make_get_request(
		f"{base_url}/api/resource/File",
		headers=headers,
		params={
			"filters": frappe.as_json(
				[["attached_to_doctype", "=", "Communication"], ["attached_to_name", "=", communication]]
			),
			"fields": frappe.as_json(["file_name", "file_url", "file_size"]),
			"limit_page_length": 500,
		},
		timeout=CRM_REQUEST_TIMEOUT,
	)["data"]

	attachments = []
	failed_files = []
	for f in files:
		try:
			attachments.append(_download_crm_file(base_url, headers, f))
		except Exception:
			frappe.log_error(title=f"CRM attachment download failed for Communication {communication}")
			failed_files.append(f["file_name"])

	return attachments, failed_files


def _download_crm_file(base_url, headers, crm_file):
	response = requests.get(f"{base_url}{crm_file['file_url']}", headers=headers, timeout=CRM_REQUEST_TIMEOUT)
	response.raise_for_status()

	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": crm_file["file_name"],
		"content": response.content,
		"is_private": 1,
	})
	# attached to its Connect Message once that is inserted, which then governs who can read it
	file_doc.insert(ignore_permissions=True)
	return {
		"file_name": crm_file["file_name"],
		"file_url": file_doc.file_url,
		"file_size": file_doc.file_size,
		"file_type": mimetypes.guess_type(crm_file["file_name"])[0],
	}
