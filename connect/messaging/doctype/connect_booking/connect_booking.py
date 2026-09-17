import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class ConnectBooking(Document):
	def validate(self):
		if getdate(self.booking_date) < getdate():
			frappe.throw(_("Can't book a slot in the past"))
		if getdate(self.booking_date).weekday() >= 5:
			frappe.throw(_("Slots are only bookable on weekdays"))
