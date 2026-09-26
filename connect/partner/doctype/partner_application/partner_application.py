# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from connect.roles import REVIEWER_ROLE

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

		frappe.publish_realtime(
			"partner_application_status_updated",
			{"partner": self.partner},
			user=self._partner_admin_user(),
			after_commit=True,
		)

	@frappe.whitelist()
	def approve(self):
		frappe.only_for(REVIEWER_ROLE)
		self._check_pending_review()
		self.status = "Approved"
		self.reviewer_comments = None
		self.save(ignore_permissions=True)

	@frappe.whitelist()
	def reject(self, reason=None):
		frappe.only_for(REVIEWER_ROLE)
		self._check_pending_review()
		self.status = "Rejected"
		self.reviewer_comments = reason
		self.save(ignore_permissions=True)

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
		linked_count = frappe.db.count("Partner Certificate", {"partner": self.partner})
		if linked_count < 2:
			frappe.throw(_("Link at least two certificates before submitting for approval."))

	def _validate_mrr(self):
		target = flt(frappe.db.get_single_value("Frappe School Settings", "mrr_target")) or 0
		if flt(self.monthly_revenue) < target:
			frappe.throw(_("Reach the minimum monthly revenue before submitting for approval."))

	def _apply_approval(self):
		updates = {"verification_status": "Verified"}
		if self.company_logo:
			updates["logo"] = self.company_logo
		frappe.db.set_value("Partner", self.partner, updates)

	def _apply_rejection(self):
		frappe.db.set_value("Partner", self.partner, "verification_status", "Rejected")

	def _partner_admin_user(self):
		from connect.permissions import _get_partner_admin

		return _get_partner_admin(self.partner)


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
	from connect.partner.doctype.partner.partner import _my_partner

	partner = _my_partner()
	details = frappe._dict(frappe.parse_json(details) or {})
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

	if not doc.name:
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)

	return doc.as_dict()


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
	from connect.partner.doctype.partner.partner import _my_partner

	partner = _my_partner()
	doc = _get_partner_application(partner)
	if not doc:
		return

	for name in frappe.get_all("Partner Certificate", filters={"partner": partner}, pluck="name"):
		frappe.db.set_value("Partner Certificate", name, "partner", None)

	for name in frappe.get_all(
		"Certificate Link Request", filters={"partner": partner, "status": "Pending"}, pluck="name"
	):
		frappe.db.set_value("Certificate Link Request", name, {"status": "Cancelled", "key": None})

	if doc.docstatus == 1:
		doc.flags.ignore_permissions = True
		doc.cancel()
	elif doc.docstatus == 0:
		frappe.delete_doc("Partner Application", doc.name, ignore_permissions=True)


@frappe.whitelist()
def get_certificate_link_status():
	from connect.partner.doctype.partner.partner import _my_partner

	partner = _my_partner()

	linked_certificates = frappe.get_all(
		"Partner Certificate",
		filters={"partner": partner},
		fields=["name", "course", "partner_member_email", "partner_member_name"],
		order_by="creation desc",
	)
	link_requests = frappe.get_all(
		"Certificate Link Request",
		filters={"partner": partner, "status": ["in", ["Pending", "Approved"]]},
		fields=["name", "course", "user_email", "status", "creation"],
		order_by="creation desc",
	)
	pending_requests = [r for r in link_requests if r.status == "Pending"]
	linked_count = len(linked_certificates)

	return {
		"linked_certificates": linked_certificates,
		"link_requests": link_requests,
		"pending_requests": pending_requests,
		"linked_count": linked_count,
		"requirement_complete": linked_count >= 2,
	}


def get_countries_with_isd_codes():
	"""Countries with their dialling code for the registration form's country and phone pickers —
	the same shape Press's get_countries_with_isd_codes returns, built from Frappe's bundled geo data."""
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
	doc = _get_partner_application(partner)
	current_amount = flt(doc.monthly_revenue) if doc else 0
	target_amount = flt(frappe.db.get_single_value("Frappe School Settings", "mrr_target")) or 0

	return {
		"current_amount": current_amount,
		"target_amount": target_amount,
		"currency": (doc.revenue_currency if doc else None) or frappe.db.get_default("currency"),
		"progress": min(100, flt((current_amount / target_amount) * 100, 2)) if target_amount else 0,
		"requirement_complete": current_amount >= target_amount if target_amount else True,
	}
