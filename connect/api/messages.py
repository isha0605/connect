import json

import frappe

from connect.api.attachments import _attach_file_to_message, _claim_staged_attachment, _copy_message_attachment
from connect.permissions import (
	_check_can_read,
	_check_can_write,
	_dm_thread_pair,
	_has_full_access,
	_thread_membership,
)

# Requirement cards are one-off snapshots tied to their thread, so only plain text and files can be
# forwarded.
FORWARDABLE_MESSAGE_TYPES = ("Text", "File")

MIN_SEARCH_LENGTH = 2
MAX_SEARCH_RESULTS = 50


PINNED_MESSAGE_FIELDS = [
	"name", "sender", "message_type", "content", "file_name", "creation", "pinned_by", "pinned_at"
]


@frappe.whitelist()
def send_message(
	thread,
	content="",
	file_url=None,
	file_name=None,
	file_type=None,
	file_size=None,
	requirement_data=None,
	reply_to=None,
	silent=0,
):
	"""Sends any message type down one path so the client only has to call one endpoint; silent skips notifying others."""
	user = frappe.session.user
	requirement_data = frappe.parse_json(requirement_data) if isinstance(requirement_data, str) else requirement_data
	content = (content or "").strip()

	_check_can_write(thread, user)

	file_doc_name = _claim_staged_attachment(file_url, user) if file_url else None

	if requirement_data:
		message_type = "Requirement"
		message_content = json.dumps(requirement_data)
	elif file_url:
		message_type = "File"
		message_content = content or file_name
	else:
		message_type = "Text"
		message_content = content

	message = frappe.get_doc({
		"doctype": "Connect Message",
		"thread": thread,
		"sender": user,
		"message_type": message_type,
		"content": message_content,
		# Only a reply to a message already in this same thread is meaningful — a stray/cross-thread
		# reply_to would show a quote the recipient has no way to see.
		"reply_to": reply_to if reply_to and frappe.db.exists("Connect Message", {"name": reply_to, "thread": thread}) else None,
	})
	if file_url:
		message.attachment = file_url
		message.file_name = file_name
		message.file_type = file_type
		message.file_size = file_size
	message.flags.silent = frappe.utils.cint(silent)
	message.insert()

	if file_doc_name:
		_attach_file_to_message(file_doc_name, "Connect Message", message.name)

	return message.as_dict()


@frappe.whitelist()
def delete_message(message):
	"""Thin API entry; ownership and cleanup are enforced on Connect Message itself."""
	frappe.delete_doc("Connect Message", message)


@frappe.whitelist()
def edit_message(message, content):
	"""Thin API entry; ownership and edit rules are enforced on Connect Message itself."""
	doc = frappe.get_doc("Connect Message", message)
	doc.content = content
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def pin_message(message):
	"""Thin API entry; the pin rules and access check live on Connect Message."""
	doc = frappe.get_doc("Connect Message", message)
	doc.pin(frappe.session.user)
	return {"thread": doc.thread, "message": doc.name, "is_pinned": 1}


@frappe.whitelist()
def unpin_message(message):
	doc = frappe.get_doc("Connect Message", message)
	doc.unpin(frappe.session.user)
	return {"thread": doc.thread, "message": doc.name, "is_pinned": 0}


@frappe.whitelist()
def get_pinned_messages(thread):
	"""Returns the thread's pins newest first, filtered by the same read query so a removed member sees only pins from their time."""
	_check_can_read(thread, frappe.session.user)
	return frappe.get_list(
		"Connect Message",
		filters={"thread": thread, "is_pinned": 1},
		fields=PINNED_MESSAGE_FIELDS,
		order_by="pinned_at desc",
		limit_page_length=0,
	)


@frappe.whitelist()
def get_forward_targets():
	"""Returns only conversations the caller can actually post into, so the forward menu never offers a dead end."""
	user = frappe.session.user

	thread_filters = {"status": ["!=", "Closed"]}
	if not _has_full_access(user):
		writable = frappe.get_all(
			"Connect Thread Member",
			filters={"user": user, "permission": "Write", "is_removed": 0},
			pluck="thread",
		)
		if not writable:
			thread_filters = None
		else:
			thread_filters["name"] = ["in", writable]
	threads = frappe.get_list("Connect Thread", filters=thread_filters, pluck="name") if thread_filters else []

	dm_threads = frappe.get_list(
		"Connect DM Thread", or_filters=[["user_a", "=", user], ["user_b", "=", user]], pluck="name"
	)

	return {"company": threads, "dm": dm_threads}


@frappe.whitelist()
def forward_message(message, source_is_dm, target_thread, target_is_dm):
	"""Forwards a message as the caller so the target sees a real post from them, not an impersonated original sender."""
	user = frappe.session.user
	source_is_dm = frappe.utils.cint(source_is_dm)
	target_is_dm = frappe.utils.cint(target_is_dm)

	source = frappe.get_doc("Connect DM Message" if source_is_dm else "Connect Message", message)
	source.check_permission("read")
	if source.message_type not in FORWARDABLE_MESSAGE_TYPES:
		frappe.throw(frappe._("Only text and file messages can be forwarded"))

	source_thread = source.dm_thread if source_is_dm else source.thread
	if source_thread == target_thread and source_is_dm == target_is_dm:
		frappe.throw(frappe._("You can't forward a message into the conversation it's already in"))

	if target_is_dm:
		_dm_thread_pair(target_thread, user)
	else:
		_check_can_write(target_thread, user)

	values = {
		"doctype": "Connect DM Message" if target_is_dm else "Connect Message",
		"dm_thread" if target_is_dm else "thread": target_thread,
		"sender": user,
		"message_type": source.message_type,
		"content": source.content,
		"is_forwarded": 1,
	}
	file_copy = _copy_message_attachment(source.attachment) if source.attachment else None
	if file_copy:
		values.update(
			attachment=file_copy.file_url,
			file_name=source.file_name,
			file_type=source.file_type,
			file_size=source.file_size,
		)
	forwarded = frappe.get_doc(values)
	forwarded.insert()

	if file_copy:
		_attach_file_to_message(file_copy.name, forwarded.doctype, forwarded.name)

	return forwarded.as_dict()


@frappe.whitelist()
def search_messages(query, thread=None, is_dm=0, kind="messages"):
	"""Searches only conversations the caller can already read, so results never leak a message they couldn't open anyway."""
	query = (query or "").strip()
	if len(query) < MIN_SEARCH_LENGTH:
		return []
	is_dm = frappe.utils.cint(is_dm)
	pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

	if kind == "files":
		filters = [["message_type", "=", "File"], ["file_name", "like", pattern]]
	elif kind == "links":
		filters = [["message_type", "=", "Text"], ["content", "like", pattern], ["content", "like", "%http%"]]
	else:
		filters = [["message_type", "=", "Text"], ["content", "like", pattern]]

	sources = [(False, "Connect Message", "thread"), (True, "Connect DM Message", "dm_thread")]
	results = []
	for source_is_dm, doctype, thread_field in sources:
		if thread and source_is_dm != bool(is_dm):
			continue
		scoped = filters + ([[thread_field, "=", thread]] if thread else [])
		rows = frappe.get_list(
			doctype,
			filters=scoped,
			fields=["name", f"{thread_field} as thread", "sender", "message_type", "content", "file_name", "creation"],
			order_by="creation desc",
			limit_page_length=MAX_SEARCH_RESULTS,
		)
		for row in rows:
			row["is_dm"] = int(source_is_dm)
		results.extend(rows)

	results.sort(key=lambda r: r.creation, reverse=True)
	results = results[:MAX_SEARCH_RESULTS]

	full_names = {
		u.name: u.full_name
		for u in frappe.get_all(
			"User", filters={"name": ["in", list({r.sender for r in results})]}, fields=["name", "full_name"]
		)
	}
	for row in results:
		row["sender_full_name"] = full_names.get(row.sender)
	return results
