import frappe
from frappe.utils.password import get_decrypted_password, set_encrypted_password

NEW_DOCTYPE = "Integration Settings"

# Old Single → {old field: new field}. Renaming a DocType doesn't move a Single's
# values or its encrypted passwords, so each is copied across by hand.
FIELD_MOVES = {
	"Press Settings": {"enabled": "press_enabled", "site_url": "press_site_url", "api_key": "press_api_key"},
	"Frappe School Settings": {
		"enabled": "school_enabled",
		"site_url": "school_site_url",
		"api_key": "school_api_key",
		"mrr_target": "mrr_target",
	},
}
SECRET_MOVES = {"Press Settings": "press_api_secret", "Frappe School Settings": "school_api_secret"}


def execute():
	"""Merges Press Settings and Frappe School Settings into Integration Settings."""
	for old_doctype, fields in FIELD_MOVES.items():
		_copy_values(old_doctype, fields)
		_copy_secret(old_doctype, SECRET_MOVES[old_doctype])
		_delete_old_doctype(old_doctype)


def _copy_values(old_doctype: str, fields: dict[str, str]):
	Singles = frappe.qb.DocType("Singles")
	stored = dict(
		frappe.qb.from_(Singles).select(Singles.field, Singles.value).where(Singles.doctype == old_doctype).run()
	)
	values = {new: stored[old] for old, new in fields.items() if stored.get(old) is not None}
	if values:
		frappe.db.set_single_value(NEW_DOCTYPE, values)


def _copy_secret(old_doctype: str, new_field: str):
	secret = get_decrypted_password(old_doctype, old_doctype, "api_secret", raise_exception=False)
	if secret:
		set_encrypted_password(NEW_DOCTYPE, NEW_DOCTYPE, secret, new_field)
		# The field itself holds a mask, as when the secret is saved from the form; readers
		# check it to tell whether a secret is set.
		frappe.db.set_single_value(NEW_DOCTYPE, new_field, "*" * len(secret))


def _delete_old_doctype(old_doctype: str):
	frappe.delete_doc("DocType", old_doctype, force=True, ignore_missing=True)
	frappe.db.delete("Singles", {"doctype": old_doctype})
	frappe.db.delete("__Auth", {"doctype": old_doctype})
