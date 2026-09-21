import json

import frappe

from connect.api.attachments import _attach_file_to_message, _claim_staged_attachment, _copy_message_attachment
from connect.notifications import notify_reaction_changed
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

MAX_EMOJI_LENGTH = 32

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
):
	"""Creates a chat message carrying text, a file, or a Requirement snapshot — one path for every message type."""
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
	message.insert()

	if file_doc_name:
		_attach_file_to_message(file_doc_name, "Connect Message", message.name)

	return message.as_dict()


@frappe.whitelist()
def delete_message(message):
	"""Deletes a message for everyone; authorization and cleanup live in has_message_permission and Connect Message's on_trash()."""
	frappe.delete_doc("Connect Message", message)


@frappe.whitelist()
def edit_message(message, content):
	"""Edits your own text message in place; authorization and validation live in has_message_permission and Connect Message's validate()."""
	doc = frappe.get_doc("Connect Message", message)
	doc.content = content
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def pin_message(message):
	"""Pins a message (a thread can hold any number); the pin rules themselves live on Connect Message."""
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
	"""A thread's pinned messages, most recently pinned first. Read through the message permission query
	conditions, so a removed member only sees pins up to the moment they were removed."""
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
	"""Lists the conversations the caller can forward a message into right now: threads where they have
	Write access and that aren't closed, plus every DM of theirs. Display data (names, avatars) is left to
	the client, which already has it from get_my_threads / get_my_dm_threads."""
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
	"""Sends a copy of a text or file message into another conversation as the caller, flagged as forwarded.
	Reading the original is checked by Frappe's permission system; posting to the target goes through the
	same write checks as send_message / send_dm_message."""
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
def get_reactions(thread, is_dm=0):
	"""Every reaction in a conversation, oldest first, so the client can group them per message. A
	removed thread member only sees reactions made up to the moment they were removed."""
	user = frappe.session.user
	is_dm = frappe.utils.cint(is_dm)
	filters = {"thread": thread, "is_dm": is_dm}

	if is_dm:
		_dm_thread_pair(thread, user)
	else:
		_check_can_read(thread, user)
		membership = _thread_membership(thread, user)
		if membership and membership.is_removed and membership.removed_on:
			filters["creation"] = ["<=", membership.removed_on]

	rows = frappe.get_all(
		"Connect Message Reaction",
		filters=filters,
		fields=["message", "emoji", "user"],
		order_by="creation asc",
		limit_page_length=0,
	)
	full_names = {
		u.name: u.full_name
		for u in frappe.get_all(
			"User", filters={"name": ["in", list({r.user for r in rows})]}, fields=["name", "full_name"]
		)
	}
	for row in rows:
		row["full_name"] = full_names.get(row.user)
	return rows


@frappe.whitelist()
def toggle_reaction(message, is_dm, emoji):
	"""Adds the caller's reaction to a message, or removes it if they already reacted with that emoji.
	Reacting is posting, so it needs the same write access as sending a message."""
	user = frappe.session.user
	is_dm = frappe.utils.cint(is_dm)
	emoji = (emoji or "").strip()
	if not emoji or len(emoji) > MAX_EMOJI_LENGTH:
		frappe.throw(frappe._("Pick an emoji to react with"))

	thread = frappe.db.get_value(
		"Connect DM Message" if is_dm else "Connect Message", message, "dm_thread" if is_dm else "thread"
	)
	if not thread:
		frappe.throw(frappe._("Message not found"))

	if is_dm:
		_dm_thread_pair(thread, user)
	else:
		_check_can_write(thread, user)

	# The emoji is compared here, not in the query: the database's default collation treats different
	# emoji as equal, so filtering on it would match (and delete) the wrong reaction.
	mine = frappe.get_all(
		"Connect Message Reaction",
		filters={"message": message, "is_dm": is_dm, "user": user},
		fields=["name", "emoji"],
	)
	existing = next((r.name for r in mine if r.emoji == emoji), None)
	if existing:
		frappe.delete_doc("Connect Message Reaction", existing, ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "Connect Message Reaction",
				"thread": thread,
				"message": message,
				"is_dm": is_dm,
				"user": user,
				"emoji": emoji,
			}
		).insert(ignore_permissions=True)

	notify_reaction_changed(thread, is_dm, user)
	return {"thread": thread, "added": not existing}


@frappe.whitelist()
def search_messages(query, thread=None, is_dm=0, kind="messages"):
	"""Search over the conversations the caller can read, newest first. `kind` picks the tab: "messages"
	matches text, "files" matches attachment names, "links" matches text that contains a URL. Pass `thread`
	(and `is_dm`) to search inside one conversation, otherwise it searches every company thread and DM.
	Visibility (thread membership, and a removed member's cut-off) comes from the doctypes' permission
	query conditions, so the search can't surface anything the message list itself wouldn't."""
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
