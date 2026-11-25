"""Team and thread invitations: an emailed link that signs someone added straight in, once."""

import hashlib
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_days, get_url, now_datetime

from connect.auth.accounts import landing_page

INVITE_DAYS = 7
SIGN_IN_PAGE = "/connect/login-signup-redesign"
# The company each kind of member row belongs to: (link field, doctype, name field).
COMPANIES = {
	"Connect Partner Member": ("partner", "Partner", "company_name"),
	"Customer Team Member": ("customer", "Customer", "customer_name"),
}
THREAD_MEMBER = "Connect Thread Member"
MESSAGING_PAGE = "/connect/messaging"


def invite_member(doc, method=None):
	"""on_update on a member row: invites someone just added, or added back after being removed."""
	before = doc.get_doc_before_save()
	joined = before is None or (before.is_removed and not doc.is_removed)
	if joined and should_invite(doc):
		send_invitation(doc)


def should_invite(doc) -> bool:
	"""Only someone another person added. People who make their own company join it themselves,
	and Frappe consultants are put on the Frappe partner by Connect, not invited."""
	inviter = frappe.session.user
	if doc.is_removed or inviter in ("Guest", doc.user) or doc.get("role") == "Consultant":
		return False
	# A data migration adds every partner's owner at once; Frappe announces the move instead.
	return not (
		frappe.flags.in_install
		or frappe.flags.in_patch
		or frappe.flags.in_migrate
		or frappe.flags.in_data_migration
	)


def send_invitation(doc) -> None:
	"""Emails a link to the sign-in page carrying a one-time token."""
	link, expires_on = issue_sign_in_link(doc)
	company = company_name(doc)
	inviter = frappe.utils.get_fullname(frappe.session.user)
	# Queued, not sent now: if adding the member fails, the email is rolled back with it.
	frappe.sendmail(
		recipients=[doc.user],
		subject=_("{0} invited you to join {1} on Frappe Connect").format(inviter, company),
		template="connect_team_invitation",
		args={
			"inviter": inviter,
			"company": company,
			"link": link,
			"expires_on": frappe.utils.format_date(expires_on),
		},
	)


def send_thread_invitation(member) -> None:
	"""Emails someone added to a thread. Someone who has never signed in gets a one-time sign-in
	link, as the roster shows them Invited until then; anyone else gets a plain link to the thread."""
	expires_on = None
	if frappe.db.get_value("User", member.user, "last_login"):
		link = get_url(thread_path(member.thread))
	else:
		link, expires_on = issue_sign_in_link(member)

	inviter = frappe.utils.get_fullname(member.added_by)
	# The email names only the inviter, an admin of the recipient's side: naming the other side
	# could reveal an anonymous customer to a partner.
	frappe.sendmail(
		recipients=[member.user],
		subject=_("{0} added you to a conversation on Frappe Connect").format(inviter),
		template="connect_thread_invitation",
		args={
			"inviter": inviter,
			"link": link,
			"expires_on": expires_on and frappe.utils.format_date(expires_on),
		},
	)


def issue_sign_in_link(doc) -> tuple[str, datetime]:
	"""Stores a fresh one-time token's hash on the member row; only the hash is kept. The link opens
	the sign-in page, which sends the token on: mail scanners open every link, and would use up
	one that signed in itself."""
	token = frappe.generate_hash(length=32)
	expires_on = add_days(now_datetime(), INVITE_DAYS)
	doc.db_set(
		{"invite_token_hash": hash_token(token), "invite_expires_on": expires_on}, update_modified=False
	)
	return get_url(f"{SIGN_IN_PAGE}?invite={token}"), expires_on


def accept_invitation(token) -> dict:
	"""Signs the invited person in and uses the link up. Returns where to go next."""
	doctype, row = find_invitation(token)
	if not frappe.db.get_value("User", row.user, "enabled"):
		frappe.throw(
			_("This account is disabled. Contact Frappe to restore access."), frappe.ValidationError
		)

	frappe.db.set_value(
		doctype, row.name, {"invite_token_hash": None, "invite_expires_on": None}, update_modified=False
	)

	frappe.local.login_manager.login_as(row.user)
	next_path = thread_path(row.thread) if doctype == THREAD_MEMBER else None
	return {"user": row.user, "redirect": landing_page(row.user, next_path)}


def find_invitation(token):
	"""The member row a token was sent for, while it's still valid; else throws."""
	if not isinstance(token, str) or not token:
		throw_expired()

	token_hash = hash_token(token)
	for doctype in (*COMPANIES, THREAD_MEMBER):
		fields = ["name", "user", "is_removed", "invite_expires_on"]
		if doctype == THREAD_MEMBER:
			fields.append("thread")
		row = frappe.db.get_value(doctype, {"invite_token_hash": token_hash}, fields, as_dict=True)
		if row and not row.is_removed and row.invite_expires_on and row.invite_expires_on > now_datetime():
			return doctype, row
	throw_expired()


def throw_expired():
	frappe.throw(
		_("This invitation link has expired or was already used. Sign in with your email instead."),
		frappe.ValidationError,
	)


def company_name(doc) -> str:
	link_field, company_doctype, name_field = COMPANIES[doc.doctype]
	company = doc.get(link_field)
	return frappe.db.get_value(company_doctype, company, name_field) or company


def thread_path(thread: str) -> str:
	return f"{MESSAGING_PAGE}?thread={thread}"


def hash_token(token: str) -> str:
	return hashlib.sha256(token.encode()).hexdigest()
