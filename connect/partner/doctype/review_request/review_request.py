# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, get_url, now_datetime, validate_email_address

from connect.auth.invitations import hash_token

LINK_DAYS = 30
REMIND_AFTER_DAYS = 3
SENT_A_DAY = 20
# Where the emailed link opens: it says who is asking, and acts only when the customer answers.
REVIEW_PAGE = "/connect/review-request"

# The link works while the request is in one of these.
OPEN = ("Sent", "Opened")
# A partner may ask the same person again only after one of these.
ASK_AGAIN = ("Expired", "Withdrawn")
NEXT_STATUSES = {
	"Draft": ("Sent", "Withdrawn"),
	"Sent": ("Opened", "Accepted", "Declined", "Expired", "Withdrawn"),
	"Opened": ("Accepted", "Declined", "Expired", "Withdrawn"),
	"Accepted": ("Reviewed",),
}

# Anyone can open an address here, so it says nothing about where the person works.
FREE_EMAIL_DOMAINS = frozenset(
	{
		"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com",
		"msn.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "zoho.com",
		"zohomail.com", "yandex.com", "mail.com", "gmx.com", "rediffmail.com",
	}
)


class ReviewRequest(Document):
	def before_validate(self):
		self.contact_email = (self.contact_email or "").strip().lower()
		for field in ("contact_name", "company_name", "project_title"):
			self.set(field, (self.get(field) or "").strip())

	def validate(self):
		validate_email_address(self.contact_email, throw=True)
		self.is_free_email = email_domain(self.contact_email) in FREE_EMAIL_DOMAINS
		if self.is_new() or self.has_value_changed("contact_email"):
			self._check_not_the_partners_own()
			self._check_not_asked_before()
		if not self.is_new() and self.has_value_changed("status"):
			self._check_status_change()

	def send(self) -> None:
		"""Emails the contact a one-time link to review the partner."""
		self._check_sent_today()
		self.sent_by = frappe.session.user
		self.sent_on = now_datetime()
		self.status = "Sent"
		self._email_link()

	def remind(self) -> None:
		"""Emails a fresh link once, a few days after the first; the old link stops working."""
		if self.status not in OPEN:
			frappe.throw(_("Only a request that's waiting for an answer can be reminded."))
		if self.reminded_on:
			frappe.throw(_("You've already sent a reminder for this request."))
		if self.sent_on > add_days(now_datetime(), -REMIND_AFTER_DAYS):
			frappe.throw(_("You can send a reminder {0} days after the request.").format(REMIND_AFTER_DAYS))
		self.reminded_on = now_datetime()
		self._email_link(reminder=True)

	def withdraw(self) -> None:
		self.status = "Withdrawn"
		self.token_hash = None
		self.save(ignore_permissions=True)

	def open(self) -> None:
		if self.status == "Sent":
			self.status = "Opened"
			self.save(ignore_permissions=True)

	def accept(self, customer: str) -> None:
		"""The contact confirmed they worked with the partner. The link is used up: from now on
		they sign in as anyone does, and may review the partner."""
		self.customer = customer
		self.status = "Accepted"
		self.token_hash = None
		self.save(ignore_permissions=True)

	def decline(self, reason: str | None) -> None:
		"""The contact says they didn't work with the partner. Frappe's partner reviewers look into it."""
		self.decline_reason = (reason or "").strip() or None
		self.status = "Declined"
		self.token_hash = None
		self.save(ignore_permissions=True)
		self._notify(
			[*self._partner_recipients(), *reviewers()],
			_("{0} said they didn't work with {1}").format(self.contact_name, self.partner_name()),
		)

	def mark_reviewed(self, review: str) -> None:
		self.review = review
		self.status = "Reviewed"
		self.save(ignore_permissions=True)
		self._notify(self._partner_recipients(), _("{0} reviewed {1}").format(self.contact_name, self.partner_name()))

	def partner_name(self) -> str:
		return frappe.db.get_value("Partner", self.partner, "partner_name") or self.partner

	def _check_not_the_partners_own(self):
		if frappe.db.exists("Connect Partner Member", {"user": self.contact_email, "is_removed": 0}):
			frappe.throw(_("{0} is on a partner's team, so they can't review a partner.").format(self.contact_email))
		domain = email_domain(self.contact_email)
		if domain not in FREE_EMAIL_DOMAINS and domain in partner_domains(self.partner):
			frappe.throw(_("{0} is your own company's email address. Ask a customer instead.").format(self.contact_email))

	def _check_not_asked_before(self):
		asked = frappe.db.exists(
			"Review Request",
			{
				"partner": self.partner,
				"contact_email": self.contact_email,
				"status": ["not in", ASK_AGAIN],
				"name": ["!=", self.name or ""],
			},
		)
		if asked:
			frappe.throw(_("You've already asked {0} for a review.").format(self.contact_email))

	def _check_status_change(self):
		before = self.get_doc_before_save().status
		if self.status not in NEXT_STATUSES.get(before, ()):
			frappe.throw(_("A {0} request can't become {1}.").format(before, self.status))

	def _check_sent_today(self):
		sent = frappe.db.count(
			"Review Request", {"partner": self.partner, "sent_on": [">=", add_days(now_datetime(), -1)]}
		)
		if sent >= SENT_A_DAY:
			frappe.throw(_("You can send {0} review requests a day. Try again tomorrow.").format(SENT_A_DAY))

	def _email_link(self, reminder: bool = False):
		token = frappe.generate_hash(length=32)
		self.token_hash = hash_token(token)
		self.expires_on = add_days(now_datetime(), LINK_DAYS)
		self.save(ignore_permissions=True)

		partner = self.partner_name()
		# Queued, not sent now: if the save fails, the email is rolled back with it.
		frappe.sendmail(
			recipients=[self.contact_email],
			subject=_("{0} asked for your feedback on {1}").format(partner, self.project_title),
			template="connect_review_request",
			args={
				"contact_name": self.contact_name,
				"partner": partner,
				"project_title": self.project_title,
				"link": get_url(f"{REVIEW_PAGE}?token={token}"),
				"expires_on": frappe.utils.format_date(self.expires_on),
				"reminder": reminder,
			},
		)

	def _partner_recipients(self) -> list[str]:
		from connect.permissions import _get_partner_owners

		return [*_get_partner_owners(self.partner), self.sent_by]

	def _notify(self, users: list[str], subject: str):
		from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

		users = list(dict.fromkeys(user for user in users if user))
		if not users:
			return
		enqueue_create_notification(
			users,
			{
				"type": "Alert",
				"document_type": "Review Request",
				"document_name": self.name,
				"subject": subject[:140],
				"link": "/customers?view=past",
			},
		)


def email_domain(email: str) -> str:
	return (email or "").rpartition("@")[2].lower()


def partner_domains(partner: str) -> set[str]:
	"""The email domains the partner's own people use, leaving out free ones."""
	emails = frappe.get_all("Connect Partner Member", filters={"partner": partner, "is_removed": 0}, pluck="user")
	emails.append(frappe.db.get_value("Partner", partner, "email") or "")
	return {email_domain(email) for email in emails if email} - FREE_EMAIL_DOMAINS - {""}


def reviewers() -> list[str]:
	"""Frappe's partner reviewers: the people told when a customer disputes a request."""
	from connect.roles import REVIEWER_ROLE

	return frappe.get_all(
		"Has Role", filters={"role": REVIEWER_ROLE, "parenttype": "User"}, pluck="parent", distinct=True
	)


def request_for_link(token: str) -> ReviewRequest:
	"""The request a review link was sent for, while the link still works; else throws."""
	name = None
	if isinstance(token, str) and token:
		name = frappe.db.get_value(
			"Review Request",
			{"token_hash": hash_token(token), "status": ["in", OPEN], "expires_on": [">", now_datetime()]},
			"name",
		)
	if not name:
		frappe.throw(_("This review link has expired or was already used."), frappe.DoesNotExistError)
	return frappe.get_doc("Review Request", name)


def expire_review_requests() -> None:
	"""Daily: requests nobody answered in time stop waiting."""
	for name in frappe.get_all(
		"Review Request", filters={"status": ["in", OPEN], "expires_on": ["<", now_datetime()]}, pluck="name"
	):
		doc = frappe.get_doc("Review Request", name)
		doc.status = "Expired"
		doc.token_hash = None
		doc.save(ignore_permissions=True)


# ---- The partner's side ----

REQUEST_FIELDS = (
	"name", "partner", "contact_name", "contact_email", "company_name", "project_title", "project_summary",
	"status", "sent_on", "reminded_on", "expires_on", "review",
)
EDITABLE_FIELDS = ("contact_name", "contact_email", "company_name", "project_title", "project_summary")


def my_requests() -> list[dict]:
	"""The caller's partner's review requests, newest first."""
	partner = _my_partner()
	return frappe.get_all(
		"Review Request", filters={"partner": partner}, fields=list(REQUEST_FIELDS), order_by="creation desc"
	)


def create_request(values: dict, send: bool = False) -> dict:
	"""A new request from the partner, sent at once when `send` is set."""
	values = frappe._dict(frappe.parse_json(values) or {})
	doc = frappe.get_doc(
		{
			"doctype": "Review Request",
			"partner": _my_partner(),
			**{field: values.get(field) for field in EDITABLE_FIELDS},
		}
	)
	# Review Request is written only through these functions, scoped to the caller's partner.
	doc.insert(ignore_permissions=True)
	if frappe.utils.sbool(send):
		doc.send()
	return _request_dict(doc)


def send_request(name: str) -> dict:
	doc = _my_request(name)
	if doc.status != "Draft":
		frappe.throw(_("This request has already been sent."))
	doc.send()
	return _request_dict(doc)


def remind_request(name: str) -> dict:
	doc = _my_request(name)
	doc.remind()
	return _request_dict(doc)


def withdraw_request(name: str) -> dict:
	doc = _my_request(name)
	doc.withdraw()
	return _request_dict(doc)


def _my_partner() -> str:
	from connect.partner.doctype.connect_partner_member.connect_partner_member import LEAD_ACCESS
	from connect.permissions import _my_partner_with_access

	return _my_partner_with_access(frappe.session.user, LEAD_ACCESS)


def _my_request(name: str) -> ReviewRequest:
	partner = _my_partner()
	if not frappe.db.exists("Review Request", {"name": name, "partner": partner}):
		frappe.throw(_("Review request not found."), frappe.DoesNotExistError)
	return frappe.get_doc("Review Request", name)


def _request_dict(doc: ReviewRequest) -> dict:
	return {field: doc.get(field) for field in REQUEST_FIELDS}


# ---- The customer's side, from the emailed link ----


def open_request(token: str) -> dict:
	"""What the link is about, for the page the customer lands on."""
	from connect.auth.accounts import find_user

	doc = request_for_link(token)
	doc.open()
	user = find_user(doc.contact_email)
	return {
		"partner": doc.partner,
		"partner_name": doc.partner_name(),
		"project_title": doc.project_title,
		"project_summary": doc.project_summary,
		"contact_name": doc.contact_name,
		"contact_email": doc.contact_email,
		"company_name": doc.company_name,
		"has_account": bool(user),
		"is_signed_in_as_contact": bool(user) and frappe.session.user == user.name,
	}


def accept_request(token: str, full_name: str | None = None, company_name: str | None = None) -> dict:
	"""The customer confirms they worked with the partner. A new customer gets an account and company
	from the details they confirm, and the link signs them in. Someone with an account must already be
	signed in to it. Returns where to go next: the partner's profile, to write the review."""
	from connect.auth.accounts import create_account, create_customer, find_user
	from connect.customer.doctype.customer.customer import get_customer_for_user

	doc = request_for_link(token)
	email = doc.contact_email
	if frappe.db.exists("Connect Partner Member", {"user": email, "is_removed": 0}):
		frappe.throw(_("{0} is on a partner's team, so it can't review a partner.").format(email))
	full_name = (full_name or "").strip() or doc.contact_name
	company_name = (company_name or "").strip() or doc.company_name

	user = find_user(email)
	if user:
		# The link lasts 30 days and can be forwarded; an account's projects and chats need its own
		# short-lived sign-in code, not the link.
		if frappe.session.user != user.name:
			frappe.throw(_("Sign in as {0} to confirm this.").format(email), frappe.PermissionError)
		doc.accept(get_customer_for_user(user.name) or create_customer(user.name, full_name, company_name))
	else:
		user_name = create_account(email, {"full_name": full_name, "company_name": company_name})
		doc.accept(get_customer_for_user(user_name))
		frappe.local.login_manager.login_as(user_name)

	return {"redirect": f"/connect/partner-profile-redesign/{doc.partner}?review=1"}


def decline_request(token: str, reason: str | None = None) -> None:
	request_for_link(token).decline(reason)
