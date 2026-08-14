def execute():
	"""Superseded by connect.patches.split_thread_guest_access_from_company_membership.
	This patch used to make every thread-only participant a full Connect Customer
	Member/Connect Partner Member row to fix a permission outage — that conflated
	'real company member' with 'was added to one chat thread', which is wrong (see the
	superseding patch for the fix and the full explanation). Left as a no-op, not deleted,
	so its Patch Log entry and history stay intact; a fresh site running this patch now
	does nothing, and the correct behavior lives in connect.connect.roles instead."""
	pass
