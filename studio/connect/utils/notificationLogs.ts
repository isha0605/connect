// How Connect reads a Notification Log: its category, title and body. Shared by the sidebar's
// Notifications item (its toast) and the Notifications panel, so both word a notification alike.

export const LOG_API = "frappe.desk.doctype.notification_log.notification_log"

// Mirrors CONNECT_NOTIFICATION_DOCTYPES in connect/notifications.py. Anything else (Frappe's
// impersonation or mail-server alerts) isn't shown.
const CATEGORY_OF_DOCTYPE = {
	"Connect Thread": "messages",
	"Connect DM Thread": "messages",
	"Customer Project": "projects",
	"Project Quote": "projects",
	"Starter Pack Order": "projects",
}

// Grouped by the linked document, not the subject text, so wording changes never move a row.
export function categoryOf(log) {
	return CATEGORY_OF_DOCTYPE[log.document_type] || null
}

// `users` is get_notification_logs' user_info, for the sender of a message.
export function titleOf(log, users = {}) {
	if (categoryOf(log) !== "messages") return plainText(log.subject)
	const sender = users[log.from_user]?.fullname || log.from_user || "Someone"
	return `New message from ${sender}`
}

export function bodyOf(log) {
	return plainText(categoryOf(log) === "messages" ? log.subject : log.email_content)
}

export function plainText(html) {
	const element = document.createElement("div")
	element.innerHTML = html || ""
	return (element.textContent || "").trim()
}
