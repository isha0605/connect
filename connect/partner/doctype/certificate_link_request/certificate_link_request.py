# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, get_url

from connect.partner.doctype.partner_certificate.partner_certificate import (
	CERTIFICATE_COURSES,
	COURSE_PAGES,
	cancel_approved_requests,
	course_label,
	is_expired,
	publish_certificates_updated,
	recount_certificates,
	tell_partner_certificate_moved,
)

DEFAULT_SCHOOL_URL = "https://school.frappe.io"


def _school_url() -> str:
	return (frappe.get_cached_doc("Integration Settings").school_site_url or DEFAULT_SCHOOL_URL).rstrip("/")


def is_school_enabled() -> bool:
	return bool(frappe.db.get_single_value("Integration Settings", "school_enabled"))


def certificate_url(course: str | None, school_certificate_id: str | None) -> str | None:
	"""The certificate's public page on Frappe School."""
	if not (course and school_certificate_id):
		return None
	return f"{_school_url()}/courses/{course}/{school_certificate_id}"


def course_page_url(certificate_type: str) -> str:
	"""Where a team member takes the course and exam for "erpnext" or "frappe"."""
	return f"{_school_url()}/lms/courses/{COURSE_PAGES[certificate_type]}"


class CertificateLinkRequest(Document):
	def before_insert(self):
		self.status = "Pending"
		self.key = frappe.generate_hash(length=15)
		self.partner_name = frappe.db.get_value("Partner", self.partner, "partner_name")

	def after_insert(self):
		self._send_email()

	def on_update(self):
		if not self.has_value_changed("status"):
			return

		if self.status == "Approved":
			self.link_certificate()
		publish_certificates_updated(self.partner)


	def validate(self):
		# refuse before the request is marked Approved, not after
		if self.status == "Approved" and self.has_value_changed("status"):
			self.get_certificate_to_link()

	def get_certificate_to_link(self) -> frappe._dict:
		"""The certificate this request links. One linked to another partner moves: the holder owns
		their certificate, and confirming the emailed link is their consent."""
		row = frappe.db.get_value(
			"Partner Certificate",
			{"partner_member_email": self.user_email, "course": self.course},
			["name", "partner", "expiry_date"],
			as_dict=True,
		)
		if not row:
			frappe.throw(_("No matching certificate found for {0} / {1}").format(self.user_email, self.course))
		if is_expired(row.expiry_date):
			frappe.throw(_("This certificate has expired."))
		return row

	def link_certificate(self):
		row = self.get_certificate_to_link()
		frappe.db.set_value("Partner Certificate", row.name, "partner", self.partner)
		recount_certificates(self.partner)
		if row.partner and row.partner != self.partner:
			cancel_approved_requests(row.partner, self.user_email, self.course)
			recount_certificates(row.partner)
			publish_certificates_updated(row.partner)
			tell_partner_certificate_moved(row.partner, self.partner_name or self.partner, self.user_email, self.course)

	@frappe.whitelist()
	def resend(self):
		self.key = frappe.generate_hash(length=15)
		self.save(ignore_permissions=True)
		self._send_email()

	def _send_email(self):
		link = get_url(f"/connect/certificate-approval?key={self.key}")
		partner_name = escape_html(self.partner_name or self.partner)
		ask = _("Please confirm that your {0} certificate should be linked to {1}.").format(course_label(self.course), partner_name)
		linked_to = frappe.db.get_value(
			"Partner Certificate", {"partner_member_email": self.user_email, "course": self.course}, "partner"
		)
		if linked_to and linked_to != self.partner:
			linked_name = frappe.db.get_value("Partner", linked_to, "partner_name") or linked_to
			ask += " " + _("It's linked to {0} now, and confirming moves it.").format(escape_html(linked_name))
		frappe.sendmail(
			recipients=[self.user_email],
			subject=_("Confirm your certificate for {0}").format(self.partner_name or self.partner),
			message=f"<p>{ask}</p><p><a href='{link}'>{_('Confirm')}</a></p>",
		)


def _get_school_client():
	"""Returns a FrappeClient connected to Frappe School using its configured credentials."""
	from frappe.frappeclient import FrappeClient

	settings = frappe.get_cached_doc("Integration Settings")
	if not settings.school_enabled or not (
		settings.school_site_url and settings.school_api_key and settings.school_api_secret
	):
		frappe.throw(_("Certificate verification isn't configured yet. Contact an administrator."))

	return FrappeClient(
		settings.school_site_url,
		api_key=settings.school_api_key,
		api_secret=settings.get_password("school_api_secret"),
	)


def school_certificates(user_email: str, courses: list[str]) -> list[dict]:
	"""The holder's published certificates for these courses on Frappe School, newest first. Its
	Connect user only sees published ones."""
	client = _get_school_client()
	try:
		return client.get_list(
			"LMS Certificate",
			filters=[["member", "=", user_email], ["course", "in", courses]],
			fields=["name", "course", "issue_date", "expiry_date", "member", "member_name"],
			order_by="issue_date desc",
		)
	except Exception:
		frappe.log_error(title="Frappe School certificate lookup failed")
		frappe.throw(_("Could not reach Frappe School right now. Please try again shortly."))


def has_current_school_certificate(user_email: str, courses: list[str]) -> bool:
	return any(not is_expired(row.get("expiry_date")) for row in school_certificates(user_email, courses))


def _fetch_school_certificate(user_email: str, courses: list[str]) -> tuple[str, str | None]:
	"""Verifies the certificate really exists on Frappe School before asking the holder to link it, and caches it locally."""
	matches = school_certificates(user_email, courses)
	if not matches:
		frappe.throw(_("No certificate found for {0}.").format(user_email))
	current = [row for row in matches if not is_expired(row.get("expiry_date"))]
	if not current:
		frappe.throw(_("This certificate has expired."))

	match = current[0]
	course = match.get("course")
	existing_name = frappe.db.get_value(
		"Partner Certificate", {"partner_member_email": user_email, "course": course}, "name"
	)
	row_values = {
		"course": course,
		"school_certificate_id": match.get("name"),
		"issue_date": match.get("issue_date"),
		"expiry_date": match.get("expiry_date"),
		"partner_member_email": user_email,
		"partner_member_name": match.get("member_name") or user_email,
	}
	if existing_name:
		frappe.db.set_value("Partner Certificate", existing_name, row_values)
		return course, frappe.db.get_value("Partner Certificate", existing_name, "partner")

	doc = frappe.get_doc({"doctype": "Partner Certificate", **row_values})
	doc.insert(ignore_permissions=True)
	return course, doc.partner


def create_or_resend(partner: str, user_email: str, certificate_type: str) -> dict:
	"""Reuses an existing pending link request instead of creating a duplicate, so a repeat click doesn't spam the holder."""
	courses = CERTIFICATE_COURSES.get(certificate_type, CERTIFICATE_COURSES["frappe"])
	course, existing_link = _fetch_school_certificate(user_email, courses)
	if existing_link == partner:
		return {"status": "Linked"}

	existing_request = frappe.db.get_value(
		"Certificate Link Request",
		{"partner": partner, "user_email": user_email, "course": course, "status": "Pending"},
		"name",
	)
	if existing_request:
		doc = frappe.get_doc("Certificate Link Request", existing_request)
		doc.resend()
		return {"status": "Pending", "request": doc.as_dict()}

	doc = frappe.get_doc(
		{"doctype": "Certificate Link Request", "partner": partner, "user_email": user_email, "course": course}
	)
	doc.insert(ignore_permissions=True)
	return {"status": "Pending", "request": doc.as_dict()}


def get_request_for_holder(key: str) -> dict:
	"""What the certificate holder sees before approving: which partner asks for which certificate."""
	request = frappe.db.get_value(
		"Certificate Link Request", {"key": key}, ["partner_name", "course", "user_email", "status"], as_dict=True
	)
	if not key or not request:
		frappe.throw(_("Invalid or expired link."), frappe.DoesNotExistError)
	return {
		"partner_name": request.partner_name,
		"course": course_label(request.course),
		"user_email": request.user_email,
		"status": request.status,
	}


def approve_from_key(key: str):
	"""Approves a link request from the emailed key alone, since the holder has no login session to check."""
	name = frappe.db.get_value("Certificate Link Request", {"key": key}, "name")
	if not name:
		frappe.throw(_("Invalid or expired link."), frappe.DoesNotExistError)

	doc = frappe.get_doc("Certificate Link Request", name)
	if doc.status != "Pending":
		return doc

	doc.status = "Approved"
	doc.save(ignore_permissions=True)
	return doc
