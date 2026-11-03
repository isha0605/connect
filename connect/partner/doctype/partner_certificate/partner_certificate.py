# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, getdate, today

# Same type -> Frappe School courses mapping as Press's CertificateLinkRequest.resolve_certificate:
# the onboarding dialog asks for a certificate type, not a course slug.
CERTIFICATE_COURSES = {
	"frappe": ["frappe-developer-certification", "app-development-with-frappe-framework"],
	"erpnext": ["erpnext-distribution", "erpnext-training"],
}
# The Partner field that counts each type's linked certificates.
COUNT_FIELDS = {"erpnext": "certs_erpnext", "frappe": "certs_frappe_framework"}
# The type each label stands for, as partners pick it.
CERTIFICATE_TYPES = {"ERPNext": "erpnext", "Framework": "frappe"}
# The Frappe School course a team member takes for each type.
COURSE_PAGES = {"erpnext": "erpnext-training", "frappe": "frappe-developer-certification"}


class PartnerCertificate(Document):
	@staticmethod
	def get_list_query(query):
		Partner = frappe.qb.DocType("Partner")
		PartnerCertificate = frappe.qb.DocType("Partner Certificate")
		return query.left_join(Partner).on(PartnerCertificate.partner == Partner.name).select(
			Partner.partner_name
		)


def course_label(course: str | None) -> str:
	""""ERPNext" or "Framework" for a Frappe School course slug, as partners know the two certifications."""
	if course in CERTIFICATE_COURSES["frappe"]:
		return "Framework"
	if course in CERTIFICATE_COURSES["erpnext"]:
		return "ERPNext"
	return course or ""


def is_expired(expiry_date) -> bool:
	return bool(expiry_date) and getdate(expiry_date) < getdate(today())


def valid_certificates(partner: str) -> list[dict]:
	"""The partner's linked certificates that haven't expired: the ones that count."""
	rows = frappe.get_all("Partner Certificate", filters={"partner": partner}, fields=["name", "course", "expiry_date"])
	return [row for row in rows if not is_expired(row.expiry_date)]


def recount_certificates(partner: str) -> None:
	"""Sets the partner's ERPNext and Framework counts, which the profile shows, from their linked,
	unexpired certificates."""
	counts = dict.fromkeys(COUNT_FIELDS.values(), 0)
	for row in valid_certificates(partner):
		for certificate_type, courses in CERTIFICATE_COURSES.items():
			if row.course in courses:
				counts[COUNT_FIELDS[certificate_type]] += 1
	frappe.db.set_value("Partner", partner, counts, update_modified=False)


def recount_partners_with_expired_certificates() -> None:
	"""Daily: a certificate that expired stops counting without anyone touching it."""
	partners = frappe.get_all(
		"Partner Certificate",
		filters={"partner": ["is", "set"], "expiry_date": ["<", today()]},
		pluck="partner",
		distinct=True,
	)
	for partner in partners:
		recount_certificates(partner)


def publish_certificates_updated(partner: str) -> None:
	from connect.permissions import _get_partner_owners

	for owner in _get_partner_owners(partner):
		frappe.publish_realtime(
			"partner_application_certificates_updated", {"partner": partner}, user=owner, after_commit=True
		)


def remove_certificate(certificate: str) -> dict:
	"""The partner's admin unlinks one of their certificates, for example when its holder leaves."""
	from connect.partner.doctype.partner.partner import _my_admin_partner

	partner = _my_admin_partner()
	row = frappe.db.get_value("Partner Certificate", certificate, ["partner", "partner_member_email", "course"], as_dict=True)
	if not row or row.partner != partner:
		frappe.throw(_("This certificate isn't linked to your partner. Refresh the page."), frappe.PermissionError)

	frappe.db.set_value("Partner Certificate", certificate, "partner", None)
	cancel_approved_requests(partner, row.partner_member_email, row.course)
	recount_certificates(partner)
	publish_certificates_updated(partner)
	return {"certificate": certificate}


def cancel_approved_requests(partner: str, user_email: str, course: str) -> None:
	"""The approval that linked a certificate no longer stands once it's unlinked or moved."""
	frappe.db.set_value(
		"Certificate Link Request",
		{"partner": partner, "user_email": user_email, "course": course, "status": "Approved"},
		{"status": "Cancelled", "key": None},
	)


def tell_partner_certificate_moved(old_partner: str, new_partner_name: str, holder: str, course: str) -> None:
	"""The holder confirmed their certificate for another partner, so the old one loses it."""
	from connect.permissions import _get_partner_owners

	owners = _get_partner_owners(old_partner)
	if not owners:
		return
	frappe.sendmail(
		recipients=owners,
		subject=_("A certificate moved to another partner"),
		message=_("{0} confirmed that their {1} certificate now belongs to {2}, so it no longer counts for your partnership.").format(
			escape_html(holder), course_label(course), escape_html(new_partner_name)
		),
	)
