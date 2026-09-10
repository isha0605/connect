import frappe
from frappe import _
from frappe.utils import now_datetime

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
	from connect.customer.doctype.requirement.requirement import get_requirement_snapshot
	return get_requirement_snapshot()


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
		fields=[
			"name", "customer", "partner", "status", "creation",
			"last_message_at", "last_message_preview", "last_message_sender",
		],
		order_by="last_message_at desc, creation desc",
		limit_page_length=100,
	)
	if not threads:
		return []

	memberships = {
		m.thread: m
		for m in frappe.get_all(
			"Connect Thread Member",
			filters={"thread": ["in", [t.name for t in threads]], "user": user},
			fields=["thread", "last_read_at", "is_removed", "removed_on"],
		)
	}
	partner_logos = {
		p.name: p.logo
		for p in frappe.get_all(
			"Partner", filters={"name": ["in", [t.partner for t in threads]]}, fields=["name", "logo"]
		)
	}

	result = []
	for t in threads:
		membership = memberships.get(t.name, {})

		message_filters = [["thread", "=", t.name], ["sender", "!=", user]]
		if membership.get("is_removed") and membership.get("removed_on"):
			message_filters.append(["creation", "<=", membership["removed_on"]])
		if membership.get("last_read_at"):
			message_filters.append(["creation", ">", membership["last_read_at"]])
		unread_count = frappe.db.count("Connect Message", filters=message_filters)

		result.append({
			"name": t.name,
			"customer": t.customer,
			"partner": t.partner,
			"partner_logo": partner_logos.get(t.partner),
			"status": t.status,
			"creation": t.creation,
			"last_message": t.last_message_preview or "",
			"last_message_at": t.last_message_at or t.creation,
			"last_message_sender": t.last_message_sender,
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
