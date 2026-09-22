import frappe

WEBHOOK_SECRET_HEADER = "X-Frappe-Webhook-Signature"


def queue_crm_lead_sync(doc, method=None):
	"""Decides whether this message should create a new CRM Lead or just be added to one that already exists, without making the customer wait on the partner's CRM."""
	if doc.flags.get("skip_crm_sync"):
		return  # this message was itself synced in from the partner's CRM reply — don't echo it back
	if doc.message_type == "System":
		return

	thread = frappe.db.get_value(
		"Connect Thread", doc.thread, ["name", "partner", "crm_lead_id"], as_dict=True
	)
	if not thread:
		return

	if not frappe.db.exists("Partner CRM Settings", {"partner": thread.partner, "enabled": 1}):
		return

	if thread.crm_lead_id:
		frappe.enqueue(
			"connect.crm_integration.sync_message_as_email",
			queue="short",
			thread=thread.name,
			message=doc.name,
			enqueue_after_commit=True,
		)
		return

	if frappe.db.count("Connect Message", {"thread": doc.thread}) != 1:
		return  # not the first message, and no Lead yet — nothing to attach to

	frappe.db.set_value("Connect Thread", thread.name, "crm_sync_status", "Queued", update_modified=False)
	frappe.enqueue(
		"connect.crm_integration.create_crm_lead",
		queue="short",
		thread=thread.name,
		message=doc.name,
		# Without this, the worker can dequeue and run before this request's transaction
		# commits, and fail to find the Connect Thread/Message it was just handed.
		enqueue_after_commit=True,
	)


def create_crm_lead(thread, message):
	"""Runs in the background so a slow or broken partner CRM never delays the customer's message."""
	thread_doc = frappe.get_doc("Connect Thread", thread)
	if thread_doc.crm_lead_id:
		return  # already synced — the check in queue_crm_lead_sync is only a fast filter

	settings = frappe.db.get_value(
		"Partner CRM Settings",
		{"partner": thread_doc.partner, "enabled": 1},
		["name", "crm_type", "site_url", "api_key", "default_lead_status"],
		as_dict=True,
	)
	if not settings:
		thread_doc.db_set("crm_sync_status", "Failed", update_modified=False)
		thread_doc.db_set(
			"crm_sync_error", "No enabled CRM settings for this partner", update_modified=False
		)
		return

	try:
		if settings.crm_type == "Frappe CRM":
			lead_id = _create_frappe_crm_lead(thread_doc, message, settings)
		else:
			frappe.throw(f"Unsupported CRM type: {settings.crm_type}")

		thread_doc.db_set("crm_lead_id", lead_id, update_modified=False)
		thread_doc.db_set("crm_sync_status", "Synced", update_modified=False)
		thread_doc.db_set("crm_synced_at", frappe.utils.now_datetime(), update_modified=False)
		thread_doc.db_set("crm_sync_error", "", update_modified=False)
	except Exception:
		frappe.log_error(title=f"CRM Lead sync failed for Connect Thread {thread}")
		thread_doc.db_set("crm_sync_status", "Failed", update_modified=False)
		thread_doc.db_set("crm_sync_error", frappe.get_traceback()[:2000], update_modified=False)


def sync_message_as_email(thread, message):
	"""Runs in the background so the partner keeps seeing new messages in their CRM without the customer waiting on it."""
	thread_doc = frappe.get_doc("Connect Thread", thread)
	if not thread_doc.crm_lead_id:
		return

	settings = frappe.db.get_value(
		"Partner CRM Settings",
		{"partner": thread_doc.partner, "enabled": 1},
		["name", "crm_type", "site_url", "api_key"],
		as_dict=True,
	)
	if not settings:
		return

	try:
		if settings.crm_type == "Frappe CRM":
			_add_frappe_crm_email(thread_doc, message, settings)
		else:
			frappe.throw(f"Unsupported CRM type: {settings.crm_type}")
	except Exception:
		frappe.log_error(title=f"CRM email sync failed for Connect Thread {thread}")


def _add_frappe_crm_email(thread_doc, message, settings, lead_id=None):
	"""Sends the message to the partner's CRM as an email, so their whole conversation reads naturally in one place instead of scattered notes."""
	from frappe.integrations.utils import make_post_request
	from frappe.utils.password import get_decrypted_password

	api_secret = get_decrypted_password("Partner CRM Settings", settings.name, "api_secret")
	headers = {"Authorization": f"token {settings.api_key}:{api_secret}"}
	base_url = settings.site_url.rstrip("/")

	message_doc = frappe.get_doc("Connect Message", message)
	customer_name = frappe.db.get_value("Customer", thread_doc.customer, "customer_name")
	sender_email = frappe.db.get_value("User", message_doc.sender, "email")

	response = make_post_request(
		f"{base_url}/api/resource/Communication",
		headers=headers,
		json={
			"communication_type": "Communication",
			"communication_medium": "Email",
			# Always "Received": a partner's reply is a separate Communication their CRM creates
			# when they reply — this is how we tell a real reply apart from this message echoing back.
			"sent_or_received": "Received",
			"status": "Open",
			"subject": f"Connect conversation with {customer_name or thread_doc.customer}",
			"sender": sender_email,
			"content": message_doc.content or "",
			"reference_doctype": "CRM Lead",
			"reference_name": lead_id or thread_doc.crm_lead_id,
		},
	)

	if message_doc.message_type == "File" and message_doc.attachment:
		try:
			_attach_file_to_crm_communication(message_doc, response["data"]["name"], base_url, headers)
		except Exception:
			frappe.log_error(title=f"CRM attachment upload failed for Connect Message {message_doc.name}")


def _attach_file_to_crm_communication(message_doc, communication_name, base_url, headers):
	"""Uploads the message's local attachment to the partner's CRM, attached to the Communication
	just created there — otherwise the partner only sees the filename as text and can't open it."""
	import requests

	file_doc = frappe.get_doc("File", {"file_url": message_doc.attachment})
	# Not file_doc.get_content(): that method tries several text encodings on the raw bytes and
	# can succeed by coincidence on binary data, silently returning a corrupted string instead of
	# the original bytes — a real risk for images/PDFs/etc. Reading the file directly is exact.
	with open(file_doc.get_full_path(), "rb") as f:
		content = f.read()

	response = requests.post(
		f"{base_url}/api/method/upload_file",
		headers=headers,
		data={"doctype": "Communication", "docname": communication_name, "is_private": 1},
		files={"file": (message_doc.file_name or file_doc.file_name, content)},
	)
	response.raise_for_status()


def _create_frappe_crm_lead(thread_doc, message, settings):
	"""Turns the customer's first message into an actual Lead record in the partner's CRM."""
	from frappe.integrations.utils import make_post_request
	from frappe.utils.password import get_decrypted_password

	api_secret = get_decrypted_password("Partner CRM Settings", settings.name, "api_secret")
	headers = {"Authorization": f"token {settings.api_key}:{api_secret}"}
	base_url = settings.site_url.rstrip("/")

	message_doc = frappe.get_doc("Connect Message", message)
	customer_name = frappe.db.get_value("Customer", thread_doc.customer, "customer_name")
	sender = frappe.db.get_value(
		"User", message_doc.sender, ["first_name", "last_name", "email"], as_dict=True
	)

	payload = {
		"first_name": sender.first_name or customer_name or "Connect Customer",
		"last_name": sender.last_name,
		"email": sender.email,
		"organization": customer_name,
		"lead_name": customer_name or sender.first_name,
		"status": settings.default_lead_status,
	}

	response = make_post_request(f"{base_url}/api/resource/CRM Lead", headers=headers, json=payload)
	lead_name = response["data"]["name"]

	try:
		_add_frappe_crm_email(thread_doc, message, settings, lead_id=lead_name)
	except Exception:
		frappe.log_error(title=f"CRM email attach failed for Lead {lead_name}")

	return lead_name


def sync_reply_webhook(doc, method=None):
	"""on_update on Partner CRM Settings: registers a Webhook on the partner's Frappe CRM site so a
	reply the partner sends there is also pushed to receive_crm_reply and shown in the Connect
	thread — in addition to reaching the customer as a normal email, since nothing masks the
	customer's address here. Registers once and leaves it in place — disabling sync here pauses
	queue_crm_lead_sync but doesn't tear down the remote webhook, since Frappe CRM will just stop
	matching any lead once nothing new syncs."""
	if doc.crm_type != "Frappe CRM" or not doc.enabled or doc.crm_reply_webhook_id:
		return
	if not (doc.site_url and doc.api_key):
		return

	from urllib.parse import quote

	from frappe.integrations.utils import make_post_request
	from frappe.utils.password import get_decrypted_password

	secret = frappe.generate_hash(length=32)
	api_secret = get_decrypted_password("Partner CRM Settings", doc.name, "api_secret")
	headers = {"Authorization": f"token {doc.api_key}:{api_secret}"}
	base_url = doc.site_url.rstrip("/")
	callback_url = frappe.utils.get_url(
		f"/api/method/connect.api.crm_webhook.receive_crm_reply?partner={quote(doc.partner)}"
	)

	fields = ["name", "reference_doctype", "reference_name", "sent_or_received", "content", "creation"]
	payload = {
		# Webhook's autoname is "prompt" — the caller must supply a docname explicitly.
		"name": f"Connect Reply Sync - {doc.partner}",
		"webhook_doctype": "Communication",
		"webhook_docevent": "after_insert",
		"condition": "doc.reference_doctype=='CRM Lead' and doc.sent_or_received=='Sent'",
		"request_url": callback_url,
		"request_method": "POST",
		"request_structure": "Form URL-Encoded",
		"webhook_data": [{"fieldname": f, "key": f} for f in fields],
		"webhook_headers": [{"key": "Content-Type", "value": "application/json"}],
		"enable_security": 1,
		"webhook_secret": secret,
		"enabled": 1,
	}

	try:
		response = make_post_request(f"{base_url}/api/resource/Webhook", headers=headers, json=payload)
		doc.db_set("crm_reply_webhook_id", response["data"]["name"], update_modified=False)
		# db_set on a Password field writes the plain value straight to the main table, bypassing
		# the __Auth encryption path entirely — get_decrypted_password (used to verify incoming
		# replies) would never find it there. set_encrypted_password is the correct way to store it.
		from frappe.utils.password import set_encrypted_password

		set_encrypted_password("Partner CRM Settings", doc.name, secret, "crm_reply_webhook_secret")
	except Exception:
		frappe.log_error(title=f"CRM reply webhook registration failed for Partner CRM Settings {doc.name}")
