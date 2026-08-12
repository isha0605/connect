import frappe
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification


def notify_thread_members(doc, method=None):
	members = frappe.get_all(
		"Connect Thread Member",
		filters={"thread": doc.thread, "is_removed": 0, "user": ["!=", doc.sender]},
		pluck="user",
	)
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
