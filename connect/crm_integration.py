"""A partner's Connect chats, kept in their CRM.

Each thread is a CRM Lead owned by the thread's consultant, and each message an email on it: the
customer's as received, the partner side's as sent. Replies sent from the CRM come back into the
thread through a Webhook on the CRM (see connect.crm_reply).
"""

from urllib.parse import quote

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, escape_html, now_datetime
from frappe.utils.password import get_decrypted_password, set_encrypted_password
from frappe.utils.synchronization import filelock

WEBHOOK_SECRET_HEADER = "X-Frappe-Webhook-Signature"

# Seconds to wait on the partner's CRM before giving up on a request.
CRM_REQUEST_TIMEOUT = 30

# Connect's own notes in a thread ("Rahul is now looking after this project") aren't anyone's
# email, so they stay out of the CRM.
SKIPPED_MESSAGE_TYPES = ("System",)

# Marks the messages of threads that had a Lead before Connect noted which messages it sent, so
# they aren't sent again.
SENT_BEFORE_TRACKING = "sent before tracking"

# The hourly retry leaves messages this recent to the job queued when they were sent.
RETRY_AFTER_MINUTES = 10

# A Lead's Source on the CRM, so the sales team can tell Connect's leads apart. Starter Pack
# chats are the ones with a Frappe consultant.
STARTER_PACK_LEAD_SOURCE = "Connect Starter Pack"
CHAT_LEAD_SOURCE = "Connect Chat"

# How long Connect remembers that a CRM has a source, before checking again.
LEAD_SOURCE_CACHE_SECONDS = 24 * 60 * 60

# A Communication's fields the reply webhook sends to Connect.
REPLY_WEBHOOK_FIELDS = [
	"name",
	"reference_doctype",
	"reference_name",
	"sent_or_received",
	"content",
	"creation",
	"sender",
]


class CRMRequestError(Exception):
	def __init__(self, status_code, message):
		super().__init__(message)
		self.status_code = status_code


def crm_settings(partner):
	"""The partner's CRM settings when sync is on, else None."""
	return frappe.db.get_value(
		"Partner CRM Settings",
		{"partner": partner, "enabled": 1},
		["name", "partner", "crm_type", "site_url", "api_key", "default_lead_status"],
		as_dict=True,
	)


def crm_request(settings, method, path, **kwargs):
	"""One call to the partner's CRM as their API user. A refusal raises with the CRM's own answer,
	so the thread's sync error says why."""
	api_secret = get_decrypted_password("Partner CRM Settings", settings.name, "api_secret")
	response = requests.request(
		method,
		settings.site_url.rstrip("/") + path,
		headers={"Authorization": f"token {settings.api_key}:{api_secret}"},
		timeout=CRM_REQUEST_TIMEOUT,
		**kwargs,
	)
	if not response.ok:
		raise CRMRequestError(
			response.status_code, f"{method} {path}: {response.status_code} {response.text[:500]}"
		)
	return response


def crm_has(settings, doctype, name):
	"""Whether the CRM has this record, such as an Industry from its fixed list."""
	try:
		crm_request(settings, "GET", f"/api/resource/{doctype}/{quote(name)}")
	except CRMRequestError as e:
		if e.status_code == 404:
			return False
		raise
	return True


def lead_source(settings, source):
	"""The source for a new Lead, added to the CRM the first time it's missing. None when it can't
	be added (the API user isn't allowed to): the Lead is sent without one, never not at all."""
	# Remembered either way, so a CRM that won't take the source is asked (and logged) once a day,
	# not on every Lead.
	key = f"connect_crm_lead_source::{settings.name}::{source}"
	known = frappe.cache.get_value(key)
	if known is not None:
		return source if known else None
	try:
		if not crm_has(settings, "CRM Lead Source", source):
			crm_request(settings, "POST", "/api/resource/CRM Lead Source", json={"source_name": source})
		known = 1
	except Exception:
		frappe.log_error(title=f"Couldn't add the lead source {source} on {settings.name}'s CRM")
		known = 0
	frappe.cache.set_value(key, known, expires_in_sec=LEAD_SOURCE_CACHE_SECONDS)
	return source if known else None


def text_html(text):
	"""Plain text as an email's HTML, keeping its line breaks."""
	return "<br>".join(escape_html(line) for line in (text or "").splitlines())


def unsynced_message_filters():
	"""The messages still to be sent: not sent yet, not a reply that came from the CRM, not a note."""
	return {
		"crm_communication": ["is", "not set"],
		"crm_source_communication": ["is", "not set"],
		"message_type": ["not in", SKIPPED_MESSAGE_TYPES],
	}


def queue_crm_lead_sync(doc, method=None):
	"""after_insert on Connect Message: sends it to the partner's CRM in the background, so the
	customer never waits on the CRM."""
	if doc.flags.get("skip_crm_sync") or doc.message_type in SKIPPED_MESSAGE_TYPES:
		return  # a reply synced in from the CRM is there already

	thread = frappe.db.get_value(
		"Connect Thread", doc.thread, ["name", "partner", "crm_lead_id"], as_dict=True
	)
	if not thread or not crm_settings(thread.partner):
		return

	if not thread.crm_lead_id:
		frappe.db.set_value("Connect Thread", thread.name, "crm_sync_status", "Queued", update_modified=False)
	queue_thread_sync(thread.name)


def queue_thread_sync(thread):
	frappe.enqueue(
		"connect.crm_integration.sync_thread",
		queue="short",
		thread=thread,
		# Without this, the worker can run before this request commits, and miss the message.
		enqueue_after_commit=True,
	)


def sync_thread(thread):
	"""Background job: makes the thread's Lead if it has none, then sends every message not on
	the CRM yet, oldest first. One job per thread runs at a time, so two messages sent together
	can't make two Leads or send one email twice."""
	with filelock(f"connect_crm_sync_{thread}", timeout=120):
		_sync_thread(thread)


def _sync_thread(thread):
	thread_doc = frappe.get_doc("Connect Thread", thread)
	settings = crm_settings(thread_doc.partner)
	if not settings:
		return

	messages = frappe.get_all(
		"Connect Message",
		filters={"thread": thread, **unsynced_message_filters()},
		fields=["name", "sender", "message_type", "content", "attachment", "file_name", "creation"],
		order_by="creation asc",
	)
	if not messages:
		# Nothing to send, and a chat with nothing in it gets no Lead. A status left from
		# before (a message deleted since it was queued) mustn't keep the hourly retry coming.
		if thread_doc.crm_sync_status in ("Queued", "Failed"):
			thread_doc.db_set(
				"crm_sync_status", "Synced" if thread_doc.crm_lead_id else "", update_modified=False
			)
		return

	note = ""
	try:
		if settings.crm_type != "Frappe CRM":
			frappe.throw(_("Unsupported CRM type: {0}").format(settings.crm_type))

		customer = _customer_contact(thread_doc)
		if not thread_doc.crm_lead_id:
			lead, owner = _create_lead(thread_doc, settings, customer)
			thread_doc.db_set("crm_lead_id", lead, update_modified=False)
			frappe.db.commit()  # the Lead is made: a failure below mustn't make another
			if thread_doc.consultant and not owner:
				note = _("The Lead has no owner: {0} has no user on the CRM.").format(thread_doc.consultant)

		partner_side = _partner_side(thread_doc)
		for message in messages:
			communication = _add_email(thread_doc, message, settings, customer, partner_side)
			frappe.db.set_value(
				"Connect Message", message.name, "crm_communication", communication, update_modified=False
			)
			frappe.db.commit()  # sent: a failure on the next message mustn't send this one again
	except Exception:
		frappe.db.rollback()
		# Logged once, not every hour the retry meets the same broken CRM.
		if thread_doc.crm_sync_status != "Failed":
			frappe.log_error(title=f"CRM sync failed for Connect Thread {thread}")
		thread_doc.db_set(
			{"crm_sync_status": "Failed", "crm_sync_error": frappe.get_traceback()[:2000]},
			update_modified=False,
		)
		return

	thread_doc.db_set(
		{"crm_sync_status": "Synced", "crm_synced_at": now_datetime(), "crm_sync_error": note},
		update_modified=False,
	)


def _customer_contact(thread_doc):
	"""The customer's person the Lead is about: whoever on their side wrote first, else their
	company's admin."""
	customer_side = frappe.get_all(
		"Connect Thread Member", filters={"thread": thread_doc.name, "side": "Customer"}, pluck="user"
	)
	first = customer_side and frappe.get_all(
		"Connect Message",
		filters={"thread": thread_doc.name, "sender": ["in", customer_side]},
		order_by="creation asc",
		limit=1,
		pluck="sender",
	)
	user = (first and first[0]) or frappe.db.get_value(
		"Customer Team Member", {"customer": thread_doc.customer, "is_admin": 1}, "user"
	)
	person = user and frappe.db.get_value("User", user, ["first_name", "last_name", "email"], as_dict=True)
	return person or frappe._dict()


def _partner_side(thread_doc):
	"""Everyone who writes for the partner in this thread, including people since removed: what
	they said was still the partner's."""
	people = set(
		frappe.get_all(
			"Connect Thread Member", filters={"thread": thread_doc.name, "side": "Partner"}, pluck="user"
		)
	)
	people.update(
		frappe.get_all("Connect Partner Member", filters={"partner": thread_doc.partner}, pluck="user")
	)
	if thread_doc.consultant:
		people.add(thread_doc.consultant)
	return people


def crm_user(settings, consultant):
	"""The consultant's user on the CRM, found by their Connect email, else their Suite email.
	None when the CRM has neither: the sales team assigns the Lead by hand then."""
	if not consultant:
		return None
	emails = [
		email
		for email in dict.fromkeys(
			[
				frappe.db.get_value("User", consultant, "email"),
				frappe.db.get_value("Frappe Consultant", consultant, "suite_email"),
			]
		)
		if email
	]
	if not emails:
		return None

	try:
		found = crm_request(
			settings,
			"GET",
			"/api/resource/User",
			params={
				"filters": frappe.as_json([["email", "in", emails], ["enabled", "=", 1]]),
				"fields": frappe.as_json(["name", "email"]),
			},
		).json()["data"]
	except Exception:
		# Leaves the Lead unowned rather than unmade: the chat matters more than who's on it.
		frappe.log_error(title=f"Couldn't find {consultant} on {settings.partner}'s CRM")
		return None

	users = {row["email"]: row["name"] for row in found}
	return next((users[email] for email in emails if email in users), None)


def _create_lead(thread_doc, settings, customer):
	"""Makes the thread's Lead, owned by its consultant when they're on the CRM. The CRM assigns
	the Lead to its owner itself. Returns the Lead and its owner."""
	customer_name = frappe.db.get_value("Customer", thread_doc.customer, "customer_name")
	owner = crm_user(settings, thread_doc.consultant)
	payload = {
		"first_name": customer.first_name or customer_name or "Connect Customer",
		"last_name": customer.last_name,
		"email": customer.email,
		"organization": customer_name,
		"lead_name": customer_name or customer.first_name,
		"status": settings.default_lead_status,
		"source": lead_source(
			settings, STARTER_PACK_LEAD_SOURCE if thread_doc.consultant else CHAT_LEAD_SOURCE
		),
		"lead_owner": owner,
	}
	lead = crm_request(
		settings, "POST", "/api/resource/CRM Lead", json={k: v for k, v in payload.items() if v}
	).json()["data"]["name"]
	return lead, owner


def _add_email(thread_doc, message, settings, customer, partner_side):
	"""Puts the message on the Lead as an email, as if the two sides had been emailing: the
	partner side's as sent to the customer, the customer's as received. The reply webhook skips
	what Connect posts, so a sent one never comes back as a reply. Returns the email's name."""
	sender = (
		frappe.db.get_value("User", message.sender, ["email", "full_name"], as_dict=True) or frappe._dict()
	)
	sent = message.sender in partner_side
	customer_name = frappe.db.get_value("Customer", thread_doc.customer, "customer_name")
	payload = {
		"communication_type": "Communication",
		"communication_medium": "Email",
		"sent_or_received": "Sent" if sent else "Received",
		"status": "Linked" if sent else "Open",
		"subject": f"Connect conversation with {customer_name or thread_doc.customer}",
		"sender": sender.email,
		"sender_full_name": sender.full_name,
		"recipients": customer.email if sent else None,
		"content": email_body(message),
		# When it was said, not when it reached the CRM: a chat sent across later reads in order.
		"communication_date": str(message.creation),
		"reference_doctype": "CRM Lead",
		"reference_name": thread_doc.crm_lead_id,
	}
	communication = crm_request(
		settings, "POST", "/api/resource/Communication", json={k: v for k, v in payload.items() if v}
	).json()["data"]["name"]

	if message.message_type == "File" and message.attachment:
		try:
			_attach_file_to_crm_communication(message, communication, settings)
		except Exception:
			frappe.log_error(title=f"CRM attachment upload failed for Connect Message {message.name}")
	return communication


def email_body(message):
	"""The message as an email's HTML: text as written, a card as the lines it shows in the chat."""
	if message.message_type == "Text":
		return text_html(message.content)
	if message.message_type == "File":
		return escape_html("📎 " + (message.file_name or _("Attachment")))

	card = frappe.parse_json(message.content or "{}") or {}
	title, fields = _card_fields(message.message_type, card)
	lines = [f"<b>{escape_html(title)}</b>"]
	lines += [f"{escape_html(label)}: {escape_html(str(value))}" for label, value in fields if value]
	return "<br>".join(lines)


def _card_fields(message_type, card):
	from connect.notifications import requirement_fields

	if message_type == "Requirement":
		return "Requirement", requirement_fields(card)
	if message_type == "Meeting":
		# starts_at is an ISO time ("2026-10-20T14:23:00+05:30"): its date and time are enough here.
		when = (card.get("starts_at") or "").replace("T", " ")[:16]
		return card.get("title") or "Kickoff call", [("When", when), ("Link", card.get("link"))]
	if message_type in ("Quote", "Hire Request"):
		amount = card.get("amount")
		weeks = card.get("weeks")
		return "Quote" if message_type == "Quote" else "Hire request", [
			("Project", card.get("project_name")),
			("Amount", amount and frappe.utils.fmt_money(amount, currency="INR", precision=0)),
			("Timeline", weeks and f"{weeks} weeks"),
			("Note", card.get("note")),
		]
	return message_type, []


def _attach_file_to_crm_communication(message, communication, settings):
	"""Uploads the message's attachment to the partner's CRM so they can actually open the file instead of just seeing its name."""
	file_doc = frappe.get_doc("File", {"file_url": message.attachment})
	# Not file_doc.get_content(): that method tries several text encodings on the raw bytes and
	# can succeed by coincidence on binary data, silently returning a corrupted string instead of
	# the original bytes — a real risk for images/PDFs/etc. Reading the file directly is exact.
	with open(file_doc.get_full_path(), "rb") as f:
		content = f.read()

	crm_request(
		settings,
		"POST",
		"/api/method/upload_file",
		data={"doctype": "Communication", "docname": communication, "is_private": 1},
		files={"file": (message.file_name or file_doc.file_name, content)},
	)


def queue_lead_owner_sync(doc, method=None):
	"""on_update on Connect Thread: when the thread's consultant changes, so does its Lead's owner."""
	if not doc.crm_lead_id or not doc.has_value_changed("consultant") or not crm_settings(doc.partner):
		return
	before = doc.get_doc_before_save()
	frappe.enqueue(
		"connect.crm_integration.sync_lead_owner",
		queue="short",
		enqueue_after_commit=True,
		thread=doc.name,
		previous=before and before.consultant,
	)


def sync_lead_owner(thread, previous=None):
	"""Background job: makes the thread's consultant the owner of its Lead, which assigns it to
	them, and takes it off the consultant before them."""
	thread_doc = frappe.get_doc("Connect Thread", thread)
	settings = crm_settings(thread_doc.partner)
	if not settings or not thread_doc.crm_lead_id:
		return

	try:
		owner = crm_user(settings, thread_doc.consultant)
		if owner:
			crm_request(
				settings,
				"PUT",
				f"/api/resource/CRM Lead/{quote(thread_doc.crm_lead_id)}",
				json={"lead_owner": owner},
			)
		else:
			# The Lead stays with the consultant before, for the sales team to reassign by hand.
			thread_doc.db_set(
				"crm_sync_error",
				_("The Lead's owner wasn't changed: {0} has no user on the CRM.").format(
					thread_doc.consultant
				),
				update_modified=False,
			)
			return

		before = crm_user(settings, previous)
		if before and before != owner:
			crm_request(
				settings,
				"POST",
				"/api/method/frappe.desk.form.assign_to.remove",
				json={"doctype": "CRM Lead", "name": thread_doc.crm_lead_id, "assign_to": before},
			)
	except Exception:
		frappe.log_error(title=f"CRM Lead owner change failed for Connect Thread {thread}")


def retry_crm_sync():
	"""Hourly: sends what a failed or missed sync left behind, for partners with sync on."""
	partners = frappe.get_all("Partner CRM Settings", filters={"enabled": 1}, pluck="partner")
	if not partners:
		return

	threads = set(
		frappe.get_all(
			"Connect Thread",
			filters={"partner": ["in", partners], "crm_sync_status": ["in", ["Queued", "Failed"]]},
			pluck="name",
		)
	)
	with_lead = frappe.get_all(
		"Connect Thread", filters={"partner": ["in", partners], "crm_lead_id": ["is", "set"]}, pluck="name"
	)
	if with_lead:
		threads.update(
			frappe.get_all(
				"Connect Message",
				filters={
					"thread": ["in", with_lead],
					"creation": ["<", add_to_date(now_datetime(), minutes=-RETRY_AFTER_MINUTES)],
					**unsynced_message_filters(),
				},
				pluck="thread",
				distinct=True,
			)
		)
	for thread in threads:
		queue_thread_sync(thread)


@frappe.whitelist(methods=["POST"])
def send_all_chats(partner: str) -> int:
	"""Desk: sends every one of the partner's chats to their CRM, the ones from before sync was
	turned on too. Returns how many chats were queued."""
	frappe.only_for("System Manager")
	if not crm_settings(partner):
		frappe.throw(_("Turn on CRM sync for this partner first."))
	threads = frappe.get_all("Connect Thread", filters={"partner": partner}, pluck="name")
	for thread in threads:
		queue_thread_sync(thread)
	return len(threads)


@frappe.whitelist(methods=["POST"])
def reset_reply_webhook(partner: str) -> None:
	"""Desk: sets up the reply webhook on the partner's CRM again, with Connect's current settings."""
	frappe.only_for("System Manager")
	doc = frappe.get_doc("Partner CRM Settings", partner)
	if not doc.enabled:
		frappe.throw(_("Turn on CRM sync for this partner first."))
	if not set_up_reply_webhook(doc):
		frappe.throw(_("Couldn't set up the reply webhook. The Error Log says why."))


def sync_reply_webhook(doc, method=None):
	"""on_update on Partner CRM Settings: sets up the Webhook on the partner's CRM that brings
	their replies into Connect, and again when the CRM's address or API key changes."""
	if doc.crm_type != "Frappe CRM" or not doc.enabled or not (doc.site_url and doc.api_key):
		return
	before = doc.get_doc_before_save()
	moved = before and (before.site_url != doc.site_url or before.api_key != doc.api_key)
	if doc.crm_reply_webhook_id and not moved:
		return
	set_up_reply_webhook(doc)


def reply_webhook(partner, integration_user, secret):
	"""The Webhook that brings the partner's replies into Connect: every email sent from a Lead,
	except those Connect itself posted there as its API user."""
	callback_url = frappe.utils.get_url(
		f"/api/method/connect.api.crm_webhook.receive_crm_reply?partner={quote(partner)}"
	)
	return {
		# Webhook's autoname is "prompt" — the caller must supply a docname explicitly.
		"name": f"Connect Reply Sync - {partner}",
		"webhook_doctype": "Communication",
		"webhook_docevent": "after_insert",
		"condition": (
			"doc.reference_doctype=='CRM Lead' and doc.sent_or_received=='Sent'"
			f" and doc.owner!={integration_user!r}"
		),
		"request_url": callback_url,
		"request_method": "POST",
		"request_structure": "Form URL-Encoded",
		"webhook_data": [{"fieldname": f, "key": f} for f in REPLY_WEBHOOK_FIELDS],
		"webhook_headers": [{"key": "Content-Type", "value": "application/json"}],
		"enable_security": 1,
		"webhook_secret": secret,
		"enabled": 1,
	}


def set_up_reply_webhook(doc) -> bool:
	"""Makes or updates the reply webhook on the partner's CRM, with a new secret. Returns whether
	it worked."""
	settings = frappe._dict(name=doc.name, partner=doc.partner, site_url=doc.site_url, api_key=doc.api_key)
	secret = frappe.generate_hash(length=32)
	try:
		integration_user = crm_request(settings, "GET", "/api/method/frappe.auth.get_logged_user").json()[
			"message"
		]
		payload = reply_webhook(doc.partner, integration_user, secret)
		try:
			crm_request(settings, "PUT", f"/api/resource/Webhook/{quote(payload['name'])}", json=payload)
		except CRMRequestError as e:
			if e.status_code != 404:
				raise
			crm_request(settings, "POST", "/api/resource/Webhook", json=payload)
	except Exception:
		frappe.log_error(title=f"CRM reply webhook setup failed for Partner CRM Settings {doc.name}")
		return False

	doc.db_set("crm_reply_webhook_id", payload["name"], update_modified=False)
	# db_set on a Password field writes the plain value straight to the main table, bypassing
	# the __Auth encryption path entirely — get_decrypted_password (used to verify incoming
	# replies) would never find it there. set_encrypted_password is the correct way to store it.
	set_encrypted_password("Partner CRM Settings", doc.name, secret, "crm_reply_webhook_secret")
	return True
