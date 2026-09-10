import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

from connect.permissions import _get_partner_admin


def _notification_targets(doc):
	"""Returns everyone else currently in the thread, who's allowed to know this message exists."""
	return frappe.get_all(
		"Connect Thread Member",
		filters={"thread": doc.thread, "is_removed": 0, "user": ["!=", doc.sender]},
		pluck="user",
	)


def _message_preview_text(message):
	"""The sidebar preview string for a message (dict or doc) — same 140-char truncation and
	per-type formatting get_my_threads/get_my_dm_threads used to compute inline on every read."""
	if message.get("message_type") == "File":
		text = "📎 " + (message.get("file_name") or _("Attachment"))
	elif message.get("message_type") == "Requirement":
		text = _("Requirement details")
	else:
		text = message.get("content") or ""
	return text[:140]


def _set_thread_last_message(thread_doctype, thread_name, message=None):
	"""Writes (or clears, if message is None) the denormalized last_message* fields on a thread —
	the single source get_my_threads/get_my_dm_threads read from instead of looking up the actual
	latest message on every sidebar load."""
	values = (
		{
			"last_message": message["name"],
			"last_message_at": message["creation"],
			"last_message_preview": _message_preview_text(message),
			"last_message_sender": message["sender"],
		}
		if message
		else {"last_message": None, "last_message_at": None, "last_message_preview": None, "last_message_sender": None}
	)
	frappe.db.set_value(thread_doctype, thread_name, values, update_modified=False)


def _recompute_thread_last_message(thread_doctype, message_doctype, thread_name, thread_field, exclude=None):
	"""Re-derives a thread's cached last message from the DB — used when the message that was
	cached gets deleted, so the cache falls back to whatever's now the true latest (or clears if
	the thread has no messages left)."""
	filters = {thread_field: thread_name}
	if exclude:
		filters["name"] = ["!=", exclude]
	rows = frappe.get_all(
		message_doctype,
		filters=filters,
		fields=["name", "creation", "sender", "message_type", "content", "file_name"],
		order_by="creation desc",
		limit_page_length=1,
	)
	_set_thread_last_message(thread_doctype, thread_name, rows[0] if rows else None)


def sync_thread_last_message(doc, method=None):
	"""after_insert on Connect Message: a new message is unambiguously the thread's latest, so
	this writes straight from the doc with no extra query."""
	_set_thread_last_message("Connect Thread", doc.thread, doc.as_dict())


def sync_dm_thread_last_message(doc, method=None):
	"""after_insert on Connect DM Message — DM counterpart to sync_thread_last_message. Also
	replaces the old ad-hoc `frappe.db.set_value(..., "modified", ...)` call that used to live in
	send_dm_message just to bump the DM inbox's sort order."""
	_set_thread_last_message("Connect DM Thread", doc.dm_thread, doc.as_dict())


def resync_thread_last_message_on_edit(doc):
	"""Called from Connect Message's on_update, only when the message was actually edited (see
	its _was_edited flag) — refreshes the cached preview if this message is still the thread's
	last one. A no-op otherwise: editing an older message doesn't change what the sidebar shows."""
	if frappe.db.get_value("Connect Thread", doc.thread, "last_message") == doc.name:
		_set_thread_last_message("Connect Thread", doc.thread, doc.as_dict())


def resync_dm_thread_last_message_on_edit(doc):
	"""DM counterpart to resync_thread_last_message_on_edit."""
	if frappe.db.get_value("Connect DM Thread", doc.dm_thread, "last_message") == doc.name:
		_set_thread_last_message("Connect DM Thread", doc.dm_thread, doc.as_dict())


def resync_thread_last_message_on_trash(doc):
	"""Called from Connect Message's on_trash, before the row is actually removed — if this
	message is the thread's cached last one, recomputes from whatever's left."""
	if frappe.db.get_value("Connect Thread", doc.thread, "last_message") == doc.name:
		_recompute_thread_last_message("Connect Thread", "Connect Message", doc.thread, "thread", exclude=doc.name)


def resync_dm_thread_last_message_on_trash(doc):
	"""DM counterpart to resync_thread_last_message_on_trash."""
	if frappe.db.get_value("Connect DM Thread", doc.dm_thread, "last_message") == doc.name:
		_recompute_thread_last_message(
			"Connect DM Thread", "Connect DM Message", doc.dm_thread, "dm_thread", exclude=doc.name
		)


def notify_thread_members(doc, method=None):
	members = _notification_targets(doc)
	if not members:
		return

	subject = "Shared requirement details" if doc.message_type == "Requirement" else frappe.utils.strip_html(doc.content)
	enqueue_create_notification(
		members,
		{
			"type": "Alert",
			"document_type": "Connect Thread",
			"document_name": doc.thread,
			"subject": subject[:140],
			"from_user": doc.sender,
		},
	)

	# Live push for anyone with the thread open right now — same shape as the `messages`
	# Document List resource in messaging.json, so the client can drop it straight into
	# that array with no refetch. after_commit=True: don't tell a client about a row that
	# might still get rolled back later in this same request.
	payload = {
		"name": doc.name,
		"thread": doc.thread,
		"sender": doc.sender,
		"message_type": doc.message_type,
		"content": doc.content,
		"attachment": doc.attachment,
		"file_name": doc.file_name,
		"file_type": doc.file_type,
		"file_size": doc.file_size,
		"creation": str(doc.creation),
	}
	for member in members:
		frappe.publish_realtime("connect_new_message", payload, user=member, after_commit=True)


def notify_message_deleted(doc):
	"""Live-pushes a message deletion to every other thread member."""
	members = _notification_targets(doc)
	if not members:
		return
	payload = {"name": doc.name, "thread": doc.thread}
	for member in members:
		frappe.publish_realtime("connect_message_deleted", payload, user=member, after_commit=True)


def notify_message_edited(doc):
	"""Live-pushes an edited message to every other thread member."""
	members = _notification_targets(doc)
	if not members:
		return
	payload = {"name": doc.name, "thread": doc.thread, "content": doc.content, "is_edited": doc.is_edited}
	for member in members:
		frappe.publish_realtime("connect_message_edited", payload, user=member, after_commit=True)


def notify_partner_of_new_requirement(doc, method=None):
	"""after_insert on Connect Message: emails the partner's admin when a customer's first message
	in the thread is a Requirement submission — a brand-new lead is easy to miss in the in-app
	notification alone."""
	if doc.message_type != "Requirement":
		return
	if frappe.db.count("Connect Message", {"thread": doc.thread}) != 1:
		return  # not the first message in this thread

	thread = frappe.db.get_value("Connect Thread", doc.thread, ["partner", "customer"], as_dict=True)
	if not thread:
		return

	admin = _get_partner_admin(thread.partner)
	if not admin:
		return
	recipient = frappe.db.get_value("User", admin, "email") or admin

	customer_name = frappe.db.get_value("Customer", thread.customer, "customer_name") or thread.customer
	requirement = frappe.parse_json(doc.content) if doc.content else {}
	fields = [
		("Company", requirement.get("company_name")),
		("Industry", requirement.get("industry")),
		("Looking for", requirement.get("looking_for")),
		("Company size", requirement.get("company_size")),
		("Timeline", requirement.get("timeline")),
	]
	details_html = "".join(
		f"<p><b>{label}:</b> {frappe.utils.escape_html(value)}</p>" for label, value in fields if value
	)

	frappe.sendmail(
		recipients=[recipient],
		subject=_("New requirement from {0}").format(customer_name),
		message=f"<p>{frappe.utils.escape_html(customer_name)} {_('just sent a new requirement on Connect.')}</p>{details_html}",
		now=False,
	)


def notify_dm_recipient(doc, method=None):
	"""Live-pushes a new DM to the one other participant in the thread."""
	pair = frappe.db.get_value("Connect DM Thread", doc.dm_thread, ["user_a", "user_b"], as_dict=True)
	if not pair:
		return
	recipient = pair.user_b if pair.user_a == doc.sender else pair.user_a

	enqueue_create_notification(
		[recipient],
		{
			"type": "Alert",
			"document_type": "Connect DM Thread",
			"document_name": doc.dm_thread,
			"subject": frappe.utils.strip_html(doc.content)[:140],
			"from_user": doc.sender,
		},
	)

	payload = {
		"name": doc.name,
		"dm_thread": doc.dm_thread,
		"sender": doc.sender,
		"content": doc.content,
		"creation": str(doc.creation),
	}
	frappe.publish_realtime("connect_new_dm_message", payload, user=recipient, after_commit=True)


def notify_dm_message_deleted(doc):
	"""DM counterpart to notify_message_deleted — single fixed recipient, no audience computation."""
	pair = frappe.db.get_value("Connect DM Thread", doc.dm_thread, ["user_a", "user_b"], as_dict=True)
	if not pair:
		return
	recipient = pair.user_b if pair.user_a == doc.sender else pair.user_a
	payload = {"name": doc.name, "dm_thread": doc.dm_thread}
	frappe.publish_realtime("connect_dm_message_deleted", payload, user=recipient, after_commit=True)


def notify_dm_message_edited(doc):
	"""DM counterpart to notify_message_edited."""
	pair = frappe.db.get_value("Connect DM Thread", doc.dm_thread, ["user_a", "user_b"], as_dict=True)
	if not pair:
		return
	recipient = pair.user_b if pair.user_a == doc.sender else pair.user_a
	payload = {"name": doc.name, "dm_thread": doc.dm_thread, "content": doc.content, "is_edited": doc.is_edited}
	frappe.publish_realtime("connect_dm_message_edited", payload, user=recipient, after_commit=True)


def notify_dm_thread_pin_changed(thread_doc, message_doc, actor):
	"""Live-pushes a pin/unpin change to the one other DM participant."""
	recipient = thread_doc.user_b if thread_doc.user_a == actor else thread_doc.user_a
	payload = {
		"thread": thread_doc.name,
		"pinned_message": message_doc.name if message_doc else None,
		"sender": message_doc.sender if message_doc else None,
		"message_type": message_doc.message_type if message_doc else None,
		"content": message_doc.content if message_doc else None,
		"file_name": message_doc.file_name if message_doc else None,
	}
	frappe.publish_realtime("connect_dm_thread_pin_changed", payload, user=recipient, after_commit=True)


def notify_thread_pin_changed(thread_doc, message_doc, actor):
	"""Live-pushes a pin/unpin change to every other active thread member."""
	members = frappe.get_all(
		"Connect Thread Member",
		filters={"thread": thread_doc.name, "is_removed": 0, "user": ["!=", actor]},
		pluck="user",
	)
	if not members:
		return
	payload = {
		"thread": thread_doc.name,
		"pinned_message": message_doc.name if message_doc else None,
		"sender": message_doc.sender if message_doc else None,
		"message_type": message_doc.message_type if message_doc else None,
		"content": message_doc.content if message_doc else None,
		"file_name": message_doc.file_name if message_doc else None,
	}
	for member in members:
		frappe.publish_realtime("connect_thread_pin_changed", payload, user=member, after_commit=True)
