# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url

# Same type -> Frappe School courses mapping as Press's CertificateLinkRequest.resolve_certificate:
# the onboarding dialog asks for a certificate type, not a course slug.
CERTIFICATE_COURSES = {
	"frappe": ["frappe-developer-certification", "app-development-with-frappe-framework"],
	"erpnext": ["erpnext-distribution", "erpnext-training"],
}


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

		from connect.permissions import _get_partner_admin

		frappe.publish_realtime(
			"partner_application_certificates_updated",
			{"partner": self.partner},
			user=_get_partner_admin(self.partner),
			after_commit=True,
		)

	def link_certificate(self):
		row_name = frappe.db.get_value(
			"Partner Certificate",
			{"partner_member_email": self.user_email, "course": self.course},
			"name",
		)
		if not row_name:
			frappe.throw(_("No matching certificate found for {0} / {1}").format(self.user_email, self.course))

		existing_partner = frappe.db.get_value("Partner Certificate", row_name, "partner")
		if existing_partner and existing_partner != self.partner:
			frappe.throw(_("This certificate is already linked to another partner."))

		frappe.db.set_value("Partner Certificate", row_name, "partner", self.partner)

	@frappe.whitelist()
	def resend(self):
		self.key = frappe.generate_hash(length=15)
		self.save(ignore_permissions=True)
		self._send_email()

	def _send_email(self):
		link = get_url(f"/certificate-approval?key={self.key}")
		try:
			frappe.sendmail(
				recipients=[self.user_email],
				subject=_("Confirm your certificate for {0}").format(self.partner_name or self.partner),
				message=(
					f"<p>{_('Please confirm that your {0} certificate should be linked to {1}.').format(self.course, frappe.utils.escape_html(self.partner_name or self.partner))}</p>"
					f"<p><a href='{link}'>{_('Confirm')}</a></p>"
				),
				now=True,
			)
		except Exception:
			frappe.log_error(title=f"Certificate link email failed for {self.name}")


def _get_school_client():
	"""Returns a FrappeClient connected to school.frappe.io using the credentials stored in
	Frappe School Settings, or throws a clear, distinct error if it isn't configured yet."""
	from frappe.frappeclient import FrappeClient

	settings = frappe.get_cached_doc("Frappe School Settings")
	if not settings.enabled or not (settings.site_url and settings.api_key and settings.api_secret):
		frappe.throw(_("Certificate verification isn't configured yet. Contact an administrator."))

	return FrappeClient(
		settings.site_url,
		api_key=settings.api_key,
		api_secret=settings.get_password("api_secret"),
	)


def _fetch_school_certificate(user_email: str, courses: list[str]) -> tuple[str, str | None]:
	"""Looks up a live LMS Certificate on school.frappe.io for this email in any of `courses`
	(newest first, like Press), and upserts a local Partner Certificate cache row for it. Returns
	the matched course and the partner that row is already linked to, if any. Throws distinctly on
	"not found" vs. "couldn't reach School" — a network failure must never read as a missing one."""
	client = _get_school_client()

	try:
		matches = client.get_list(
			"LMS Certificate",
			filters=[["member", "=", user_email], ["course", "in", courses]],
			fields=["name", "course", "issue_date", "member", "member_name"],
			order_by="issue_date desc",
		)
	except Exception:
		frappe.log_error(title="Frappe School certificate lookup failed")
		frappe.throw(_("Could not reach Frappe School right now. Please try again shortly."))

	if not matches:
		frappe.throw(_("No certificate found for {0}.").format(user_email))

	match = matches[0]
	course = match.get("course")
	existing_name = frappe.db.get_value(
		"Partner Certificate", {"partner_member_email": user_email, "course": course}, "name"
	)
	row_values = {
		"course": course,
		"school_certificate_id": match.get("name"),
		"issue_date": match.get("issue_date"),
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
	"""Verifies the certificate exists on Frappe School (live), then mirrors Press's flow: already
	linked to this partner -> "Linked"; linked elsewhere -> error; otherwise reuse an existing
	Pending request for the same (partner, email, course) instead of creating a duplicate."""
	courses = CERTIFICATE_COURSES.get(certificate_type, CERTIFICATE_COURSES["frappe"])
	course, existing_link = _fetch_school_certificate(user_email, courses)
	if existing_link == partner:
		return {"status": "Linked"}
	if existing_link:
		frappe.throw(_("This certificate is already linked to another partner."))

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


def approve_from_key(key: str):
	"""Called only from connect/www/certificate-approval.py's guest POST handler. Possession of
	the emailed key is the authorization — the holder has no login session to check."""
	name = frappe.db.get_value("Certificate Link Request", {"key": key}, "name")
	if not name:
		frappe.throw(_("Invalid or expired link."), frappe.DoesNotExistError)

	doc = frappe.get_doc("Certificate Link Request", name)
	if doc.status != "Pending":
		return doc

	doc.status = "Approved"
	doc.save(ignore_permissions=True)
	return doc
