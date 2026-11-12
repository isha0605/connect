# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from connect.partner.doctype.connect_partner_member.connect_partner_member import get_current_membership
from connect.partner.doctype.partner.partner import VERIFIED
from connect.permissions import _is_partner_admin
from connect.roles import REVIEWER_ROLE

# A partner who registers in Connect starts at the lowest tier until Frappe sets theirs.
NEW_PARTNER_TIER = "Beginner"

# The monthly revenue on Frappe Cloud a partner needs before applying, in the currency Frappe Cloud
# bills their team in: rupees for an Indian partner, dollars for everyone else. As Press has it.
MRR_TARGETS = {"INR": 10000, "USD": 100}

_APPLICATION_FIELDS = (
	"company_name",
	"registered_country",
	"registered_state",
	"company_email",
	"contact",
	"address",
	"headquarter_city",
	"annual_revenue",
	"revenue_currency",
	"employee_range",
	"certified_employees_range",
	"verticals_served",
	"customer_count_range",
	"erpnext_customer_count_range",
	"existing_partnerships",
	"erp_implementations_range",
	"incorporation_certificate",
	"company_logo",
	"monthly_revenue",
	"agreed_to_due_diligence",
	"agreed_to_partnership_agreement",
)

_REQUIRED_PROFILE_FIELDS = (
	"company_name",
	"registered_country",
	"company_email",
	"contact",
	"address",
	"headquarter_city",
	"employee_range",
	"agreed_to_due_diligence",
	"agreed_to_partnership_agreement",
)


class PartnerApplication(Document):
	def validate(self):
		if self.registered_country != "India":
			self.registered_state = None
			return

		if self.docstatus == 0 and not self.registered_state:
			frappe.throw(_("Registered state is required when registered country is India."))

	def before_submit(self):
		self._validate_profile_complete()
		self._validate_certificate_count()
		self._validate_cloud_account()
		self._validate_mrr()
		self.status = "Pending Review"
		self.submitted_on = now_datetime()

	def before_save(self):
		if not self.has_value_changed("status"):
			return

		if self.status in ("Approved", "Rejected"):
			self.reviewed_by = frappe.session.user
			self.reviewed_on = now_datetime()
			if self.status == "Approved":
				self.approved_on = now_datetime()

	def on_update_after_submit(self):
		# approve()/reject() always act on an already-submitted (docstatus=1) document, so a
		# status change to Approved/Rejected routes through Frappe's "update after submit" save
		# action, which fires this hook — not on_update, which only fires for docstatus=0 saves.
		if not self.has_value_changed("status"):
			return

		if self.status == "Approved":
			self._apply_approval()
		elif self.status == "Rejected":
			self._apply_rejection()

		from connect.permissions import _get_partner_owners

		for owner in _get_partner_owners(self.partner):
			frappe.publish_realtime(
				"partner_application_status_updated",
				{"partner": self.partner},
				user=owner,
				after_commit=True,
			)

	@frappe.whitelist()
	def approve(self):
		# reviewer role has write at permlevel 1, which is where status and reviewer_comments live
		frappe.only_for(REVIEWER_ROLE)
		self._check_pending_review()
		self.status = "Approved"
		self.reviewer_comments = None
		self.save()

	@frappe.whitelist()
	def reject(self, reason=None):
		frappe.only_for(REVIEWER_ROLE)
		self._check_pending_review()
		self.status = "Rejected"
		self.reviewer_comments = reason
		self.save()

	def _check_pending_review(self):
		if self.docstatus != 1 or self.status != "Pending Review":
			frappe.throw(_("Only a submitted, Pending Review application can be reviewed."))

	def _validate_profile_complete(self):
		missing = [f for f in _REQUIRED_PROFILE_FIELDS if not self.get(f)]
		if self.registered_country == "India" and not self.registered_state:
			missing.append("registered_state")
		if missing:
			frappe.throw(_("Complete your company profile before submitting for approval."))

	def _validate_certificate_count(self):
		from connect.partner.doctype.partner_certificate.partner_certificate import valid_certificates

		if len(valid_certificates(self.partner)) < 2:
			frappe.throw(_("Link at least two certificates before submitting for approval."))

	def _validate_cloud_account(self):
		# Customers add a partner on Frappe Cloud, so a listed partner must have its team there.
		from connect.partner.cloud_integration import is_cloud_enabled

		registered = frappe.db.get_value("Partner", self.partner, "cloud_registration") == "Completed"
		if is_cloud_enabled() and not registered:
			frappe.throw(_("Connect your Frappe Cloud account before submitting for approval."))

	def _validate_mrr(self):
		if flt(self.monthly_revenue) < get_mrr_target(self.registered_country)[1]:
			frappe.throw(_("Reach the minimum monthly revenue before submitting for approval."))

	def _apply_approval(self):
		updates = {"verification_status": VERIFIED}
		if self.company_logo:
			updates["logo"] = self.company_logo
		frappe.db.set_value("Partner", self.partner, updates)

	def _apply_rejection(self):
		frappe.db.set_value("Partner", self.partner, "verification_status", "Rejected")


def _active_application_filters(partner: str) -> dict:
	return {"partner": partner, "docstatus": ["<", 2], "status": ["!=", "Cancelled"]}


def _get_partner_application(partner: str):
	names = frappe.get_all(
		"Partner Application",
		filters=_active_application_filters(partner),
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	if names:
		return frappe.get_doc("Partner Application", names[0])
	return None


@frappe.whitelist()
def get_partner_application():
	from connect.partner.doctype.partner.partner import _my_partner

	partner = _my_partner()
	doc = _get_partner_application(partner)
	return doc.as_dict() if doc else None


@frappe.whitelist(methods=["POST"])
def save_partner_application(details=None):
	details = frappe._dict(frappe.parse_json(details) or {})
	partner = _partner_to_apply_for(details)
	doc = _get_partner_application(partner)

	if not doc:
		doc = frappe.get_doc({"doctype": "Partner Application", "partner": partner, "status": "Draft"})
	elif doc.docstatus != 0:
		frappe.throw(
			_(
				"Submitted application details cannot be changed. Contact support if you need to update them."
			)
		)

	for fieldname in _APPLICATION_FIELDS:
		if fieldname in details:
			doc.set(fieldname, details[fieldname])

	# caller is the partner's own admin (from _my_partner), matching has_partner_application_permission's rule
	if not doc.name:
		doc.insert()
	else:
		doc.save()

	return doc.as_dict()


def _partner_to_apply_for(details: frappe._dict) -> str:
	"""The caller's partner. Someone on no partner's team registers a new one with these details."""
	from connect.partner.doctype.partner.partner import _my_partner

	if get_current_membership(frappe.session.user):
		return _my_partner()
	return _register_partner(details)


def _register_partner(details: frappe._dict) -> str:
	"""A new partner, owned by the caller. It stays off the directory until its application is
	approved (verification_status starts at Pending Review)."""
	# A new applicant has no partner yet, so no permission can let them create one or join it.
	partner = frappe.get_doc(
		{
			"doctype": "Partner",
			"partner_name": details.company_name,
			"country": details.registered_country,
			"tier": NEW_PARTNER_TIER,
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{"doctype": "Connect Partner Member", "partner": partner.name, "user": frappe.session.user, "is_admin": 1}
	).insert(ignore_permissions=True)
	return partner.name


@frappe.whitelist(methods=["POST"])
def submit_for_approval():
	from connect.partner.doctype.partner.partner import _my_partner

	partner = _my_partner()
	doc = _get_partner_application(partner)
	if not doc:
		frappe.throw(_("Register as a partner before submitting for approval."))

	if doc.docstatus == 1:
		return doc.as_dict()

	if doc.docstatus != 0:
		frappe.throw(_("This application cannot be submitted. Register again to start a new one."))

	doc.submit()
	return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def unregister():
	"""The partner's admin opts out while onboarding (Draft, Pending Review or Rejected). An approved
	partnership can't be undone by the partner."""
	from connect.partner.doctype.partner.partner import _my_admin_partner
	from connect.partner.doctype.partner_certificate.partner_certificate import recount_certificates

	partner = _my_admin_partner()
	doc = _get_partner_application(partner)
	if not doc:
		return
	if doc.status == "Approved":
		frappe.throw(_("Your partnership is approved, so it can't be undone here. Contact Frappe."))

	# bulk update via filter dict avoids an N+1 loop per matching row
	frappe.db.set_value("Partner Certificate", {"partner": partner}, "partner", None)
	recount_certificates(partner)
	frappe.db.set_value(
		"Certificate Link Request",
		{"partner": partner, "status": "Pending"},
		{"status": "Cancelled", "key": None},
	)

	if doc.docstatus == 1:
		doc.flags.ignore_permissions = True
		doc.cancel()
	elif doc.docstatus == 0:
		frappe.delete_doc("Partner Application", doc.name, ignore_permissions=True)


@frappe.whitelist()
def get_certificate_link_status():
	from connect.partner.doctype.certificate_application.certificate_application import free_certification_status
	from connect.partner.doctype.certificate_link_request.certificate_link_request import (
		certificate_url,
		course_page_url,
	)
	from connect.partner.doctype.partner.partner import _my_partner
	from connect.partner.doctype.partner_certificate.partner_certificate import course_label, is_expired

	partner = _my_partner()

	linked_certificates = frappe.get_all(
		"Partner Certificate",
		filters={"partner": partner},
		fields=[
			"name", "course", "partner_member_email", "partner_member_name", "issue_date", "expiry_date",
			"school_certificate_id",
		],
		order_by="issue_date desc",
	)
	for certificate in linked_certificates:
		certificate.course_label = course_label(certificate.course)
		certificate.certificate_url = certificate_url(certificate.course, certificate.school_certificate_id)
		certificate.is_expired = is_expired(certificate.expiry_date)
	link_requests = frappe.get_all(
		"Certificate Link Request",
		filters={"partner": partner, "status": ["in", ["Pending", "Approved"]]},
		fields=["name", "course", "user_email", "status", "creation"],
		order_by="creation desc",
	)
	for request in link_requests:
		request.course_label = course_label(request.course)
	pending_requests = [r for r in link_requests if r.status == "Pending"]
	# expired certificates still show, but don't count
	linked_count = len([certificate for certificate in linked_certificates if not certificate.is_expired])

	return {
		"linked_certificates": linked_certificates,
		"link_requests": link_requests,
		"pending_requests": pending_requests,
		"linked_count": linked_count,
		"requirement_complete": linked_count >= 2,
		"can_edit": _is_partner_admin(partner, frappe.session.user),
		"applications": frappe.get_all(
			"Certificate Application",
			filters={"partner": partner, "status": ["!=", "Cancelled"]},
			fields=["name", "member_email", "member_name", "certificate_type", "status", "rejection_reason", "creation"],
			order_by="creation desc",
		),
		"free_certifications": free_certification_status(partner),
		"course_pages": {certificate_type: course_page_url(certificate_type) for certificate_type in ("erpnext", "frappe")},
	}


def get_countries_with_isd_codes():
	"""Returns countries with dialling codes for the registration form's country and phone pickers."""
	from frappe.geo.country_info import get_all

	return sorted(
		(
			{"name": name, "code": info.get("code"), "isd": info.get("isd")}
			for name, info in get_all().items()
			if info.get("code") and info.get("isd")
		),
		key=lambda c: c["name"],
	)


@frappe.whitelist()
def get_mrr_status():
	from connect.partner.doctype.partner.partner import _my_partner

	partner = _my_partner()

	# Pull fresh data from Press if the integration is enabled — this way the partner
	# sees live numbers without waiting for the nightly scheduled sync.
	try:
		press_enabled = frappe.db.get_single_value("Integration Settings", "press_enabled")
		if press_enabled:
			from connect.partner.press_integration import sync_partner_mrr

			sync_partner_mrr(partner)
	except Exception:
		pass  # never let a Press outage block the page load

	doc = _get_partner_application(partner)
	current_amount = flt(doc.monthly_revenue) if doc else 0
	currency, target_amount = get_mrr_target(doc.registered_country if doc else None)

	return {
		"current_amount": current_amount,
		"target_amount": target_amount,
		"currency": currency,
		"progress": min(100, flt((current_amount / target_amount) * 100, 2)),
		"requirement_complete": current_amount >= target_amount,
	}


def get_mrr_target(country: str | None) -> tuple[str, int]:
	"""The currency and minimum monthly revenue for a partner registered in `country`."""
	currency = "INR" if country == "India" else "USD"
	return currency, MRR_TARGETS[currency]
