import frappe

from connect.auth.accounts import create_user
from connect.membership import ADMIN, OWNER
from connect.partner.migration.report import Report

# A source site sometimes names a Frappe staff member as a partner's user. Staff don't run partners.
FRAPPE_STAFF_DOMAINS = frozenset({"frappe.io"})


def add_owner(
	partner: str, email: str | None, full_name: str | None, country: str | None, report: Report
) -> None:
	"""The person who runs the partner on its source site joins it in Connect, so they sign in with an
	email code. The partner's first such person is its Owner, a later one an Admin. No invitation
	goes out: Frappe announces the move to every partner at once."""
	if not email or frappe.db.exists("Connect Partner Member", {"partner": partner, "user": email}):
		return
	if email.rsplit("@", 1)[-1].lower() in FRAPPE_STAFF_DOMAINS:
		report.add("owners_skipped", f"{partner}: {email} is Frappe staff")
		return

	# One person running two partners is almost always shared or wrong data: staff decide.
	owns = frappe.db.get_value(
		"Connect Partner Member",
		{"user": email, "access": OWNER, "is_removed": 0, "partner": ["!=", partner]},
		"partner",
	)
	if owns:
		report.add("conflicts", f"{email} already owns {owns}, so isn't added to {partner}")
		return

	if not frappe.db.exists("User", email):
		create_user(email, full_name or email.split("@")[0], country)

	has_owner = frappe.db.exists(
		"Connect Partner Member", {"partner": partner, "access": OWNER, "is_removed": 0}
	)
	access = ADMIN if has_owner else OWNER
	frappe.get_doc(
		{"doctype": "Connect Partner Member", "partner": partner, "user": email, "access": access}
	).insert(
		ignore_permissions=True  # The migration is a system job, not a user.
	)
	report.add("members_added", f"{partner}: {email} ({access})")
