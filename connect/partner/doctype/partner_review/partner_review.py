# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_fullname, nowdate

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.partner.doctype.partner.partner import recompute_rating_from_reviews
from connect.roles import REVIEWER_ROLE


HIRED = "Hired on Connect"
CONFIRMED = "Confirmed by customer"
# A review request the customer has accepted, and so may review from.
ACCEPTED = ("Accepted", "Reviewed")


class PartnerReview(Document):
	def after_insert(self):
		recompute_rating_from_reviews(self.partner)

	def on_update(self):
		recompute_rating_from_reviews(self.partner)
		if self.review_request and self.has_value_changed("review_request"):
			frappe.get_doc("Review Request", self.review_request).mark_reviewed(self.name)

	def on_trash(self):
		recompute_rating_from_reviews(self.partner, exclude=self.name)

	def refresh_standing(self):
		"""The company's standing with the partner changed, as when it accepts a review request
		after it wrote this review: the review links that request and says how Connect knows them."""
		self.verification, self.review_request = _standing(self.partner, self.customer)
		self.save(ignore_permissions=True)

	@frappe.whitelist()
	def hide(self, reason=None):
		"""Frappe's partner reviewers take a review off the profile and out of the rating."""
		frappe.only_for((REVIEWER_ROLE, "System Manager"))
		if not (reason or "").strip():
			frappe.throw(_("Say why the review is hidden."))
		self.update({"is_hidden": 1, "hidden_reason": reason.strip()})
		# Reviewers only read reviews, so a customer's words can't be edited; hiding is theirs to do.
		self.save(ignore_permissions=True)

	@frappe.whitelist()
	def show(self):
		frappe.only_for((REVIEWER_ROLE, "System Manager"))
		self.update({"is_hidden": 0, "hidden_reason": None})
		self.save(ignore_permissions=True)


def list_partner_reviews(partner):
	"""Returns a partner's reviews as a plain API call, since Studio's Document List resource isn't guest-accessible."""
	return frappe.get_all(
		"Partner Review",
		filters={"partner": partner, "is_hidden": 0},
		fields=[
			"reviewer_name", "customer", "customer.customer_name as customer_name",
			"rating", "headline", "quote", "reviewed_on", "verification",
			"business_understanding", "implementation_quality", "communication",
			"timeliness", "support", "technical_expertise",
		],
		order_by="reviewed_on desc",
		limit_page_length=100,
	)


def get_my_review_for_partner(partner):
	"""The caller's own review of a partner, so the review form opens pre-filled, and whether
	they may review it at all. A company reviews a partner once, and only its author edits it."""
	customer = get_customer_for_user()
	if not customer:
		return {"review": None, "can_review": False, "reviewed_by_teammate": False}
	rows = frappe.get_all(
		"Partner Review", filters={"partner": partner, "customer": customer}, fields=["*"], limit_page_length=1
	)
	review = rows[0] if rows else None
	if review and review.owner != frappe.session.user:
		return {"review": None, "can_review": False, "reviewed_by_teammate": True}
	return {"review": review, "can_review": _standing(partner, customer)[0] is not None, "reviewed_by_teammate": False}


def submit_partner_review(
	partner, rating, headline=None, quote=None,
	business_understanding=None, implementation_quality=None, communication=None,
	timeliness=None, support=None, technical_expertise=None,
):
	"""Creates or updates the caller's review of a partner. Only the partner's real customers
	review it: those who completed a project with it on Connect, or confirmed they worked with it
	from its request."""
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)
	verification, review_request = review_standing(partner, customer)

	rating = cint(rating)
	if rating < 1 or rating > 5:
		frappe.throw(_("Rating must be between 1 and 5."))

	values = {
		"partner": partner,
		"customer": customer,
		"reviewer_name": get_fullname(frappe.session.user),
		"rating": rating,
		"headline": headline,
		"quote": quote,
		"reviewed_on": nowdate(),
		"verification": verification,
		"business_understanding": cint(business_understanding) or None,
		"implementation_quality": cint(implementation_quality) or None,
		"communication": cint(communication) or None,
		"timeliness": cint(timeliness) or None,
		"support": cint(support) or None,
		"technical_expertise": cint(technical_expertise) or None,
	}

	if review_request:
		values["review_request"] = review_request

	existing = frappe.db.get_value("Partner Review", {"partner": partner, "customer": customer}, ["name", "owner"], as_dict=True)
	if existing and existing.owner != frappe.session.user:
		frappe.throw(_("Someone at your company has already reviewed this partner."), frappe.PermissionError)
	if existing:
		doc = frappe.get_doc("Partner Review", existing.name)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Partner Review", **values})
		doc.insert(ignore_permissions=True)

	return {"name": doc.name}


def review_standing(partner: str, customer: str) -> tuple[str, str | None]:
	"""How Connect knows the customer worked with the partner, and the review request that shows
	it, if any. Throws for a customer who neither completed a project with the partner nor was
	asked by them."""
	verification, request = _standing(partner, customer)
	if not verification:
		frappe.throw(
			_("Only customers who completed a project with this partner on Connect, or whom they asked for feedback, can review them."),
			frappe.PermissionError,
		)
	return verification, request


def _standing(partner: str, customer: str) -> tuple[str | None, str | None]:
	# A hired customer may also have answered the partner's request; the review answers it too.
	request = frappe.db.get_value(
		"Review Request", {"partner": partner, "customer": customer, "status": ["in", ACCEPTED]}, "name"
	)
	if _completed_a_project(partner, customer):
		return HIRED, request
	return (CONFIRMED, request) if request else (None, None)


def _completed_a_project(partner: str, customer: str) -> bool:
	"""Whether someone at the company completed a project with the partner on Connect. A hire
	alone isn't enough: nothing has been delivered yet, and it can still be cancelled."""
	Project = frappe.qb.DocType("Customer Project")
	Member = frappe.qb.DocType("Customer Team Member")
	return bool(
		frappe.qb.from_(Project)
		.join(Member)
		.on(Member.user == Project.user)
		.select(Project.name)
		.where((Project.partner == partner) & (Project.status == "Completed") & (Member.customer == customer))
		.limit(1)
		.run()
	)
