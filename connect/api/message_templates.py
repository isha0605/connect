import frappe
from frappe import _

from connect.permissions import _my_side


@frappe.whitelist()
def get_my_message_templates():
	"""Returns quick-reply templates visible to the caller: shared defaults for their side plus their own personal ones."""
	return frappe.get_list(
		"Connect Message Template",
		fields=["name", "title", "content", "side", "is_global"],
		order_by="is_global desc, title asc",
	)


@frappe.whitelist()
def create_message_template(title, content):
	"""Creates a personal quick-reply template for the caller's own side."""
	side = _my_side(frappe.session.user)
	if not side:
		frappe.throw(_("You are not a member of any company"))

	doc = frappe.get_doc({
		"doctype": "Connect Message Template",
		"title": title,
		"content": content,
		"side": side,
		"is_global": 0,
	})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def update_message_template(name, title=None, content=None):
	doc = frappe.get_doc("Connect Message Template", name)
	doc.update_personal(title=title, content=content)
	return doc.as_dict()


@frappe.whitelist()
def delete_message_template(name):
	doc = frappe.get_doc("Connect Message Template", name)
	doc.delete_personal()
	return {"deleted": name}
