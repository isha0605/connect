# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from connect.membership import ADMIN, MEMBER, OWNER, CompanyMembership

# What a person can do at their partner firm. A firm has exactly one Owner (see CompanyMembership).
SALES, FINANCE = "Sales", "Finance"
ACCESS_LEVELS = (OWNER, ADMIN, SALES, FINANCE, MEMBER)
# Who opens the Leads page, and so who a lead can be assigned to.
LEAD_ACCESS = (OWNER, ADMIN, SALES)
# Who opens the Customers page. A Member does neither: their work is in Messages.
CUSTOMER_ACCESS = (OWNER, ADMIN, SALES, FINANCE)


def access_level_of(row) -> str:
	"""Owner, Admin, Sales, Finance or Member, from a member row or a dict with `access`."""
	return row.get("access") or MEMBER


def get_current_membership(user: str) -> frappe._dict | None:
	"""The user's active membership in the partner they work for now (see pick_current), or None
	when they are on no partner's team. Every partner page and check reads the partner and access
	level from this row, so a person in two firms sees one firm at a time."""
	memberships, chosen = _memberships(user)
	row = pick_current(memberships, chosen)
	return frappe._dict(row) if row else None


def get_active_memberships(user: str) -> list[frappe._dict]:
	"""The user's active memberships, newest first."""
	return [frappe._dict(row) for row in _memberships(user)[0]]


def get_current_partners(users: list[str]) -> dict[str, str]:
	"""{user: the partner they work for now} for many users in two queries. Users on no partner's
	team are left out."""
	if not users:
		return {}
	memberships = frappe.get_all(
		"Connect Partner Member",
		filters={"user": ["in", users], "is_removed": 0},
		fields=["user", "partner"],
		order_by="creation desc",
	)
	chosen = dict(
		frappe.get_all(
			"Connect User Settings", filters={"name": ["in", users]}, fields=["name", "current_partner"], as_list=True
		)
	)
	by_user = {}
	for row in memberships:
		by_user.setdefault(row.user, []).append(row)
	return {user: pick_current(rows, chosen.get(user)).partner for user, rows in by_user.items()}


def pick_current(memberships: list, chosen: str | None):
	"""The membership the user works for now: the partner they switched to, else their newest
	membership, which is the one Connect used before people could switch. None if there is none."""
	return next((row for row in memberships if row.partner == chosen), memberships[0] if memberships else None)


def list_my_partners(user: str) -> list[dict]:
	"""The partner firms the user is on the team of, by name, for the company switcher."""
	member = frappe.qb.DocType("Connect Partner Member")
	partner = frappe.qb.DocType("Partner")
	rows = (
		frappe.qb.from_(member)
		.join(partner)
		.on(partner.name == member.partner)
		.select(member.partner, partner.company_name, partner.logo, member.access)
		.where((member.user == user) & (member.is_removed == 0))
		.orderby(member.creation, order=frappe.qb.desc)
	).run(as_dict=True)
	current = pick_current(rows, frappe.db.get_value("Connect User Settings", user, "current_partner"))
	firms = [
		{
			"partner": row.partner,
			"company_name": row.company_name,
			"logo": row.logo,
			"access_level": access_level_of(row),
			"is_current": row is current,
		}
		for row in rows
	]
	return sorted(firms, key=lambda firm: (firm["company_name"] or "").lower())


def switch_partner(user: str, partner: str) -> None:
	"""Makes `partner` the firm the user works for now. Only a firm they are an active member of."""
	from connect.messaging.doctype.connect_user_settings.connect_user_settings import set_current_partner

	if not any(row.partner == partner for row in get_active_memberships(user)):
		frappe.throw(_("You are not on the team of {0}.").format(partner), frappe.PermissionError)
	set_current_partner(user, partner)


def _memberships(user: str) -> tuple[list, str | None]:
	"""The user's active memberships, newest first, and the partner they chose."""
	memberships = frappe.get_all(
		"Connect Partner Member",
		filters={"user": user, "is_removed": 0},
		fields=["name", "partner", "access"],
		order_by="creation desc",
	)
	return memberships, frappe.db.get_value("Connect User Settings", user, "current_partner")


class ConnectPartnerMember(CompanyMembership, Document):
	COMPANY_FIELD = "partner"
	COMPANY_DOCTYPE = "Partner"
	SIDE = "Partner"
	ACCESS_LEVELS = ACCESS_LEVELS

	def validate(self):
		if frappe.db.exists(
			"Connect Partner Member",
			{"partner": self.partner, "user": self.user, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} is already a member of {1}").format(self.user, self.partner))

		self.validate_owner()

	def check_can_invite(self, invited_by: str):
		from connect.partner.doctype.partner.partner import check_partner_is_approved

		check_partner_is_approved(self.partner)
		super().check_can_invite(invited_by)

	def get_access_of(self, user: str) -> str | None:
		"""Someone who works for two firms acts for one at a time, so they act here only while
		this firm is the one they work for now."""
		from connect.permissions import _current_access_at

		return _current_access_at(self.partner, user)

	def on_update(self):
		if self.is_new() or self.has_value_changed("access") or self.has_value_changed("is_removed"):
			set_owner_on_partner(self.partner)
		if self.is_new() or self.has_value_changed("is_removed"):
			set_login_from_partners(self.user)

	def on_trash(self):
		if self.access == OWNER:
			# The row is still in the table now, so the partner is left with no Owner.
			frappe.db.set_value(
				"Partner", self.partner, {"partner_name": None, "owner_email": None}, update_modified=False
			)


def set_owner_on_partner(partner: str) -> None:
	"""Keeps Partner.partner_name and owner_email the full name and login of the partner's one Owner,
	like frappe.io's Partner Name and User. Set without saving the Partner, so its own save hooks
	(CRM sync) don't run for it."""
	owner = frappe.db.get_value("Connect Partner Member", {"partner": partner, "access": OWNER, "is_removed": 0}, "user")
	full_name = frappe.db.get_value("User", owner, "full_name") if owner else None
	frappe.db.set_value(
		"Partner", partner, {"partner_name": full_name, "owner_email": owner}, update_modified=False
	)


def set_member_logins(partner: str) -> None:
	"""Partner on_update: disabling a partner turns off its team's logins, as on frappe.io, and
	enabling it turns them back on."""
	for user in frappe.get_all("Connect Partner Member", filters={"partner": partner, "is_removed": 0}, pluck="user"):
		set_login_from_partners(user)


def set_login_from_partners(user: str) -> None:
	"""A person on partner teams can log in while at least one of those partners is enabled. A person
	on no team is left as they are. Frappe staff (System Users) are never changed."""
	member = frappe.qb.DocType("Connect Partner Member")
	partner = frappe.qb.DocType("Partner")
	partners_enabled = (
		frappe.qb.from_(member)
		.join(partner)
		.on(partner.name == member.partner)
		.select(partner.enabled)
		.where((member.user == user) & (member.is_removed == 0))
	).run(pluck=True)
	if not partners_enabled:
		return

	user_doc = frappe.get_doc("User", user)
	enabled = int(any(partners_enabled))
	if user_doc.user_type == "System User" or user_doc.enabled == enabled:
		return
	user_doc.enabled = enabled
	# Follows the partner's status, set by Frappe staff or the import, not by the user themselves.
	user_doc.save(ignore_permissions=True)


def update_owner_name_from_user(doc, method=None) -> None:
	"""User on_update: a renamed Owner's new name shows on each partner they own."""
	if not doc.has_value_changed("full_name"):
		return
	for partner in frappe.get_all(
		"Connect Partner Member", filters={"user": doc.name, "access": OWNER, "is_removed": 0}, pluck="partner"
	):
		set_owner_on_partner(partner)
