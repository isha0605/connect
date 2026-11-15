import frappe
from frappe import _
from frappe.model.document import Document

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.partner.doctype.connect_partner_member.connect_partner_member import get_current_membership

MAX_MESSAGE_LENGTH = 2000
MAX_PAGE_LENGTH = 140


class ConnectFeedback(Document):
	def validate(self):
		self.message = (self.message or "").strip()
		if not self.message:
			frappe.throw(_("Write your feedback first."), frappe.MandatoryError)
		if len(self.message) > MAX_MESSAGE_LENGTH:
			frappe.throw(_("Keep your feedback to {0} characters.").format(MAX_MESSAGE_LENGTH))


def submit_feedback(message: str, page: str | None = None) -> str:
	"""Saves what the signed-in user wrote, with the company they act for and the page they were on,
	for Frappe staff to read in the Desk."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Sign in to send feedback."), frappe.PermissionError)

	membership = get_current_membership(user)
	doc = frappe.get_doc(
		{
			"doctype": "Connect Feedback",
			"user": user,
			"partner": membership.partner if membership else None,
			"customer": get_customer_for_user(user),
			"page": (page or "")[:MAX_PAGE_LENGTH],
			"message": message,
		}
	)
	# Partners and customers have no Desk access to Connect Feedback; the record is the caller's own.
	doc.insert(ignore_permissions=True)
	return doc.name
