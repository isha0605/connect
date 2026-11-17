import frappe


def execute():
	"""Partner members moved from `is_admin` to one `access` field, and a firm now has one Owner.
	In each firm the earliest owner stays Owner, and every other owner becomes an Admin."""
	set_one_owner("Connect Partner Member", "partner")


def set_one_owner(doctype: str, company_field: str):
	"""Turns the `is_admin` rows of `doctype` into one Owner per company and Admins for the rest."""
	if not frappe.db.has_column(doctype, "is_admin"):
		return

	Member = frappe.qb.DocType(doctype)
	owners = (
		frappe.qb.from_(Member)
		.select(Member.name, Member[company_field].as_("company"))
		.where((Member.is_admin == 1) & (Member.is_removed == 0))
		.orderby(Member.creation)
	).run(as_dict=True)

	first_owners, other_owners = split_owners(owners)
	_set_access(Member, first_owners, "Owner")
	_set_access(Member, other_owners, "Admin")


def split_owners(owners: list[dict]) -> tuple[list[str], list[str]]:
	"""(The first owner of each company, every other owner), from owner rows oldest first."""
	first_owner_by_company = {}
	for row in owners:
		first_owner_by_company.setdefault(row["company"], row["name"])

	first_owners = list(first_owner_by_company.values())
	return first_owners, [row["name"] for row in owners if row["name"] not in first_owners]


def _set_access(Member, names: list[str], level: str):
	if names:
		frappe.qb.update(Member).set(Member.access, level).where(Member.name.isin(names)).run()
