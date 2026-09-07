import frappe


def queue_crm_lead_sync(doc, method=None):
	"""Decides whether this message should create a new CRM Lead or just be added to one that already exists, without making the customer wait on the partner's CRM."""
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

	make_post_request(
		f"{base_url}/api/resource/Communication",
		headers=headers,
		json={
			"communication_type": "Communication",
			"communication_medium": "Email",
			# Always "Received": a future partner-reply sync would use "Sent" instead,
			# which is how we'll tell a real reply apart from this message echoing back.
			"sent_or_received": "Received",
			"status": "Open",
			"subject": f"Connect conversation with {customer_name or sender_email}",
			"sender": sender_email,
			"content": message_doc.content or "",
			"reference_doctype": "CRM Lead",
			"reference_name": lead_id or thread_doc.crm_lead_id,
		},
	)


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
		"first_name": sender.first_name or sender.email or "Connect Customer",
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
