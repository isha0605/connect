import frappe
from frappe import _

from connect.api.messages import send_message
from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.customer.doctype.requirement.requirement import format_requirement_message
from connect.messaging.doctype.connect_thread.connect_thread import open_contact_thread


@frappe.whitelist()
def start_partner_thread(partner, message=None):
	"""Finds or creates the (customer, partner) thread and adds both sides as members, for the Contact Partner action."""
	user = frappe.session.user
	customer = get_customer_for_user(user)
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	thread = open_contact_thread(customer, partner, user)

	is_new_thread = not frappe.db.exists("Connect Message", {"thread": thread})
	if is_new_thread and message:
		content = format_requirement_message(customer, message)
		if content:
			send_message(thread, content=content)

	return {"thread": thread, "is_new_thread": is_new_thread}
