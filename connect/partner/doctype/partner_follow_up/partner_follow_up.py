# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import json
from datetime import timedelta, timezone
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, get_datetime, now_datetime

from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import with_timezone

class PartnerFollowUp(Document):
	"""A call, demo, email or meeting a partner's team had with one customer, shown on the
	customer's leads and on the customer's page. One with a meeting link is an invite: it is
	posted in the customer's thread, where they join it from."""

	def before_insert(self):
		if self.is_invite():
			self.mode = "Meeting"

	def validate(self):
		if self.is_invite() and self.is_new():
			self._validate_invite()

	def after_insert(self):
		if self.is_invite():
			self._post_card()
			frappe.enqueue(
				"connect.partner.doctype.partner_follow_up.partner_follow_up.email_invite",
				queue="short",
				enqueue_after_commit=True,
				name=self.name,
			)

	def is_invite(self) -> bool:
		return bool(self.meeting_link)

	def get_card(self) -> dict:
		return {
			"follow_up": self.name,
			"title": self.title,
			"link": self.meeting_link,
			"starts_at": with_timezone(self.followed_up_on),
			"duration_minutes": self.duration_minutes,
			"agenda": self.notes,
		}

	def _validate_invite(self):
		self.title = (self.title or "").strip()
		self.meeting_link = self.meeting_link.strip()
		if not self.title:
			frappe.throw(_("Give the meeting a title."))
		parsed = urlparse(self.meeting_link)
		if parsed.scheme != "https" or not parsed.netloc:
			frappe.throw(_("Enter the meeting link, starting with https://"))
		if not self.followed_up_on:
			frappe.throw(_("Pick when the meeting is."))
		if get_datetime(self.followed_up_on) <= now_datetime():
			frappe.throw(_("Pick a time that's still to come."))
		if not self.thread:
			frappe.throw(_("A meeting can only be scheduled from a lead."))

	def _post_card(self):
		# The team member's access to the thread was checked by the caller; the card is theirs.
		card = frappe.get_doc(
			{
				"doctype": "Connect Message",
				"thread": self.thread,
				"sender": frappe.session.user,
				"message_type": "Meeting",
				"content": json.dumps(self.get_card()),
			}
		).insert(ignore_permissions=True)
		self.db_set("message", card.name)


def email_invite(name: str) -> None:
	"""Background job: the invite by email too, with a calendar file, to the customer's people
	in the thread."""
	doc = frappe.get_doc("Partner Follow Up", name)
	recipients = frappe.get_all(
		"Connect Thread Member",
		filters={"thread": doc.thread, "side": "Customer", "is_removed": 0},
		pluck="user",
	)
	if not recipients:
		return
	partner_name = frappe.db.get_value("Partner", doc.partner, "partner_name") or doc.partner
	frappe.sendmail(
		recipients=recipients,
		subject=_("{0} invited you to “{1}”").format(partner_name, doc.title),
		message=_invite_email_body(doc, partner_name),
		attachments=[{"fname": "invite.ics", "fcontent": _calendar_file(doc)}],
	)


def _invite_email_body(doc, partner_name: str) -> str:
	when = frappe.utils.format_datetime(doc.followed_up_on, "EEE, d MMM yyyy, h:mm a")
	rows = [
		(_("When"), f"{when} ({frappe.utils.get_system_timezone()})"),
		(_("Duration"), _("{0} minutes").format(doc.duration_minutes) if doc.duration_minutes else None),
		(_("Link"), doc.meeting_link),
		(_("Agenda"), doc.notes),
	]
	details = "<br>".join(f"<b>{label}:</b> {escape_html(str(value))}" for label, value in rows if value)
	return (
		f"<p>{escape_html(_('{0} would like to meet you.').format(partner_name))}</p>"
		f"<p>{details}</p>"
		f"<p>{escape_html(_('Join from the invite in your conversation with them on Connect, or from your calendar.'))}</p>"
	)


def _calendar_file(doc) -> str:
	"""An iCalendar event, so the meeting lands in the customer's calendar in one click."""
	starts = _utc(doc.followed_up_on)
	ends = starts + timedelta(minutes=doc.duration_minutes or 30)
	stamp = "%Y%m%dT%H%M%SZ"
	lines = [
		"BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Frappe Connect//EN", "METHOD:PUBLISH", "BEGIN:VEVENT",
		f"UID:{doc.name}@connect",
		f"DTSTAMP:{_utc(now_datetime()).strftime(stamp)}",
		f"DTSTART:{starts.strftime(stamp)}",
		f"DTEND:{ends.strftime(stamp)}",
		f"SUMMARY:{_ical_text(doc.title)}",
		f"DESCRIPTION:{_ical_text(doc.notes or '')}",
		f"LOCATION:{_ical_text(doc.meeting_link)}",
		f"URL:{doc.meeting_link}",
		"END:VEVENT", "END:VCALENDAR",
	]
	return "\r\n".join(lines)


def _utc(value):
	"""A stored datetime (system time zone, without one) in UTC."""
	return get_datetime(with_timezone(value)).astimezone(timezone.utc)


def _ical_text(text: str) -> str:
	return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

