import frappe
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification


def _notification_targets(doc):
	"""Who's allowed to know this message exists at all — a private message's audience is
	just its sender + recipients; everyone else on the thread (even members with full read
	access to the thread otherwise) never learns it was sent, let alone deleted."""
	if doc.is_private:
		# private_to is stored comma-padded (",a@x.com,b@y.com,") for cheap LIKE-based permission
		# checks elsewhere — split it back into a plain list here
		recipients = [u for u in (doc.private_to or "").split(",") if u]
		return frappe.get_all(
			"Connect Thread Member",
			filters={"thread": doc.thread, "is_removed": 0, "user": ["in", recipients]},
			pluck="user",
		)
	return frappe.get_all(
		"Connect Thread Member",
		filters={"thread": doc.thread, "is_removed": 0, "user": ["!=", doc.sender]},
		pluck="user",
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
	# might still get rolled back later in this same request. `members` is already narrowed
	# to just the recipients for a private message, so this never reaches anyone it shouldn't.
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
		"is_private": doc.is_private,
		"private_to": doc.private_to,
		"creation": str(doc.creation),
	}
	for member in members:
		frappe.publish_realtime("connect_new_message", payload, user=member, after_commit=True)


def notify_message_deleted(doc):
	"""Live-push a deletion the same way a new message gets pushed, to the same restricted
	audience — called explicitly from api.delete_message (there's no after_delete doc_event
	hook wired up for Connect Message, and by the time one would fire the doc's own fields
	needed to compute the audience are already gone). The sender doesn't need this: they
	already remove the message from their own view right after the delete call succeeds."""
	members = _notification_targets(doc)
	if not members:
		return
	payload = {"name": doc.name, "thread": doc.thread}
	for member in members:
		frappe.publish_realtime("connect_message_deleted", payload, user=member, after_commit=True)


def notify_message_edited(doc):
	"""Same restricted audience as a new message — an edited private message must not leak its
	new content to anyone outside its original recipients. The editor's own tab already shows
	the new content right after the edit call resolves."""
	members = _notification_targets(doc)
	if not members:
		return
	payload = {"name": doc.name, "thread": doc.thread, "content": doc.content, "is_edited": doc.is_edited}
	for member in members:
		frappe.publish_realtime("connect_message_edited", payload, user=member, after_commit=True)


def notify_dm_recipient(doc, method=None):
	"""Mirrors notify_thread_members, simplified: a DM thread has exactly one other party, so
	there's no audience computation — just push straight to whichever of user_a/user_b isn't
	the sender."""
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
	"""DM counterpart to notify_thread_pin_changed — the "everyone but the actor" audience is
	just the one other participant. `message_doc` is None on unpin."""
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
	"""Pinning is thread-wide (not audience-restricted like a message's own visibility), so
	every active member hears about it — except `actor`, whose own tab already updated right
	after the pin/unpin call resolved. `message_doc` is None on unpin."""
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
