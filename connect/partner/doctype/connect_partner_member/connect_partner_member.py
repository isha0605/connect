# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# What a person can do at their partner firm. A firm has exactly one Owner.
OWNER, ADMIN, SALES, FINANCE, MEMBER = "Owner", "Admin", "Sales", "Finance", "Member"
ACCESS_LEVELS = (OWNER, ADMIN, SALES, FINANCE, MEMBER)
# Who runs the firm: its team, profile and settings. Only the Owner changes who is in this group.
FULL_ACCESS = (OWNER, ADMIN)
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
		.select(member.partner, partner.partner_name, partner.logo, member.access)
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
		fields=["name", "partner", "access"],
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

		self._keep_the_owner()
		self._allow_one_owner()

	def _keep_the_owner(self):
		"""The Owner stays until they hand the firm to someone: its chats and requests go to them."""
		before = self.get_doc_before_save()
		was_owner = bool(before and before.access == OWNER and not before.is_removed)
		is_owner = self.access == OWNER and not self.is_removed
		if was_owner and not is_owner and not self.flags.is_ownership_transfer:
			frappe.throw(_("Transfer ownership to someone else first. A firm needs an Owner."))

	def _allow_one_owner(self):
		if self.access != OWNER or self.is_removed:
			return

		# Locks the firm, so two saves at the same time can't both make an Owner.
		frappe.db.get_value("Partner", self.partner, "name", for_update=True)
		if frappe.db.exists(
			"Connect Partner Member",
			{"partner": self.partner, "access": OWNER, "is_removed": 0, "name": ["!=", self.name]},
		):
			frappe.throw(_("This firm already has an Owner. Transfer ownership instead."))

	@property
	def access_level(self) -> str:
		return access_level_of(self)

	def set_access_level(self, level: str, changed_by: str):
		"""Gives this person a new access level. Making them Owner hands them the firm, and the
		old Owner becomes an Admin."""
		if level not in ACCESS_LEVELS:
			frappe.throw(_("Pick Owner, Admin, Sales, Finance or Member"))
		if self.is_removed:
			frappe.throw(_("{0} has left the team").format(self.user))
		self._check_can_change(level, changed_by)
		if level == self.access:
			return

		if level == OWNER:
			self._take_over_from_owner()
		self.access = level
		self.save(ignore_permissions=True)

	def _check_can_change(self, level: str, changed_by: str):
		"""An Admin manages Sales, Finance and Members. Only the Owner makes, changes or removes an
		Admin, or hands over the firm."""
		from connect.permissions import _is_partner_admin, _is_partner_owner

		if not _is_partner_admin(self.partner, changed_by):
			frappe.throw(_("Only the Owner or an Admin can change the team"), frappe.PermissionError)
		if {level, self.access} & set(FULL_ACCESS) and not _is_partner_owner(self.partner, changed_by):
			frappe.throw(_("Only the Owner can change an Admin or the Owner"), frappe.PermissionError)

	def _take_over_from_owner(self):
		"""The current Owner steps down to Admin, so the firm still has one Owner after this save."""
		owner = frappe.db.get_value(
			"Connect Partner Member", {"partner": self.partner, "access": OWNER, "is_removed": 0}
		)
		if not owner:
			return

		owner_doc = frappe.get_doc("Connect Partner Member", owner)
		owner_doc.access = ADMIN
		owner_doc.flags.is_ownership_transfer = True
		owner_doc.save(ignore_permissions=True)

	def remove(self, removed_by):
		"""Removes this person from the company roster, revoking their thread access but leaving their past messages untouched."""
		if self.is_removed:
			frappe.throw(_("{0} has already left").format(self.user))
		self._check_can_change(MEMBER, removed_by)

		# A removed person keeps no access, so a check that skips `is_removed` still drops them.
		# The Owner can't be removed: `_keep_the_owner` asks them to transfer ownership first.
		self.is_removed = 1
		if self.access != OWNER:
			self.access = MEMBER
		self.removed_on = now_datetime()
		self.save(ignore_permissions=True)

		for row in frappe.get_all(
			"Connect Thread Member",
			filters={"user": self.user, "side": "Partner", "is_removed": 0},
			fields=["name", "thread"],
		):
			frappe.get_doc("Connect Thread", row.thread).remove_member(row.name, removed_by)
