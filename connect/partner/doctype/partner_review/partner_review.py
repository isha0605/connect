# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_fullname, nowdate

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.partner.doctype.partner.partner import recompute_rating_from_reviews


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
	"""Returns the caller's own review of a partner, if one exists, so the review form opens pre-filled."""
	customer = get_customer_for_user()
	if not customer:
		return None
	rows = frappe.get_all(
		"Partner Review", filters={"partner": partner, "customer": customer}, fields=["*"], limit_page_length=1
	)
	return rows[0] if rows else None


def submit_partner_review(
	partner, rating, headline=None, quote=None,
	business_understanding=None, implementation_quality=None, communication=None,
	timeliness=None, support=None, technical_expertise=None,
):
	"""Creates or updates the caller's review of a partner. Only the partner's real customers
	review it: those who hired it on Connect, or confirmed they worked with it from its request."""
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

	existing = frappe.db.get_value("Partner Review", {"partner": partner, "customer": customer}, "name")
	if existing:
		doc = frappe.get_doc("Partner Review", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Partner Review", **values})
		doc.insert(ignore_permissions=True)

	return {"name": doc.name}


def review_standing(partner: str, customer: str) -> tuple[str, str | None]:
	"""How Connect knows the customer worked with the partner, and the review request that shows
	it, if any. Throws for a customer who neither hired the partner nor was asked by them."""
	if frappe.db.exists("Partner Customer", {"partner": partner, "customer": customer, "source": "Connect"}):
		return HIRED, None
	request = frappe.db.get_value(
		"Review Request", {"partner": partner, "customer": customer, "status": ["in", ACCEPTED]}, "name"
	)
	if request:
		return CONFIRMED, request
	frappe.throw(
		_("Only customers who hired this partner on Connect, or whom they asked for feedback, can review them."),
		frappe.PermissionError,
	)
