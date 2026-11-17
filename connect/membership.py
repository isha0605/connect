import frappe
from frappe import _
from frappe.utils import now_datetime

OWNER, ADMIN, MEMBER = "Owner", "Admin", "Member"
# Who runs the company: its team, profile and settings. Only the Owner changes who is in this group.
FULL_ACCESS = (OWNER, ADMIN)


class CompanyMembership:
	"""The rules a partner firm's and a customer company's team rows share. A company has one
	Owner. Only the Owner makes, changes or removes an Admin, or hands the company over. An Admin
	manages everyone else."""

	COMPANY_FIELD: str
	COMPANY_DOCTYPE: str
	SIDE: str
	ACCESS_LEVELS: tuple[str, ...]

	def get_access_of(self, user: str) -> str | None:
		"""The user's access at this row's company, or None when they don't act for it."""
		raise NotImplementedError

	@property
	def access_level(self) -> str:
		return self.access or MEMBER

	def validate_owner(self):
		self._keep_the_owner()
		self._allow_one_owner()

	def set_access_level(self, level: str, changed_by: str):
		"""Gives this person a new access level. Making them Owner hands them the company, and the
		old Owner becomes an Admin."""
		if level not in self.ACCESS_LEVELS:
			frappe.throw(_("Pick one of: {0}").format(", ".join(self.ACCESS_LEVELS)))
		if self.is_removed:
			frappe.throw(_("{0} has left the team").format(self.user))
		self._check_can_change(level, changed_by)
		if level == self.access:
			return

		if level == OWNER:
			self._take_over_from_owner()
		self.access = level
		self.save(ignore_permissions=True)

	def remove(self, removed_by: str):
		"""Removes this person from the company roster, revoking their thread access but leaving
		their past messages untouched."""
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
		self._leave_threads(removed_by)

	def _check_can_change(self, level: str, changed_by: str):
		access = self.get_access_of(changed_by)
		if access not in FULL_ACCESS:
			frappe.throw(_("Only the Owner or an Admin can change the team"), frappe.PermissionError)
		if {level, self.access} & set(FULL_ACCESS) and access != OWNER:
			frappe.throw(_("Only the Owner can change an Admin or the Owner"), frappe.PermissionError)

	def _keep_the_owner(self):
		"""The Owner stays until they hand the company to someone: its chats and requests go to them."""
		before = self.get_doc_before_save()
		was_owner = bool(before and before.access == OWNER and not before.is_removed)
		is_owner = self.access == OWNER and not self.is_removed
		if was_owner and not is_owner and not self.flags.is_ownership_transfer:
			frappe.throw(_("Transfer ownership to someone else first. A company needs an Owner."))

	def _allow_one_owner(self):
		if self.access != OWNER or self.is_removed:
			return

		# Locks the company, so two saves at the same time can't both make an Owner.
		frappe.db.get_value(self.COMPANY_DOCTYPE, self.get(self.COMPANY_FIELD), "name", for_update=True)
		if frappe.db.exists(
			self.doctype,
			{
				self.COMPANY_FIELD: self.get(self.COMPANY_FIELD),
				"access": OWNER,
				"is_removed": 0,
				"name": ["!=", self.name],
			},
		):
			frappe.throw(_("This company already has an Owner. Transfer ownership instead."))

	def _take_over_from_owner(self):
		"""The current Owner steps down to Admin, so the company still has one Owner after this save."""
		owner = frappe.db.get_value(
			self.doctype, {self.COMPANY_FIELD: self.get(self.COMPANY_FIELD), "access": OWNER, "is_removed": 0}
		)
		if not owner:
			return

		owner_doc = frappe.get_doc(self.doctype, owner)
		owner_doc.access = ADMIN
		owner_doc.flags.is_ownership_transfer = True
		owner_doc.save(ignore_permissions=True)

	def _leave_threads(self, removed_by: str):
		for row in frappe.get_all(
			"Connect Thread Member",
			filters={"user": self.user, "side": self.SIDE, "is_removed": 0},
			fields=["name", "thread"],
		):
			frappe.get_doc("Connect Thread", row.thread).remove_member(row.name, removed_by)
