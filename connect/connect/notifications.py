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

	enqueue_create_notification(
		members,
		{
			"type": "Alert",
			"document_type": "Connect Thread",
			"document_name": doc.thread,
			"subject": frappe.utils.strip_html(doc.content)[:140],
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
