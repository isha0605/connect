import frappe
from frappe import _
from frappe.utils import now_datetime

from connect.api.attachments import _attach_file_to_message, _claim_staged_attachment
from connect.api.messages import _get_message_preview
from connect.permissions import _dm_thread_pair, _dm_thread_pair_or_none


@frappe.whitelist()
def start_dm(user):
	"""Finds or creates the 1:1 DM thread with a user, storing participants in a fixed order so the pair is never duplicated."""
	me = frappe.session.user
	if user == me:
		frappe.throw(_("You can't start a conversation with yourself"))
	if not frappe.db.exists("User", user):
		frappe.throw(_("User not found"))

	user_a, user_b = sorted([me, user])

	existing = frappe.db.get_value("Connect DM Thread", {"user_a": user_a, "user_b": user_b}, "name")
	if existing:
		return existing

	doc = frappe.get_doc({"doctype": "Connect DM Thread", "user_a": user_a, "user_b": user_b})
	doc.insert()
	return doc.name


@frappe.whitelist()
def get_my_dm_threads():
	"""Returns the DM inbox for the sidebar, one row per person the caller has ever messaged."""
	user = frappe.session.user
	threads = frappe.get_list(
		"Connect DM Thread",
		or_filters=[["user_a", "=", user], ["user_b", "=", user]],
		fields=[
			"name", "user_a", "user_b", "last_read_at_a", "last_read_at_b", "creation",
			"last_message_at", "last_message_preview", "last_message_sender",
		],
		order_by="last_message_at desc, creation desc",
		limit_page_length=100,
	)
	if not threads:
		return []

	others = list({(t.user_b if t.user_a == user else t.user_a) for t in threads})
	profiles = {
		p.name: p
		for p in frappe.get_all("User", filters={"name": ["in", others]}, fields=["name", "full_name", "user_image"])
	}

	result = []
	for t in threads:
		other = t.user_b if t.user_a == user else t.user_a
		last_read_at = t.last_read_at_a if t.user_a == user else t.last_read_at_b
		profile = profiles.get(other, {})

		unread_filters = {"dm_thread": t.name, "sender": ["!=", user]}
		if last_read_at:
			unread_filters["creation"] = [">", last_read_at]
		unread_count = frappe.db.count("Connect DM Message", filters=unread_filters)

		result.append({
			"name": t.name,
			"other_user": other,
			"other_user_full_name": profile.get("full_name"),
			"other_user_image": profile.get("user_image"),
			"last_message": t.last_message_preview or "",
			"last_message_at": t.last_message_at or t.creation,
			"last_message_sender": t.last_message_sender,
			"unread_count": unread_count,
		})
	return result


@frappe.whitelist()
def mark_dm_thread_read(thread):
	"""Best-effort, mirrors mark_thread_read — a stale/foreign thread name is a silent no-op."""
	user = frappe.session.user
	pair = _dm_thread_pair_or_none(thread, user)
	if not pair:
		return
	field = "last_read_at_a" if pair.user_a == user else "last_read_at_b"
	frappe.db.set_value("Connect DM Thread", thread, field, now_datetime())


@frappe.whitelist()
def send_dm_message(thread, content="", file_url=None, file_name=None, file_type=None, file_size=None):
	"""Sends a DM text or file message, the DM counterpart to send_message."""
	user = frappe.session.user
	_dm_thread_pair(thread, user)

	content = (content or "").strip()
	if not content and not file_url:
		frappe.throw(_("Message cannot be empty"))

	file_doc_name = _claim_staged_attachment(file_url, user) if file_url else None

	doc = frappe.get_doc({
		"doctype": "Connect DM Message",
		"dm_thread": thread,
		"sender": user,
		"message_type": "File" if file_url else "Text",
		"content": content or file_name,
	})
	if file_url:
		doc.attachment = file_url
		doc.file_name = file_name
		doc.file_type = file_type
		doc.file_size = file_size
	doc.insert()

	if file_doc_name:
		_attach_file_to_message(file_doc_name, "Connect DM Message", doc.name)

	return doc.as_dict()


@frappe.whitelist()
def delete_dm_message(message):
	"""Deletes a DM for everyone; authorization and cleanup live in has_dm_message_permission and Connect DM Message's on_trash()."""
	frappe.delete_doc("Connect DM Message", message)


@frappe.whitelist()
def edit_dm_message(message, content):
	"""Edits your own DM in place; authorization and validation live in has_dm_message_permission and Connect DM Message's validate()."""
	doc = frappe.get_doc("Connect DM Message", message)
	doc.content = content
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def pin_dm_message(message):
	"""Resolves which thread a DM belongs to; pin/unpin logic itself lives on Connect DM Thread."""
	doc = frappe.get_doc("Connect DM Message", message)
	thread_doc = frappe.get_doc("Connect DM Thread", doc.dm_thread)
	thread_doc.pin(message, frappe.session.user)
	return {"thread": thread_doc.name, "pinned_message": thread_doc.pinned_message}


@frappe.whitelist()
def unpin_dm_message(thread):
	thread_doc = frappe.get_doc("Connect DM Thread", thread)
	thread_doc.unpin(frappe.session.user)
	return {"thread": thread_doc.name, "pinned_message": None}


@frappe.whitelist()
def get_pinned_dm_message(thread):
	_dm_thread_pair(thread, frappe.session.user)

	pinned = frappe.db.get_value("Connect DM Thread", thread, "pinned_message")
	if not pinned:
		return None
	return _get_message_preview("Connect DM Message", pinned)
