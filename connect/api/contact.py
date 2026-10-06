import frappe
from frappe import _

from connect.api.messages import send_message
from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.permissions import _get_partner_admin


def _format_requirement_message(customer, note=None):
	"""Turns the customer's saved Requirement into a readable message body, with an optional note appended."""
	lines = []
	requirement = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if requirement:
		req = frappe.get_doc("Requirement", requirement)
		lines.append(_("New inquiry from {0} — here's what they're looking for:").format(req.company_name or customer))
		if req.industry:
			lines.append(_("Industry: {0}").format(req.industry))
		if req.looking_for:
			lines.append(_("Looking for: {0}").format(req.looking_for))
		apps = [a.app for a in req.apps]
		if apps:
			lines.append(_("Apps: {0}").format(", ".join(apps)))
		if req.company_size:
			lines.append(_("Company size: {0}").format(req.company_size))
		if req.timeline:
			lines.append(_("Timeline: {0}").format(req.timeline))
		if req.budget:
			lines.append(_("Budget: {0}").format(req.budget))
		if req.delivery_preference:
			lines.append(_("Delivery preference: {0}").format(req.delivery_preference))

	note = (note or "").strip()
	if note:
		if lines:
			lines.append("")
		lines.append(note)

	return "\n".join(lines) if lines else None


def _ensure_thread_member(thread, user, side, added_by):
	"""Idempotent: only creates a membership row if this user doesn't already have one — used by start_partner_thread's two call sites."""
	if not frappe.db.exists("Connect Thread Member", {"thread": thread, "user": user}):
		frappe.get_doc({
			"doctype": "Connect Thread Member",
			"thread": thread,
			"user": user,
			"side": side,
			"permission": "Write",
			"added_by": added_by,
		}).insert(ignore_permissions=True)


@frappe.whitelist()
def start_partner_thread(partner, message=None):
	"""Finds or creates the (customer, partner) thread and adds both sides as members, for the Contact Partner action."""
	user = frappe.session.user
	customer = get_customer_for_user(user)
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	thread = frappe.db.get_value("Connect Thread", {"customer": customer, "partner": partner}, "name")
	if not thread:
		thread = frappe.get_doc({
			"doctype": "Connect Thread",
			"customer": customer,
			"partner": partner,
		}).insert().name

	_ensure_thread_member(thread, user, "Customer", user)

	partner_admin = _get_partner_admin(partner)
	if partner_admin:
		_ensure_thread_member(thread, partner_admin, "Partner", user)

	is_new_thread = not frappe.db.exists("Connect Message", {"thread": thread})
	if is_new_thread and message:
		content = _format_requirement_message(customer, message)
		if content:
			send_message(thread, content=content)

	return {"thread": thread, "is_new_thread": is_new_thread}
