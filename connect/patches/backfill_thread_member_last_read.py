import frappe
from frappe.utils import now_datetime


def execute():
	"""New members start with no unread badge for pre-existing history — back-date
	last_read_at to now for every row that predates this field, same as a fresh
	'you've seen everything up to today' baseline."""
	if not frappe.db.table_exists("Connect Thread Member"):
		return

	# frappe.db.set_value's bulk-filter form doesn't translate the ["is", "not set"]
	# operator the way frappe.get_all does — it reaches the query builder as a literal
	# comparison and MySQL chokes trying to compare a datetime column against ''.
	# Resolving the rows via get_all first and updating them one at a time sidesteps that.
	names = frappe.get_all("Connect Thread Member", filters={"last_read_at": ["is", "not set"]}, pluck="name")
	now = now_datetime()
	for name in names:
		frappe.db.set_value("Connect Thread Member", name, "last_read_at", now, update_modified=False)
