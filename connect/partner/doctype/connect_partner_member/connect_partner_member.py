# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# What a person can do at their partner firm. Owner is `is_admin`; the rest are `access`.
OWNER, SALES, FINANCE, MEMBER = "Owner", "Sales", "Finance", "Member"
ACCESS_LEVELS = (OWNER, SALES, FINANCE, MEMBER)
# Who opens the Leads page, and so who a lead can be assigned to.
LEAD_ACCESS = (OWNER, SALES)
# Who opens the Customers page. A Member does neither: their work is in Messages.
CUSTOMER_ACCESS = (OWNER, SALES, FINANCE)


def access_level_of(row) -> str:
	"""Owner, Sales, Finance or Member, from a member row or a dict with is_admin and access."""
	return OWNER if row.get("is_admin") else (row.get("access") or MEMBER)


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
		.select(member.partner, partner.partner_name, partner.logo, member.is_admin, member.access)
		.where((member.user == user) & (member.is_removed == 0))
		.orderby(member.creation, order=frappe.qb.desc)
	).run(as_dict=True)
	current = pick_current(rows, frappe.db.get_value("Connect User Settings", user, "current_partner"))
	firms = [
		{
			"partner": row.partner,
			"partner_name": row.partner_name,
			"logo": row.logo,
			"access_level": access_level_of(row),
			"is_current": row is current,
		}
		for row in rows
	]
	return sorted(firms, key=lambda firm: (firm["partner_name"] or "").lower())


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
		fields=["name", "partner", "is_admin", "access"],
		order_by="creation desc",
	)
	return memberships, frappe.db.get_value("Connect User Settings", user, "current_partner")


class ConnectPartnerMember(Document):
	def validate(self):
		if frappe.db.exists(
			"Connect Partner Member",
			{"partner": self.partner, "user": self.user, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} is already a member of {1}").format(self.user, self.partner))

		self._keep_an_owner()

	def _keep_an_owner(self):
		"""A firm can have several owners, but never none: its chats and requests go to them."""
		before = self.get_doc_before_save()
		was_owner = bool(before and before.is_admin and not before.is_removed)
		if not was_owner or (self.is_admin and not self.is_removed):
			return

		if not frappe.db.exists(
			"Connect Partner Member",
			{"partner": self.partner, "is_admin": 1, "is_removed": 0, "name": ["!=", self.name]},
		):
			frappe.throw(_("Make someone else an owner first. A firm needs at least one owner."))

	@property
	def access_level(self) -> str:
		return access_level_of(self)

	def set_access_level(self, level: str, changed_by: str):
		"""Makes this person an owner, or gives them Sales, Finance or Member access."""
		from connect.permissions import _is_partner_admin

		if not _is_partner_admin(self.partner, changed_by):
			frappe.throw(_("Only an owner can change what people can do"), frappe.PermissionError)
		if level not in ACCESS_LEVELS:
			frappe.throw(_("Pick Owner, Sales, Finance or Member"))
		if self.is_removed:
			frappe.throw(_("{0} has left the team").format(self.user))

		self.is_admin = int(level == OWNER)
		if level != OWNER:
			self.access = level
		self.save(ignore_permissions=True)

	def remove(self, removed_by):
		"""Removes this person from the company roster, revoking their thread access but leaving their past messages untouched."""
		from connect.permissions import _is_partner_admin

		if not _is_partner_admin(self.partner, removed_by):
			frappe.throw(_("Only an admin can remove a team member"), frappe.PermissionError)
		if self.is_removed:
			frappe.throw(_("{0} has already left").format(self.user))

		# A removed owner stops being one, so every `is_admin` check drops them too.
		self.is_removed = 1
		self.is_admin = 0
		self.removed_on = now_datetime()
		self.save(ignore_permissions=True)

		for row in frappe.get_all(
			"Connect Thread Member",
			filters={"user": self.user, "side": "Partner", "is_removed": 0},
			fields=["name", "thread"],
		):
			frappe.get_doc("Connect Thread", row.thread).remove_member(row.name, removed_by)
