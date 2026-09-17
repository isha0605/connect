import json

import frappe
from frappe import _
from frappe.utils import cint

from connect.permissions import _check_can_write

# Used whenever a partner hasn't configured their own Partner Booking Slot rows yet, so the
# "Book a slot" dialog always has something to offer instead of coming up empty.
DEFAULT_SLOTS = [
	{"time": "14:00:00", "capacity": 3},
	{"time": "15:00:00", "capacity": 3},
	{"time": "16:00:00", "capacity": 3},
	{"time": "17:00:00", "capacity": 3},
]


def _partner_slot_template(partner):
	rows = frappe.get_all(
		"Partner Booking Slot",
		filters={"parent": partner, "parenttype": "Partner", "parentfield": "booking_slots"},
		fields=["time", "capacity"],
		order_by="time asc",
	)
	return rows or DEFAULT_SLOTS


@frappe.whitelist(allow_guest=True)
def get_available_slots(partner, booking_date):
	"""Returns the partner's daily slot template for one date, each with how many spots are left."""
	template = _partner_slot_template(partner)
	slots = []
	for slot in template:
		capacity = cint(slot["capacity"])
		booked = frappe.db.count(
			"Connect Booking",
			filters={"partner": partner, "booking_date": booking_date, "booking_time": slot["time"]},
		)
		slots.append({
			"time": str(slot["time"]),
			"capacity": capacity,
			"booked": booked,
			"spots_left": max(0, capacity - booked),
		})
	return slots


@frappe.whitelist()
def request_slot(thread, booking_date, booking_time):
	"""Books an introduction call and drops a Booking-type message announcing it into the thread,
	so both sides see the same confirmation card (see Connect Message's message_type)."""
	user = frappe.session.user
	_check_can_write(thread, user)

	thread_doc = frappe.db.get_value("Connect Thread", thread, ["partner", "customer"], as_dict=True)
	if not thread_doc:
		frappe.throw(_("Thread not found"))

	template = _partner_slot_template(thread_doc.partner)
	slot = next((s for s in template if str(s["time"])[:8] == str(booking_time)[:8]), None)
	if not slot:
		frappe.throw(_("That slot is no longer available"))

	# Recounted here rather than trusting whatever spots_left the client last fetched — the only
	# way to keep two customers from both landing in the last spot of a slot at the same time.
	booked = frappe.db.count(
		"Connect Booking",
		filters={"partner": thread_doc.partner, "booking_date": booking_date, "booking_time": booking_time},
	)
	if booked >= cint(slot["capacity"]):
		frappe.throw(_("This slot is full"))

	booking = frappe.get_doc({
		"doctype": "Connect Booking",
		"thread": thread,
		"partner": thread_doc.partner,
		"customer": thread_doc.customer,
		"booked_by": user,
		"booking_date": booking_date,
		"booking_time": booking_time,
	})
	booking.insert()

	message = frappe.get_doc({
		"doctype": "Connect Message",
		"thread": thread,
		"sender": user,
		"message_type": "Booking",
		"content": json.dumps({
			"booking": booking.name,
			"date": str(booking_date),
			"time": str(booking_time),
			"duration_minutes": booking.duration_minutes,
			"meeting_type": booking.meeting_type,
		}),
	})
	message.insert()

	return message.as_dict()
