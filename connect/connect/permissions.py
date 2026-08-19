import frappe


def _has_full_access(user):
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _is_customer_admin(customer, user):
	return bool(
		frappe.db.exists("Customer Team Member", {"parent": customer, "user": user, "is_admin": 1})
	)


def _is_partner_admin(partner, user):
	return bool(
		frappe.db.exists("Connect Partner Member", {"partner": partner, "user": user, "is_admin": 1})
	)


def _thread_membership(thread, user):
	return frappe.db.get_value(
		"Connect Thread Member",
		{"thread": thread, "user": user},
		["permission", "is_removed", "removed_on"],
		as_dict=True,
	)


def has_thread_permission(doc, ptype="read", user=None, **kwargs):
	"""Controllers can only deny access on top of the 'All' role baseline, never grant it."""
	user = user or frappe.session.user
	if _has_full_access(user):
		return True

	if not doc.get("customer") or not doc.get("partner"):
		# form not filled in yet (e.g. opening a blank "New Connect Thread")
		return True

	if ptype == "create":
		return bool(
			frappe.db.exists("Customer Team Member", {"parent": doc.customer, "user": user})
			or frappe.db.exists("Connect Partner Member", {"partner": doc.partner, "user": user})
		)

	membership = _thread_membership(doc.name, user)
	if not membership:
		return False

	if ptype == "read":
		return True

	# any other write (e.g. closing the thread) is partner-admin only, per spec
	return not membership.is_removed and _is_partner_admin(doc.partner, user)


def get_thread_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	user = frappe.db.escape(user)
	return f"""`tabConnect Thread`.name in (
		select thread from `tabConnect Thread Member` where user = {user}
	)"""


def has_message_permission(doc, ptype="read", user=None, **kwargs):
	user = user or frappe.session.user
	if _has_full_access(user):
		return True

	if not doc.get("thread"):
		return True

	membership = _thread_membership(doc.thread, user)
	if not membership:
		return False

	if ptype in ("write", "create", "delete", "submit", "cancel"):
		if membership.is_removed or membership.permission != "Write":
			return False
		if ptype == "create":
			# Beyond thread membership, a message you're creating must actually be
			# *yours* — api.send_message always sets sender=session user, but that's
			# just app-layer convention; without this, the raw doctype API (create=1
			# is granted to every Connect Customer/Partner role) would let any Write
			# member insert a message with someone else's email as sender, or with
			# message_type="System" to forge an authoritative-looking system notice.
			if doc.get("sender") != user or doc.get("message_type") == "System":
				return False
		return True

	# removed members keep a frozen view up to the moment they were removed
	if not membership.is_removed:
		return True
	return bool(doc.get("creation")) and doc.creation <= membership.removed_on


def get_message_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	escaped_user = frappe.db.escape(user)
	return f"""exists (
		select 1 from `tabConnect Thread Member` ctm
		where ctm.thread = `tabConnect Message`.thread
		and ctm.user = {escaped_user}
		and (ctm.is_removed = 0 or `tabConnect Message`.creation <= ctm.removed_on)
	)"""


def has_thread_member_permission(doc, ptype="read", user=None, **kwargs):
	user = user or frappe.session.user
	if _has_full_access(user):
		return True

	if not doc.get("thread") or not doc.get("side"):
		return True

	thread = frappe.db.get_value("Connect Thread", doc.thread, ["customer", "partner"], as_dict=True)
	if not thread:
		return False

	if ptype in ("create", "write", "delete"):
		# adding/removing members is admin-only, scoped to their own side's roster
		if doc.side == "Customer":
			return _is_customer_admin(thread.customer, user)
		if doc.side == "Partner":
			return _is_partner_admin(thread.partner, user)
		return False

	# read: any active member of the same thread can see the roster
	return bool(_thread_membership(doc.thread, user))


def get_thread_member_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	user = frappe.db.escape(user)
	return f"""`tabConnect Thread Member`.thread in (
		select thread from `tabConnect Thread Member` where user = {user}
	)"""


def has_dm_thread_permission(doc, ptype="read", user=None, **kwargs):
	"""A DM thread has exactly two fixed participants (no add/remove, unlike company threads)
	— either one can always read/write it, and starting one is always self-initiated (the
	caller is always one of the two parties), so create is unconditionally allowed here."""
	user = user or frappe.session.user
	if _has_full_access(user):
		return True
	if ptype == "create" or not doc.get("user_a") or not doc.get("user_b"):
		return True
	return user in (doc.user_a, doc.user_b)


def get_dm_thread_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	user = frappe.db.escape(user)
	return f"(`tabConnect DM Thread`.user_a = {user} or `tabConnect DM Thread`.user_b = {user})"


def has_dm_message_permission(doc, ptype="read", user=None, **kwargs):
	user = user or frappe.session.user
	if _has_full_access(user):
		return True
	if ptype == "create":
		return doc.get("sender") == user

	thread = frappe.db.get_value("Connect DM Thread", doc.get("dm_thread"), ["user_a", "user_b"], as_dict=True)
	if not thread or user not in (thread.user_a, thread.user_b):
		return False
	if ptype in ("write", "delete"):
		return doc.get("sender") == user
	return True


def get_dm_message_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	user = frappe.db.escape(user)
	return f"""`tabConnect DM Message`.dm_thread in (
		select name from `tabConnect DM Thread` where user_a = {user} or user_b = {user}
	)"""


def _is_customer_member(user):
	return bool(frappe.db.exists("Customer Team Member", {"user": user}))


def _is_partner_member(user):
	return bool(frappe.db.exists("Connect Partner Member", {"user": user}))


def has_message_template_permission(doc, ptype="read", user=None, **kwargs):
	"""Global templates: read-only for any member on the matching side; the 'All' role baseline
	already grants full CRUD (same pattern as elsewhere in this file), so this hook is what
	actually restricts create/write/delete on globals to platform admins. Personal templates
	(is_global=0) are owner-only for every operation — never visible to teammates or the other
	side, per spec."""
	user = user or frappe.session.user
	if _has_full_access(user):
		return True

	if doc.get("is_global"):
		if ptype in ("write", "create", "delete", "submit", "cancel"):
			return False
		if doc.get("side") == "Customer":
			return _is_customer_member(user)
		if doc.get("side") == "Partner":
			return _is_partner_member(user)
		return False

	# personal template: creating one is only allowed for your own side; every other
	# operation (read/write/delete) is owner-only
	if ptype == "create":
		if doc.get("side") == "Customer":
			return _is_customer_member(user)
		if doc.get("side") == "Partner":
			return _is_partner_member(user)
		return False

	return doc.get("owner") == user


def get_message_template_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	conditions = [f"`tabConnect Message Template`.owner = {frappe.db.escape(user)}"]
	if _is_customer_member(user):
		conditions.append(
			"(`tabConnect Message Template`.is_global = 1 and `tabConnect Message Template`.side = 'Customer')"
		)
	if _is_partner_member(user):
		conditions.append(
			"(`tabConnect Message Template`.is_global = 1 and `tabConnect Message Template`.side = 'Partner')"
		)
	return "(" + " or ".join(conditions) + ")"


def has_studio_page_permission(doc, ptype="read", user=None, **kwargs):
	"""Lets any logged-in user load our published 'connect' app pages (e.g. the messaging
	page) without granting System Manager / Studio User access to Studio Page in general.
	Guests only get pages explicitly marked allow_guest."""
	user = user or frappe.session.user
	if _has_full_access(user):
		return True
	if ptype != "read":
		return False
	if not (doc.get("studio_app") == "connect" and bool(doc.get("published"))):
		return False
	if user == "Guest":
		return bool(doc.get("allow_guest"))
	return True


def get_studio_page_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	base = "`tabStudio Page`.studio_app = 'connect' and `tabStudio Page`.published = 1"
	if user == "Guest":
		return base + " and `tabStudio Page`.allow_guest = 1"
	return base
