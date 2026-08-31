import frappe
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification


def _notification_targets(doc):
	"""Returns everyone else currently in the thread, who's allowed to know this message exists."""
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
