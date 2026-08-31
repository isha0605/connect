import frappe

CUSTOMER_ROLE = "Connect Customer"
PARTNER_ROLE = "Connect Partner"
CUSTOMER_GUEST_ROLE = "Connect Customer Guest"
PARTNER_GUEST_ROLE = "Connect Partner Guest"

_COMPANY_ROLE_BY_DOCTYPE = {
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
	"""Grants the messaging role tied to a real company membership row."""
	_set_role(doc.user, _COMPANY_ROLE_BY_DOCTYPE[doc.doctype], True)


def revoke_company_role(doc, method=None):
	_set_role(doc.user, _COMPANY_ROLE_BY_DOCTYPE[doc.doctype], False)


def grant_thread_guest_role(doc, method=None):
	"""Grants messaging-only access to someone added to a thread without a real company membership."""
	_set_role(doc.user, _GUEST_ROLE_BY_SIDE[doc.side], True)


def revoke_thread_guest_role(doc, method=None):
	"""Revokes the guest role only if this was the user's last thread on that side."""
	still_has_other_thread = frappe.db.exists(
		"Connect Thread Member",
		{"user": doc.user, "side": doc.side, "name": ["!=", doc.name]},
	)
	_set_role(doc.user, _GUEST_ROLE_BY_SIDE[doc.side], bool(still_has_other_thread))
