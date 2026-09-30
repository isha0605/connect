import frappe
from frappe import _

from connect.permissions import _my_side


@frappe.whitelist()
def get_my_message_templates():
	"""Returns templates visible to the caller, with globals first so shared defaults appear above personal ones."""
	return frappe.get_list(
		"Connect Message Template",
		fields=["name", "title", "content", "side", "is_global", "scope", "team", "owner"],
		order_by="is_global desc, title asc",
	)


@frappe.whitelist()
def create_message_template(title, content, scope="Personal"):
	"""Creates a Personal or Team template for the caller's side, blocking Global since those are Desk-admin only."""
	side = _my_side(frappe.session.user)
	if not side:
		frappe.throw(_("You are not a member of any company"))
	if scope not in ("Personal", "Team"):
		frappe.throw(_("Scope must be Personal or Team"))

	doc = frappe.get_doc({
		"doctype": "Connect Message Template",
		"title": title,
		"content": content,
		"side": side,
		"scope": scope,
	})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def update_message_template(name, title=None, content=None, scope=None):
	"""Thin API entry; owner-only enforcement lives on Connect Message Template."""
	if scope is not None and scope not in ("Personal", "Team"):
		frappe.throw(_("Scope must be Personal or Team"))
	doc = frappe.get_doc("Connect Message Template", name)
	doc.update_personal(title=title, content=content, scope=scope)
	return doc.as_dict()


@frappe.whitelist()
def delete_message_template(name):
	doc = frappe.get_doc("Connect Message Template", name)
	doc.delete_personal()
	return {"deleted": name}


@frappe.whitelist()
def render_message_template(content, thread=None, dm_thread=None):
	"""Returns the template filled in for the current conversation so the client can preview before sending."""
	from connect.messaging.doctype.connect_message_template.connect_message_template import render_template

	return render_template(content, thread=thread, dm_thread=dm_thread)
