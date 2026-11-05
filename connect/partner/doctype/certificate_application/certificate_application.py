# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, escape_html, now_datetime, today

from connect.partner.doctype.certificate_link_request.certificate_link_request import (
	course_page_url,
	create_or_resend,
	has_current_school_certificate,
	is_school_enabled,
)
from connect.partner.doctype.partner_certificate.partner_certificate import (
	CERTIFICATE_COURSES,
	CERTIFICATE_TYPES,
	publish_certificates_updated,
)
from connect.roles import REVIEWER_ROLE

OPEN_STATUSES = ("Applied", "Approved")
# An application holds one of the partner's free certifications in these states.
USED_STATUSES = ("Applied", "Approved", "Certified")
# Where each status may move. Rejected, Cancelled and Certified are final.
NEXT_STATUSES = {"Applied": ("Approved", "Rejected", "Cancelled"), "Approved": ("Certified",)}


class CertificateApplication(Document):
	"""A partner's request for one of their free Frappe School certifications."""

	def before_insert(self):
		self.status = "Applied"
		self.applied_by = frappe.session.user

	def validate(self):
		if self.is_new():
			self._check_can_apply()
		else:
			self._check_status_change()

	def after_insert(self):
		self._email_reviewers()
		publish_certificates_updated(self.partner)

	def on_update(self):
		if not self.has_value_changed("status") or self.is_new():
			return
		if self.status == "Approved":
			self._email_approved()
		elif self.status == "Rejected":
			self._email_rejected()
		publish_certificates_updated(self.partner)

	@frappe.whitelist()
	def approve(self):
		frappe.only_for(REVIEWER_ROLE)
		self._check_applied()
		self.update({"status": "Approved", "reviewed_by": frappe.session.user, "reviewed_on": now_datetime()})
		self.save()

	@frappe.whitelist()
	def reject(self, reason=None):
		frappe.only_for(REVIEWER_ROLE)
		self._check_applied()
		if not (reason or "").strip():
			frappe.throw(_("Say why the application is rejected. The partner sees it."))
		self.update({
			"status": "Rejected", "rejection_reason": reason.strip(), "reviewed_by": frappe.session.user,
			"reviewed_on": now_datetime(),
		})
		self.save()

	def _check_applied(self):
		if self.status != "Applied":
			frappe.throw(_("Only an Applied application can be reviewed."))

	def _check_status_change(self):
		"""Status only moves forward, so a direct save through the API can't reopen a closed
		application or mark one Certified without its certificate."""
		before = self.get_doc_before_save()
		if before and before.status != self.status and self.status not in NEXT_STATUSES.get(before.status, ()):
			frappe.throw(_("A {0} application can't become {1}.").format(_(before.status), _(self.status)))
		if self.status == "Rejected" and not (self.rejection_reason or "").strip():
			frappe.throw(_("Say why the application is rejected. The partner sees it."))
		if self.status == "Certified" and not self.partner_certificate:
			frappe.throw(_("A Certified application needs its Partner Certificate."))

	def _check_can_apply(self):
		status = free_certification_status(self.partner)
		if not status["is_registered"]:
			frappe.throw(_("Free certifications open once Frappe approves your partnership."))
		if not status["left"]:
			frappe.throw(_("You've used all {0} of your free certifications.").format(status["allowance"]))
		if frappe.db.exists(
			"Certificate Application",
			{"member_email": self.member_email, "certificate_type": self.certificate_type, "status": ["in", OPEN_STATUSES]},
		):
			frappe.throw(_("{0} already has an open application for this certificate.").format(self.member_email))

		courses = CERTIFICATE_COURSES[CERTIFICATE_TYPES[self.certificate_type]]
		if has_current_school_certificate(self.member_email, courses):
			frappe.throw(_("{0} already has this certificate. Use Link Certificate instead.").format(self.member_email))

	def _email_reviewers(self):
		reviewers = reviewer_emails()
		if not reviewers:
			return
		frappe.sendmail(
			recipients=reviewers,
			subject=_("{0} applied for a free {1} certification").format(self.partner_name or self.partner, self.certificate_type),
			message=_("{0} asked for a free {1} certification for {2}. Approve or reject it in Desk: {3}").format(
				escape_html(self.partner_name or self.partner), self.certificate_type, escape_html(self.member_email),
				frappe.utils.get_url_to_form(self.doctype, self.name),
			),
		)

	def _email_approved(self):
		from connect.permissions import _get_partner_owners

		link = course_page_url(CERTIFICATE_TYPES[self.certificate_type])
		frappe.sendmail(
			recipients=list(dict.fromkeys([self.member_email, *_get_partner_owners(self.partner)])),
			subject=_("Your free {0} certification is approved").format(self.certificate_type),
			message=_(
				"{0} can now take the {1} course and exam on Frappe School: <a href='{2}'>{2}</a>. Frappe gives "
				"them free access to the exam. Once the certificate is issued, we'll ask them to confirm it "
				"for {3}."
			).format(escape_html(self.member_name or self.member_email), self.certificate_type, link,
				escape_html(self.partner_name or self.partner)),
		)

	def _email_rejected(self):
		from connect.permissions import _get_partner_owners

		owners = _get_partner_owners(self.partner)
		if not owners:
			return
		frappe.sendmail(
			recipients=owners,
			subject=_("Your free {0} certification wasn't approved").format(self.certificate_type),
			message=_("The application for {0} wasn't approved: {1}").format(
				escape_html(self.member_email), escape_html(self.rejection_reason)
			),
		)


def reviewer_emails() -> list[str]:
	users = frappe.get_all("Has Role", filters={"role": REVIEWER_ROLE, "parenttype": "User"}, pluck="parent")
	people = [user for user in users if user not in ("Administrator", "Guest")]
	return frappe.get_all("User", filters={"name": ["in", people or [""]], "enabled": 1}, pluck="name")


def free_certification_status(partner: str) -> dict:
	"""Whether the partner may ask for free certifications, and how many are left. Only an approved
	(Verified) partner may: approval already needed two certificates of its own, the paid ones."""
	partner_row = frappe.db.get_value("Partner", partner, ["verification_status", "free_certifications"], as_dict=True)
	is_registered = partner_row.verification_status == "Verified"
	allowance = cint(partner_row.free_certifications)
	used = frappe.db.count("Certificate Application", {"partner": partner, "status": ["in", USED_STATUSES]})
	left = max(allowance - used, 0)
	return {
		"is_registered": is_registered,
		"allowance": allowance,
		"used": used,
		"left": left,
		"can_apply": is_registered and left > 0,
	}


def apply(member_email: str, certificate_type: str, member_name: str | None = None) -> dict:
	from connect.partner.doctype.partner.partner import _my_admin_partner

	partner = _my_admin_partner()
	if certificate_type not in CERTIFICATE_TYPES:
		frappe.throw(_("Pick ERPNext or Framework."))
	# Partner admins have no Desk permission on applications; _my_admin_partner checked them.
	doc = frappe.get_doc({
		"doctype": "Certificate Application", "partner": partner, "member_email": (member_email or "").strip(),
		"member_name": (member_name or "").strip() or None, "certificate_type": certificate_type,
	}).insert(ignore_permissions=True)
	return {"application": doc.name}


def cancel(application: str) -> dict:
	from connect.partner.doctype.partner.partner import _my_admin_partner

	partner = _my_admin_partner()
	doc = frappe.get_doc("Certificate Application", application)
	if doc.partner != partner:
		frappe.throw(_("This application isn't your partner's. Refresh the page."), frappe.PermissionError)
	if doc.status != "Applied":
		frappe.throw(_("Only an application that's still waiting for review can be cancelled."))
	doc.status = "Cancelled"
	# As in apply: _my_admin_partner and the partner check above stand in for Desk permission.
	doc.save(ignore_permissions=True)
	return {"application": doc.name}


def check_approved_applications(partner: str | None = None) -> list[str]:
	"""Marks Approved applications Certified once Frappe School has issued the certificate, and asks
	the holder to confirm linking it. Returns the applications that became Certified."""
	if not is_school_enabled():
		return []

	filters = {"status": "Approved", **({"partner": partner} if partner else {})}
	certified = []
	for row in frappe.get_all("Certificate Application", filters=filters, fields=["name", "partner", "member_email", "certificate_type"]):
		certificate_type = CERTIFICATE_TYPES[row.certificate_type]
		courses = CERTIFICATE_COURSES[certificate_type]
		if not has_current_school_certificate(row.member_email, courses):
			continue

		create_or_resend(row.partner, row.member_email, certificate_type)
		doc = frappe.get_doc("Certificate Application", row.name)
		# Frappe School issued it: the system marks it, from the daily job or a partner's Check now.
		doc.update({
			"status": "Certified", "certified_on": today(),
			"partner_certificate": frappe.db.get_value(
				"Partner Certificate", {"partner_member_email": row.member_email, "course": ["in", courses]}, "name"
			),
		})
		doc.save(ignore_permissions=True)
		certified.append(row.name)
	return certified


def check_all_approved_applications() -> None:
	"""Daily."""
	try:
		check_approved_applications()
	except frappe.ValidationError:
		# Frappe School didn't answer; the lookup logged it, and tomorrow's run tries again.
		frappe.clear_messages()
