import frappe

CUSTOMER_ROLE = "Connect Customer"
PARTNER_ROLE = "Connect Partner"
CUSTOMER_GUEST_ROLE = "Connect Customer Guest"
PARTNER_GUEST_ROLE = "Connect Partner Guest"

_COMPANY_ROLE_BY_DOCTYPE = {
	"Connect Customer Member": CUSTOMER_ROLE,
	"Connect Partner Member": PARTNER_ROLE,
	"Customer Team Member": CUSTOMER_ROLE,
}
_GUEST_ROLE_BY_SIDE = {
	"Customer": CUSTOMER_GUEST_ROLE,
	"Partner": PARTNER_GUEST_ROLE,
}


def _set_role(user, role, should_have):
	user_doc = frappe.get_doc("User", user)
	user_doc.flags.ignore_permissions = True
	if should_have:
		user_doc.add_roles(role)
	else:
		user_doc.remove_roles(role)


def grant_company_role(doc, method=None):
	"""Fires on Customer Team Member creation (and the legacy Connect Customer Member/
	Connect Partner Member doctypes) — real company membership: roster visibility,
	admin-transfer eligibility, and thread-creation permission all still read this table
	directly (see connect.connect.permissions), unaffected by this role. This role only
	ever gates the messaging doctypes.

	Note: there is no partner-side equivalent yet — Partner Team Member (the public
	team/bio roster shown on a partner's profile) has no `user` field, so partner login
	accounts still need their Connect Partner role granted manually until a real
	partner-membership doctype exists."""
	_set_role(doc.user, _COMPANY_ROLE_BY_DOCTYPE[doc.doctype], True)


def revoke_company_role(doc, method=None):
	_set_role(doc.user, _COMPANY_ROLE_BY_DOCTYPE[doc.doctype], False)


def grant_thread_guest_role(doc, method=None):
	"""Fires on Connect Thread Member creation. A person added to a thread without being a
	real company member (e.g. a sales rep only there to chat) gets messaging access only —
	no roster visibility, no admin eligibility, no thread-creation permission. Deliberately
	a separate role from Connect Customer/Partner so the two populations never get
	conflated, even though both roles currently unlock the same four doctypes."""
	_set_role(doc.user, _GUEST_ROLE_BY_SIDE[doc.side], True)


def revoke_thread_guest_role(doc, method=None):
	"""Only strip the guest role if this was the user's last thread on that side — they
	may still be an active member of other threads."""
	still_has_other_thread = frappe.db.exists(
		"Connect Thread Member",
		{"user": doc.user, "side": doc.side, "name": ["!=", doc.name]},
	)
	_set_role(doc.user, _GUEST_ROLE_BY_SIDE[doc.side], bool(still_has_other_thread))
