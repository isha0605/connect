import frappe
from frappe import _
from frappe.utils import now_datetime

from connect.api import _get_customer_for_user
from connect.permissions import _check_can_read, _get_partner_admin


@frappe.whitelist()
def add_thread_member(thread, email, side, permission="Write"):
	# adding member to chat
	thread_doc = frappe.get_doc("Connect Thread", thread)
	member, created_user = thread_doc.add_member(email, side, permission, frappe.session.user)
	return {"member": member.name, "created_user": created_user}


@frappe.whitelist()
def remove_thread_member(thread, member):
	# removing member from chat
	thread_doc = frappe.get_doc("Connect Thread", thread)
	member_doc = thread_doc.remove_member(member, frappe.session.user)
	return {"removed": member_doc.user}


@frappe.whitelist()
def close_thread(thread):
	# closing the chat thread
	thread_doc = frappe.get_doc("Connect Thread", thread)
	thread_doc.close(frappe.session.user)
	return {"status": thread_doc.status}


@frappe.whitelist()
def get_requirement_snapshot():
	"""Returns the caller's saved Requirement as a dict, to seed a draft Requirement card in a new thread."""
	user = frappe.session.user
	customer = _get_customer_for_user(user)
	if not customer:
		return None

	requirement = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if not requirement:
		return None

	req = frappe.get_doc("Requirement", requirement)
	return {
		"company_name": req.company_name,
		"country": req.country,
		"industry": req.industry,
		"apps": [a.app for a in req.apps],
		"looking_for": req.looking_for,
		"company_size": req.company_size,
		"current_situation": req.current_situation,
		"timeline": req.timeline,
		"delivery_preference": req.delivery_preference,
		"budget": req.budget,
	}


@frappe.whitelist()
def make_thread_admin(thread, member):
	"""Admin-transfer logic lives on Connect Thread Member's make_admin()."""
	member_doc = frappe.get_doc("Connect Thread Member", member)
	if member_doc.thread != thread:
		frappe.throw(_("Member does not belong to this thread"))
	member_doc.make_admin(frappe.session.user)
	return {"new_admin": member_doc.user}


@frappe.whitelist()
def get_thread_admins(thread):
	"""Returns the two companies' admin emails, to show an Admin badge and gate per-member actions."""
	user = frappe.session.user
	_check_can_read(thread, user)

	thread_doc = frappe.db.get_value("Connect Thread", thread, ["customer", "partner"], as_dict=True)
	if not thread_doc:
		frappe.throw(_("Thread not found"))

	partner_admin = _get_partner_admin(thread_doc.partner)
	customer_admin = frappe.db.get_value(
		"Customer Team Member", {"customer": thread_doc.customer, "is_admin": 1}, "user"
	)
	return {"partner_admin": partner_admin, "customer_admin": customer_admin}


@frappe.whitelist()
def get_thread_member_profiles(thread):
	"""Returns name and photo for everyone who's ever been a thread member, for the sender hover card in chat."""
	user = frappe.session.user
	_check_can_read(thread, user)

	emails = frappe.get_list("Connect Thread Member", filters={"thread": thread}, pluck="user", distinct=True)
	if not emails:
		return []
	return frappe.get_list(
		"User", filters={"name": ["in", emails]}, fields=["name", "full_name", "user_image"]
	)


@frappe.whitelist()
def get_my_threads():
	"""Returns the sidebar thread list with a last-message preview and unread count, scoped to what the caller can still see."""
	user = frappe.session.user
	threads = frappe.get_list(
		"Connect Thread",
		fields=["name", "customer", "partner", "status", "creation"],
		order_by="modified desc",
		limit_page_length=100,
	)

	result = []
	for t in threads:
		membership = frappe.db.get_value(
			"Connect Thread Member",
			{"thread": t.name, "user": user},
			["last_read_at", "is_removed", "removed_on"],
			as_dict=True,
		) or {}

		message_filters = [["thread", "=", t.name]]
		if membership.get("is_removed") and membership.get("removed_on"):
			message_filters.append(["creation", "<=", membership["removed_on"]])

		last = frappe.get_list(
			"Connect Message",
			filters=message_filters,
			fields=["content", "message_type", "file_name", "creation", "sender"],
			order_by="creation desc",
			limit_page_length=1,
		)
		if last:
			m = last[0]
			if m.message_type == "File":
				preview = "📎 " + (m.file_name or _("Attachment"))
			elif m.message_type == "Requirement":
				preview = _("Requirement details")
			else:
				preview = m.content or ""
			last_message_at = m.creation
			last_message_sender = m.sender
		else:
			preview = ""
			last_message_at = t.creation
			last_message_sender = None

		unread_filters = message_filters + [["sender", "!=", user]]
		if membership.get("last_read_at"):
			unread_filters.append(["creation", ">", membership["last_read_at"]])
		unread_count = frappe.db.count("Connect Message", filters=unread_filters)

		result.append({
			"name": t.name,
			"customer": t.customer,
			"partner": t.partner,
			"status": t.status,
			"creation": t.creation,
			"last_message": preview[:140],
			"last_message_at": last_message_at,
			"last_message_sender": last_message_sender,
			"unread_count": unread_count,
		})

	return result


@frappe.whitelist()
def mark_thread_read(thread):
	"""Clears the caller's unread badge by bumping their own last-read time; silently does nothing if their membership is stale."""
	frappe.db.set_value(
		"Connect Thread Member",
		{"thread": thread, "user": frappe.session.user, "is_removed": 0},
		"last_read_at",
		now_datetime(),
	)
