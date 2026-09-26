# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from jinja2 import DebugUndefined, TemplateError, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

# The variables a template can use, e.g. "Hi {{ first_name }}". Kept in step with the page
# script's TEMPLATE_VARIABLES, which offers them after "{{" in the Response box.
TEMPLATE_VARIABLES = (
	"first_name",
	"full_name",
	"email",
	"company_name",
	"my_first_name",
	"my_full_name",
	"my_email",
	"my_company_name",
)

# Templates are written by customers and partners, so they're rendered in Jinja's sandbox with
# only the variables above, never through frappe.render_template, whose environment exposes
# frappe.db and friends. DebugUndefined leaves an unknown name visible as "{{ name }}" instead
# of silently dropping it.
_jinja = SandboxedEnvironment(undefined=DebugUndefined, autoescape=False)


class ConnectMessageTemplate(Document):
	def validate(self):
		# `scope` is the source of truth; `is_global` is kept for the existing ordering and seed data
		self.is_global = 1 if self.scope == "Global" else 0
		self.team = self._owner_company() if self.scope == "Team" else None
		try:
			_jinja.parse(self.content or "")
		except TemplateSyntaxError as e:
			frappe.throw(_("The response has a template error on line {0}: {1}").format(e.lineno, e.message))

	def _owner_company(self):
		"""A Team template is always shared with its creator's own company, never one they name."""
		from connect.permissions import _my_company_membership

		_doctype, company, _row = _my_company_membership(self.owner)
		if not company:
			frappe.throw(_("Only a member of a customer or partner company can create a team template"))
		return company

	def update_personal(self, title=None, content=None, scope=None):
		"""Edits a personal or team template; globals are edited via Desk's own save() instead, not this method."""
		if self.is_global:
			frappe.throw(_("Global templates can't be edited here"), frappe.PermissionError)
		if title is not None:
			self.title = title
		if content is not None:
			self.content = content
		if scope is not None:
			self.scope = scope
		self.save()

	def delete_personal(self):
		"""Deletes a personal or team template; globals are deleted via Desk's own delete() instead, not this method."""
		if self.is_global:
			frappe.throw(_("Global templates can't be deleted here"), frappe.PermissionError)
		self.delete()


def render_template(content, thread=None, dm_thread=None):
	"""Fill a template's variables for the conversation the caller is writing in."""
	context = _conversation_context(thread, dm_thread)
	try:
		return _jinja.from_string(content or "").render(context)
	except TemplateError as e:
		# includes the sandbox's SecurityError, e.g. {{ ''.__class__ }}
		frappe.throw(_("This template couldn't be filled in: {0}").format(e.message or e))


def _conversation_context(thread=None, dm_thread=None):
	from connect.permissions import _my_company_membership

	me = frappe.session.user
	_doctype, my_company, _row = _my_company_membership(me)
	recipient, their_company = None, None

	if dm_thread:
		doc = frappe.get_doc("Connect DM Thread", dm_thread)
		doc.check_permission("read")
		recipient = doc.user_b if doc.user_a == me else doc.user_a
		_doctype, their_company, _row = _my_company_membership(recipient)
	elif thread:
		doc = frappe.get_doc("Connect Thread", thread)
		doc.check_permission("read")
		my_side = frappe.db.get_value("Connect Thread Member", {"thread": thread, "user": me}, "side")
		their_side = "Partner" if my_side == "Customer" else "Customer"
		their_company = doc.partner if their_side == "Partner" else doc.customer
		recipient = _latest_member_of_side(thread, their_side)

	return {
		**_person_variables(recipient, their_company, prefix=""),
		**_person_variables(me, my_company, prefix="my_"),
	}


def _latest_member_of_side(thread, side):
	"""A company thread has no single recipient, so "the other person" is whoever on their side
	wrote most recently, or their first active member if none of them has written yet."""
	members = frappe.get_all(
		"Connect Thread Member",
		filters={"thread": thread, "side": side, "is_removed": 0},
		pluck="user",
		order_by="creation asc",
	)
	if not members:
		return None
	latest = frappe.get_all(
		"Connect Message",
		filters={"thread": thread, "sender": ["in", members]},
		pluck="sender",
		order_by="creation desc",
		limit=1,
	)
	return latest[0] if latest else members[0]


def _person_variables(user, company, prefix):
	first_name, full_name = frappe.db.get_value("User", user, ["first_name", "full_name"]) if user else (None, None)
	return {
		f"{prefix}first_name": first_name or "",
		f"{prefix}full_name": full_name or "",
		f"{prefix}email": user or "",
		f"{prefix}company_name": _company_name(company),
	}


def _company_name(company):
	if not company:
		return ""
	if frappe.db.exists("Partner", company):
		return frappe.db.get_value("Partner", company, "partner_name") or company
	return frappe.db.get_value("Customer", company, "customer_name") or company
