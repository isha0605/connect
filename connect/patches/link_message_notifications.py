import frappe

# Notification document type -> the message DocType and its thread field.
MESSAGE_SOURCES = {
	"Connect Thread": ("Connect Message", "thread", ""),
	"Connect DM Thread": ("Connect DM Message", "dm_thread", "&type=dm"),
}


def execute():
	"""Gives older message notifications the link new ones get, so clicking one opens the thread at
	that message. The message is the sender's latest one in the thread when the notification was made."""
	for document_type, source in MESSAGE_SOURCES.items():
		if frappe.db.table_exists(source[0]):
			link_notifications(document_type, *source)


def link_notifications(document_type: str, message_doctype: str, thread_field: str, suffix: str) -> None:
	logs = frappe.get_all(
		"Notification Log",
		filters={"document_type": document_type, "link": ["in", ["", None]]},
		fields=["name", "document_name", "from_user", "creation"],
	)

	for log in logs:
		message = frappe.db.get_value(
			message_doctype,
			{thread_field: log.document_name, "sender": log.from_user, "creation": ["<=", log.creation]},
			"name",
			order_by="creation desc",
		)
		link = f"/messaging?thread={log.document_name}{suffix}"
		if message:
			link += f"&message={message}"
		frappe.db.set_value("Notification Log", log.name, "link", link, update_modified=False)
