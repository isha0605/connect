import frappe
from frappe import _

from connect.permissions import _has_full_access

# What the partner side sees in place of the customer's people until the customer is revealed
# (Connect Thread.is_customer_revealed). One stand-in for all of them: the company is the party.
ANONYMOUS_USER = "anonymous-customer"


def anonymous_company() -> str:
	return _("Anonymous company")


def hidden_threads(threads: list[str], user: str | None = None) -> set[str]:
	"""Of these threads, the ones where the user writes for the partner and the customer is
	still anonymous to them."""
	user = user or frappe.session.user
	if not threads or _has_full_access(user):
		return set()
	Member = frappe.qb.DocType("Connect Thread Member")
	Thread = frappe.qb.DocType("Connect Thread")
	rows = (
		frappe.qb.from_(Member)
		.join(Thread)
		.on(Thread.name == Member.thread)
		.select(Member.thread)
		.where(Member.user == user)
		.where(Member.side == "Partner")
		.where(Thread.is_customer_revealed == 0)
		.where(Member.thread.isin(list(threads)))
		.run(pluck=True)
	)
	return set(rows)


def hides_customer(thread: str, user: str | None = None) -> bool:
	return thread in hidden_threads([thread], user)


def customer_users(thread: str) -> set[str]:
	"""Everyone who has been on the thread's customer side, removed members included."""
	return set(
		frappe.get_all("Connect Thread Member", filters={"thread": thread, "side": "Customer"}, pluck="user")
	)


def mask_message(row: dict, customers: set[str]) -> dict:
	"""The message as the partner side may see it while the customer is anonymous."""
	for field in ("sender", "pinned_by"):
		if row.get(field) in customers:
			row[field] = ANONYMOUS_USER
	if row.get("message_type") == "Requirement" and row.get("content"):
		row["content"] = mask_requirement(row["content"])
	return row


def mask_requirement(content: str) -> str:
	card = frappe.parse_json(content) or {}
	card.pop("company_name", None)
	return frappe.as_json(card)


def anonymous_profile() -> dict:
	return {"name": ANONYMOUS_USER, "full_name": anonymous_company(), "user_image": None}
