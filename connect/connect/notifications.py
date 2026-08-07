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
