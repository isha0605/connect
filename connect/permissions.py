import functools
from pathlib import Path

import frappe


def _has_full_access(user):
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _is_customer_admin(customer, user):
	return bool(
		frappe.db.exists("Customer Team Member", {"customer": customer, "user": user, "is_admin": 1})
	)


def _is_partner_admin(partner, user):
	return bool(
		frappe.db.exists("Connect Partner Member", {"partner": partner, "user": user, "is_admin": 1})
	)


def _get_partner_owners(partner) -> list[str]:
	"""The partner's active owners (admins), earliest first. A partner can have several."""
	return frappe.get_all(
		"Connect Partner Member",
		filters={"partner": partner, "is_admin": 1, "is_removed": 0},
		order_by="creation asc",
		pluck="user",
	)


def _my_partner_with_access(user, levels):
	"""The partner the user is on the team of, if their access level is one of `levels`
	(connect_partner_member.LEAD_ACCESS, say); else a PermissionError."""
	from frappe import _

	from connect.partner.doctype.connect_partner_member.connect_partner_member import access_level_of

	row = frappe.db.get_value(
		"Connect Partner Member", {"user": user, "is_removed": 0}, ["partner", "is_admin", "access"], as_dict=True
	)
	if not row:
		frappe.throw(_("Only a partner's team can see this."), frappe.PermissionError)
	if access_level_of(row) not in levels:
		frappe.throw(_("Your access doesn't include this page. Ask an owner of your firm."), frappe.PermissionError)
	return row.partner


def _has_partner_access(partner, user, levels) -> bool:
	"""Whether the user is an active member of the partner with one of these access levels."""
	from connect.partner.doctype.connect_partner_member.connect_partner_member import access_level_of

	row = frappe.db.get_value(
		"Connect Partner Member",
		{"partner": partner, "user": user, "is_removed": 0},
		["is_admin", "access"],
		as_dict=True,
	)
	return bool(row) and access_level_of(row) in levels


def _is_partner_reviewer(user):
	return "Partner Reviewer" in frappe.get_roles(user)


def _my_company_membership(user):
	"""Returns which company (and doctype/row) this user belongs to, or Nones if neither. Someone
	removed from a team no longer belongs to it."""
	customer_row = frappe.db.get_value(
		"Customer Team Member", {"user": user, "is_removed": 0}, ["name", "customer", "is_admin"], as_dict=True
	)
	if customer_row:
		return "Customer Team Member", customer_row.customer, customer_row
	partner_row = frappe.db.get_value(
		"Connect Partner Member", {"user": user, "is_removed": 0}, ["name", "partner", "is_admin"], as_dict=True
	)
	if partner_row:
		return "Connect Partner Member", partner_row.partner, partner_row
	return None, None, None


def _my_side(user):
	"""Which side (Customer/Partner) this user belongs to, or None if neither."""
	doctype, _company, _row = _my_company_membership(user)
	if doctype == "Customer Team Member":
		return "Customer"
	if doctype == "Connect Partner Member":
		return "Partner"
	return None


def _thread_membership(thread, user):
	return frappe.db.get_value(
		"Connect Thread Member",
		{"thread": thread, "user": user},
		["permission", "is_removed", "removed_on"],
		as_dict=True,
	)


def _check_can_write(thread, user):
	from frappe import _

	if _has_full_access(user):
		return
	membership = _thread_membership(thread, user)
	if not membership or membership.is_removed or membership.permission != "Write":
		frappe.throw(_("You don't have permission to post in this thread"), frappe.PermissionError)
	if frappe.db.get_value("Connect Thread", thread, "status") == "Closed":
		frappe.throw(_("This thread is closed"))


def _visible_message_filters(thread, user):
	"""Filters for the thread's messages a member may read: a removed member's stop at their removal."""
	filters = {"thread": thread}
	membership = _thread_membership(thread, user)
	if membership and membership.is_removed:
		filters["creation"] = ["<=", membership.removed_on]
	return filters


def _check_can_read(thread, user):
	from frappe import _

	if _has_full_access(user):
		return
	if not _thread_membership(thread, user):
		frappe.throw(_("You don't have access to this thread"), frappe.PermissionError)


def _dm_thread_pair_or_none(thread, user):
	pair = frappe.db.get_value("Connect DM Thread", thread, ["user_a", "user_b"], as_dict=True)
	if not pair or user not in (pair.user_a, pair.user_b):
		return None
	return pair


def _dm_thread_pair(thread, user):
	from frappe import _

	pair = _dm_thread_pair_or_none(thread, user)
	if not pair:
		frappe.throw(_("You don't have access to this conversation"), frappe.PermissionError)
	return pair


def has_partner_crm_settings_permission(doc, ptype="read", user=None, **kwargs):
	"""Controllers can only deny access on top of the 'Connect Partner' role baseline, never grant it."""
	user = user or frappe.session.user
	if _has_full_access(user):
		return True
	return _is_partner_admin(doc.partner, user)


def get_partner_crm_settings_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	user = frappe.db.escape(user)
	return f"""`tabPartner CRM Settings`.partner in (
		select partner from `tabConnect Partner Member` where user = {user} and is_admin = 1
	)"""


def has_partner_application_permission(doc, ptype="read", user=None, **kwargs):
	"""Controllers can only deny access on top of the 'Connect Partner' role baseline, never grant it."""
	user = user or frappe.session.user
	if _has_full_access(user) or _is_partner_reviewer(user):
		return True
	if not doc.get("partner"):
		return True
	return _is_partner_admin(doc.partner, user)


def get_partner_application_permission_query_conditions(user, doctype=None):
	if _has_full_access(user) or _is_partner_reviewer(user):
		return ""
	user = frappe.db.escape(user)
	return f"""`tabPartner Application`.partner in (
		select partner from `tabConnect Partner Member` where user = {user} and is_admin = 1
	)"""


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
			frappe.db.exists("Customer Team Member", {"customer": doc.customer, "user": user})
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
		if ptype in ("write", "create", "delete"):
			# Beyond thread membership, editing/deleting/creating a message requires it
			# be *yours* — api.send_message/edit_message/delete_message all operate as
			# the session user, but that's just app-layer convention; without this, the
			# raw doctype API (create/write/delete=1 is granted to every Connect
			# Customer/Partner role) would let any Write member touch anyone's message.
			if doc.get("sender") != user:
				return False
			if ptype == "create" and doc.get("message_type") == "System":
				return False
		return True

	if _is_anonymous_customer_row(doc.thread, user, doc.get("sender")):
		return False
	# removed members keep a frozen view up to the moment they were removed
	if not membership.is_removed:
		return True
	return bool(doc.get("creation")) and doc.creation <= membership.removed_on


def _is_anonymous_customer_row(thread, user, customer_user):
	"""A row that would tell the partner side who an anonymous customer is: the masked APIs in
	connect.api.threads serve it instead."""
	from connect.messaging.customer_identity import customer_users, hides_customer

	return hides_customer(thread, user) and customer_user in customer_users(thread)


def _anonymous_customer_sql(user, table, user_column):
	"""SQL that holds for a row of `table` whose `user_column` is the customer side of a thread
	where `user` writes for the partner and the customer is still anonymous."""
	return f"""exists (
		select 1 from `tabConnect Thread` anon_thread
		join `tabConnect Thread Member` anon_viewer
			on anon_viewer.thread = anon_thread.name and anon_viewer.user = {user} and anon_viewer.side = 'Partner'
		join `tabConnect Thread Member` anon_customer
			on anon_customer.thread = anon_thread.name and anon_customer.side = 'Customer'
		where anon_thread.name = `{table}`.thread
		and anon_thread.is_customer_revealed = 0
		and anon_customer.user = `{table}`.{user_column}
	)"""


def get_message_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	escaped_user = frappe.db.escape(user)
	return f"""exists (
		select 1 from `tabConnect Thread Member` ctm
		where ctm.thread = `tabConnect Message`.thread
		and ctm.user = {escaped_user}
		and (ctm.is_removed = 0 or `tabConnect Message`.creation <= ctm.removed_on)
	) and not {_anonymous_customer_sql(escaped_user, "tabConnect Message", "sender")}"""


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
	if doc.side == "Customer" and _is_anonymous_customer_row(doc.thread, user, doc.user):
		return False
	return bool(_thread_membership(doc.thread, user))


def get_thread_member_permission_query_conditions(user, doctype=None):
	if _has_full_access(user):
		return ""
	user = frappe.db.escape(user)
	return f"""`tabConnect Thread Member`.thread in (
		select thread from `tabConnect Thread Member` where user = {user}
	) and not {_anonymous_customer_sql(user, "tabConnect Thread Member", "user")}"""


def has_dm_thread_permission(doc, ptype="read", user=None, **kwargs):
	"""Lets either DM participant read/write it, since a DM has exactly two fixed participants."""
	user = user or frappe.session.user
	if _has_full_access(user):
		return True
	if not doc.get("user_a") or not doc.get("user_b"):
		return True
	# create included: nobody may open a DM between two other people
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
	# create included: the raw resource API must not post into someone else's DM
	if not _dm_thread_pair_or_none(doc.get("dm_thread"), user):
		return False
	if ptype in ("create", "write", "delete"):
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
	"""Restricts global templates to read-only per side, team templates to reading by the
	creator's company, and every edit of a personal or team template to its owner."""
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

	if ptype == "read" and doc.get("scope") == "Team" and doc.get("owner") != user:
		_doctype, company, _row = _my_company_membership(user)
		return bool(company) and company == doc.get("team") and _my_side(user) == doc.get("side")

	# personal/team template: creating one is only allowed for your own side (the controller pins
	# a team template to the creator's company); every other operation is owner-only
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
	side = _my_side(user)
	_doctype, company, _row = _my_company_membership(user)
	if side and company:
		conditions.append(
			"(`tabConnect Message Template`.scope = 'Team'"
			f" and `tabConnect Message Template`.side = {frappe.db.escape(side)}"
			f" and `tabConnect Message Template`.team = {frappe.db.escape(company)})"
		)
	return "(" + " or ".join(conditions) + ")"


def has_studio_page_permission(doc, ptype="read", user=None, **kwargs):
	"""Lets any logged-in user load connect's own published Studio pages, without granting broader Studio access."""
	user = user or frappe.session.user
	if _has_full_access(user):
		return True
	if ptype != "read":
		return True
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


def has_studio_component_permission(doc, ptype="read", user=None, **kwargs):
	"""Lets signed-in users load the components connect's pages render (the sidebar), and no others.
	Studio's renderer fetches them at runtime, so a page without them loses its sidebar."""
	user = user or frappe.session.user
	if _has_studio_access(user) or ptype != "read":
		return True
	return doc.name in get_connect_component_names()


def get_studio_component_permission_query_conditions(user, doctype=None):
	if _has_studio_access(user):
		return ""
	names = ", ".join(frappe.db.escape(name) for name in get_connect_component_names())
	return f"`tabStudio Component`.name in ({names})"


@functools.cache
def get_connect_component_names() -> tuple[str, ...]:
	"""connect's own components: one JSON file each, named after the component."""
	folder = Path(frappe.get_app_source_path("connect"), "studio", "connect", "studio_components")
	return tuple(sorted(path.stem for path in folder.glob("*.json")))


def _has_studio_access(user):
	return _has_full_access(user) or "Studio User" in frappe.get_roles(user)
