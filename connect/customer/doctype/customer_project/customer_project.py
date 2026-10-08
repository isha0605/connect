# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from connect.customer.doctype.customer.customer import get_customer_for_user

# What the questionnaire's verdict ("packs" / "custom", from recommend() in
# studio/connect/utils/recommendation.ts) is stored as.
VERDICTS = {"packs": "Starter Pack", "custom": "Custom"}


class CustomerProject(Document):
	"""A customer's project before anything is bought: what they named it, when they need
	it live, and their questionnaire answers — which decide whether we point them at a
	Starter Pack or a custom implementation. Once paid for, the Starter Pack Order is the
	project; this stays the record of how they got there."""

	def before_insert(self):
		self.user = frappe.session.user


def get_own_project(name):
	doc = frappe.get_doc("Customer Project", name)
	if doc.user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return doc


def save_project(
	project_name, go_live=None, operations=None, problems=None, verdict=None, name=None, systems=None,
	industries=None, company_size=None,
):
	"""Create a draft project, or update one when `name` is given ("Change my answers").
	Industries and company size come only from the Contact partners questions, so they're
	left alone when not given."""
	project_name = (project_name or "").strip()
	if not project_name:
		frappe.throw(_("Give the project a name."))

	doc = get_own_project(name) if name else frappe.new_doc("Customer Project")
	doc.update(
		{
			"project_name": project_name,
			"go_live": go_live or "",
			"operations": operations or "",
			"systems": frappe.as_json(frappe.parse_json(systems) or []),
			"problems": frappe.as_json(frappe.parse_json(problems) or []),
			"verdict": VERDICTS.get(verdict, ""),
		}
	)
	if industries is not None:
		doc.industries = frappe.as_json(frappe.parse_json(industries) or [])
	if company_size is not None:
		doc.company_size = (company_size or "").strip()
	doc.save(ignore_permissions=True)
	return project_dict(doc)


def get_project(name):
	return project_dict(get_own_project(name))


def share_requirements(name, budget=None, description=None):
	"""Keep the custom-implementation brief on the project and send it to every partner its
	criteria match, as the customer's own Requirement card."""
	budget = (budget or "").strip()
	description = (description or "").strip()
	if not budget:
		frappe.throw(_("Pick a budget range."))
	if not description:
		frappe.throw(_("Tell partners what you want built."))

	doc = get_own_project(name)
	if doc.status in ("Shared", "Hired", "Completed"):
		frappe.throw(_("These requirements have already been sent."))
	customer = get_customer_for_user(doc.user)
	if not customer:
		frappe.throw(_("Sign in with your company account to send this to partners."))

	doc.budget = budget
	doc.description = description
	sent = send_to_partners(doc, customer)
	if not sent:
		frappe.throw(_("No partners match these criteria yet. Try widening them."))

	doc.status = "Shared"
	doc.shared_on = frappe.utils.now_datetime()
	doc.shared_count = sent
	doc.save(ignore_permissions=True)
	return project_dict(doc)


# ---- Sending the brief ----
# The answers as the custom page words them (GO_LIVE_CRITERIA, OPERATION_OPTIONS and
# PROBLEM_OPTIONS in studio/connect/utils/recommendation.ts) — the card is written here, so
# what a partner reads can't be anything the browser made up.

GO_LIVE_LABELS = {
	"within_month": "As soon as possible",
	"one_to_three_months": "Live within three months",
	"three_to_six_months": "Live within six months",
	"no_deadline": "No fixed deadline",
}
OPERATION_LABELS = {
	"spreadsheets": "Spreadsheets, email and paper",
	"accounting_software": "Accounting software, everything else by hand",
	"disconnected_systems": "Several systems that do not talk to each other",
	"outgrown_erp": "An ERP that no longer fits how we work",
}
PROBLEM_LABELS = {
	"manual_work": "Manual work that should be automated",
	"hr_by_hand": "Payroll, leave and attendance are run by hand",
	"disconnected_systems": "Systems that do not talk to each other",
	"slow_close": "Month-end close and reporting take too long",
	"stock_visibility": "No reliable view of stock and orders",
	"tools_dont_fit": "Our tools cannot handle how we actually work",
	"outgrowing": "We are outgrowing what we have",
}


def send_to_partners(doc, customer):
	"""Sends the brief to each matching partner's admin, as the customer's own Requirement card
	in their thread with that partner, and returns how many got it."""
	from connect.customer.doctype.starter_pack_order.implementation import get_or_open_thread
	from connect.permissions import _get_partner_admin

	criteria = normalize_criteria(frappe.parse_json(doc.criteria) or {})
	card = frappe.as_json(requirement_card(doc, customer))
	sent = 0
	for partner in _partners_in_scope():
		if not _matches(partner, criteria):
			continue
		if not _get_partner_admin(partner.name):
			continue  # nobody on their side to read it
		thread = get_or_open_thread(customer, partner.name, doc.user)
		frappe.get_doc(
			{
				"doctype": "Connect Message",
				"thread": thread,
				"sender": doc.user,
				"message_type": "Requirement",
				"content": card,
			}
		).insert(ignore_permissions=True)
		_await_quote(doc.name, partner.name, thread)
		sent += 1
	return sent


def _await_quote(project, partner, thread):
	"""Remembers that this partner has the brief, so their quote can be matched to it."""
	if frappe.db.exists("Project Quote", {"customer_project": project, "partner": partner}):
		return
	frappe.get_doc(
		{"doctype": "Project Quote", "customer_project": project, "partner": partner, "thread": thread}
	).insert(ignore_permissions=True)


def requirement_card(doc, customer):
	"""The same Requirement card a customer sends from Messaging: their saved requirement and
	company, with this project's name, brief and answers on top."""
	from connect.customer.doctype.requirement.requirement import get_requirement_snapshot

	company = frappe.db.get_value("Customer", customer, ["customer_name", "industry", "country"], as_dict=True) or {}
	criteria = normalize_criteria(frappe.parse_json(doc.criteria) or {})
	systems = frappe.parse_json(doc.systems) or []
	problems = frappe.parse_json(doc.problems) or []
	industries = frappe.parse_json(doc.industries) or []

	situation = OPERATION_LABELS.get(doc.operations, "")
	if systems:
		situation = "; ".join(filter(None, [situation, _("uses {0}").format(", ".join(systems))]))
	if problems:
		fix = ", ".join(PROBLEM_LABELS.get(p, p).lower() for p in problems)
		situation = ". ".join(filter(None, [situation, _("Wants fixed: {0}").format(fix)]))

	card = get_requirement_snapshot(customer) or {}
	card.update(
		{
			"project_name": doc.project_name,
			"company_name": card.get("company_name") or company.get("customer_name"),
			# what they picked themselves, before anything saved for the company
			"industry": ", ".join(industries) or card.get("industry") or company.get("industry"),
			"country": card.get("country") or company.get("country"),
			"company_size": doc.company_size or card.get("company_size"),
			"description": doc.description,
			"looking_for": _("Custom implementation: {0}").format(doc.description),
			"current_situation": situation or card.get("current_situation"),
			"timeline": GO_LIVE_LABELS.get(doc.go_live, "") or card.get("timeline"),
			"delivery_preference": ", ".join(WORK_MODES[w]["label"] for w in criteria["work"])
			or card.get("delivery_preference"),
			"budget": doc.budget,
			"partner_brief": partner_brief(criteria),
		}
	)
	return card


def partner_brief(criteria):
	"""Who the brief went to, in a sentence: "A partner based in India who offers services for
	Manufacturing. Any tier, remote or on site." """
	def either(values):
		return values[0] if len(values) == 1 else _("{0} or {1}").format(", ".join(values[:-1]), values[-1])

	place = criteria["cities"] or criteria["countries"]
	who = ""
	if place:
		who += " " + _("based in {0}").format(either(place))
	if criteria["industries"]:
		who += " " + _("who offers services for {0}").format(either(criteria["industries"]))
	tier = _("{0} tier").format(either(criteria["tiers"])) if criteria["tiers"] else _("Any tier")
	work = {("onsite",): _("on site"), ("remote",): _("remote")}.get(tuple(criteria["work"]), _("remote or on site"))
	# "A partner." says nothing on its own, so it's only there with a place or industry
	return (_("A partner") + who + ". " if who else "") + f"{tier}, {work}."


def delete_project(name):
	doc = get_own_project(name)
	frappe.delete_doc("Customer Project", doc.name, ignore_permissions=True)


def project_dict(doc):
	from connect.customer.doctype.starter_pack_order.starter_pack_order import with_timezone

	return {
		"name": doc.name,
		"project_name": doc.project_name,
		"status": doc.status,
		"verdict": {v: k for k, v in VERDICTS.items()}.get(doc.verdict, ""),
		"go_live": doc.go_live,
		"operations": doc.operations,
		"systems": frappe.parse_json(doc.systems) or [],
		"problems": frappe.parse_json(doc.problems) or [],
		"criteria": normalize_criteria(frappe.parse_json(doc.criteria) or {}),
		"shared_count": doc.shared_count or 0,
		"shared_on": with_timezone(doc.shared_on),
		"budget": doc.budget,
		"description": doc.description,
		"created_on": with_timezone(doc.creation),
		"order": booked_order(doc.name),
		"hired": hired_partner(doc),
		"hire_reason": doc.hire_reason,
		"done_tasks": frappe.parse_json(doc.done_tasks) or [],
		**quote_counts(doc.name),
	}


# Paying states a Starter Pack Order stays a project in (mirrors my_orders()).
PAID = ("Paid", "Partially Refunded", "Refunded")


def booked_order(project):
	"""The paid Starter Pack Order bought for this project, if any. From then on the order
	is the project: it shows the implementation steps under the project's name."""
	return frappe.db.get_value(
		"Starter Pack Order", {"customer_project": project, "payment_status": ["in", PAID]}, "name"
	)


def my_projects():
	"""The caller's draft projects, newest first, in the Projects page's row shape."""
	if frappe.session.user == "Guest":
		return []
	from connect.customer.doctype.starter_pack_order.starter_pack_order import FRAPPE_LOGO

	names = frappe.get_all(
		"Customer Project", filters={"user": frappe.session.user}, pluck="name", order_by="creation desc"
	)
	# a booked project is listed once, as its order
	booked = set(
		frappe.get_all(
			"Starter Pack Order",
			filters={"customer_project": ["in", names or [""]], "payment_status": ["in", PAID]},
			pluck="customer_project",
		)
	)
	names = [name for name in names if name not in booked]
	rows = []
	for name in names:
		project = project_dict(frappe.get_doc("Customer Project", name))
		hired = project["hired"]  # once hired, the row shows the partner, like a booked pack
		rows.append(
			{
				"kind": "project",
				"project": project["name"],
				"project_title": project["project_name"],
				"status": project["status"],
				"verdict": project["verdict"],
				"quotes": project["quotes"],
				"shortlisted": project["shortlisted"],
				"hired": bool(hired),
				"partner_name": hired["partner_name"] if hired else "Frappe",
				"partner_logo": hired["logo"] if hired else FRAPPE_LOGO,
				"created_on": project["created_on"],
			}
		)
	return rows


# ---- Partner criteria ("Edit criteria" on the custom implementation page) ----
# Which partners the brief goes to. Countries (where the partner is based), industries
# (what they serve), cities and tiers narrow to any of the picked values;
# "how do you want to work" maps onto the partners' delivery modes, where Hybrid counts
# for both. Nothing picked in a group means no limit there. The go-live answer is edited
# alongside but doesn't filter partners — it belongs to the project's answers.
WORK_MODES = {
	"onsite": {"label": "Will come to us", "modes": ("Onsite", "Hybrid")},
	"remote": {"label": "Remote is fine", "modes": ("Remote", "Hybrid")},
}


def normalize_criteria(criteria):
	criteria = criteria or {}
	return {
		"countries": [c for c in criteria.get("countries") or [] if c],
		"industries": [i for i in criteria.get("industries") or [] if i],
		"cities": [c for c in criteria.get("cities") or [] if c],
		"tiers": [t for t in criteria.get("tiers") or [] if t],
		"work": [w for w in criteria.get("work") or [] if w in WORK_MODES],
	}


def _partners_in_scope():
	from connect.partner.doctype.partner.partner import BASE_PARTNER_FILTERS

	rows = frappe.get_all("Partner", filters=BASE_PARTNER_FILTERS, fields=["name", "city", "tier", "country", "industry"])
	modes = {}
	for m in frappe.get_all(
		"Partner Delivery Mode",
		filters={"parenttype": "Partner", "parent": ["in", [r.name for r in rows] or [""]]},
		fields=["parent", "delivery_mode"],
	):
		modes.setdefault(m.parent, set()).add(m.delivery_mode)
	for r in rows:
		r.modes = modes.get(r.name, set())
	return rows


def _matches(partner, criteria):
	if not _in_reach(partner, criteria):
		return False
	if criteria["cities"] and (partner.city or "") not in criteria["cities"]:
		return False
	if criteria["tiers"] and (partner.tier or "") not in criteria["tiers"]:
		return False
	if criteria["work"]:
		wanted = {m for w in criteria["work"] for m in WORK_MODES[w]["modes"]}
		if not (partner.modes & wanted):
			return False
	return True


def _in_reach(partner, criteria):
	"""The answers from the questions themselves (where, and what industry), which the Edit
	criteria chips then narrow within."""
	if criteria["countries"] and (partner.country or "") not in criteria["countries"]:
		return False
	if criteria["industries"] and (partner.industry or "") not in criteria["industries"]:
		return False
	return True


def partner_criteria(criteria=None):
	"""The Edit criteria chips with how many partners each covers, and how many match the
	given criteria. Chip counts are per option on their own, as in the prototype, among the
	partners in the chosen countries and industries."""
	criteria = normalize_criteria(frappe.parse_json(criteria) or {})
	partners = [p for p in _partners_in_scope() if _in_reach(p, criteria)]

	cities, tiers = {}, {}
	for p in partners:
		if p.city:
			cities[p.city] = cities.get(p.city, 0) + 1
		if p.tier:
			tiers[p.tier] = tiers.get(p.tier, 0) + 1
	tier_order = ["Gold", "Silver", "Bronze"]

	return {
		"cities": [{"value": c, "count": n} for c, n in sorted(cities.items())],
		"tiers": [{"value": t, "count": tiers[t]} for t in tier_order if t in tiers],
		"work": [
			{"value": key, "label": spec["label"], "count": sum(1 for p in partners if p.modes & set(spec["modes"]))}
			for key, spec in WORK_MODES.items()
		],
		"total": sum(1 for p in partners if _matches(p, criteria)),
	}


def matching_partner_count(criteria):
	criteria = normalize_criteria(criteria)
	return sum(1 for p in _partners_in_scope() if _matches(p, criteria))


def save_criteria(name, criteria=None, go_live=None):
	doc = get_own_project(name)
	doc.criteria = frappe.as_json(normalize_criteria(frappe.parse_json(criteria) or {}))
	if go_live is not None:
		doc.go_live = go_live
	doc.save(ignore_permissions=True)
	return project_dict(doc)


# ---- Quotes: partners' replies to a shared brief ----
# Quoted is a reply nobody has decided on yet ("Others" on the project page), Interested is
# shortlisted, and Not Interested drops out of both lists (Undo puts it back).
QUOTE_STATUSES = ("Quoted", "Interested", "Not Interested")


def quote_counts(project):
	statuses = frappe.get_all("Project Quote", filters={"customer_project": project}, pluck="status")
	return {
		"quotes": sum(1 for s in statuses if s in ("Quoted", "Interested")),
		"shortlisted": sum(1 for s in statuses if s == "Interested"),
	}


def list_quotes(name):
	"""The project's quotes for the Interested / Others lists, cheapest first."""
	doc = get_own_project(name)
	rows = frappe.get_all(
		"Project Quote",
		filters={"customer_project": doc.name, "status": ["in", ("Quoted", "Interested")]},
		fields=["name", "partner", "thread", "status", "amount", "timeline_weeks", "note"],
		order_by="amount asc",
	)
	partners = {
		p.name: p
		for p in frappe.get_all(
			"Partner",
			filters={"name": ["in", [r.partner for r in rows] or [""]]},
			fields=["name", "partner_name", "tier", "city", "logo", "verification_status"],
		)
	}
	for r in rows:
		p = partners.get(r.partner) or frappe._dict()
		r.update(
			{
				"partner_name": p.partner_name or r.partner,
				"tier": p.tier,
				"city": p.city,
				"logo": p.logo,
				"verified": p.verification_status == "Verified",
			}
		)
	return rows


def set_quote_status(quote, status):
	if status not in QUOTE_STATUSES:
		frappe.throw(_("Pick Interested or Not interested."))
	row = frappe.get_doc("Project Quote", quote)
	get_own_project(row.customer_project)  # only the project's owner decides
	if row.status == "Awaiting":
		frappe.throw(_("This partner hasn't quoted yet."))
	if row.status == "Hired":
		frappe.throw(_("You have already hired this partner."))
	row.db_set("status", status)
	return quote_counts(row.customer_project)


# ---- Hiring: step 1 (choosing a partner) ends, step 2 (set up hosting) begins ----
HIRE_REASONS = ("Price", "Timeline", "Their profile", "How they replied")

# Step 2's tasks, all optional; the page knows their labels and links.
HOSTING_TASKS = ("fc-login", "fc-code", "fc-link")


def hire_partner(quote):
	"""Hire the partner behind a quote: the project moves to step 2 with them as its partner."""
	row = frappe.get_doc("Project Quote", quote)
	doc = get_own_project(row.customer_project)
	if doc.status != "Shared":
		frappe.throw(_("This project already has a partner."))
	if row.status not in ("Quoted", "Interested"):
		frappe.throw(_("Only a partner who has quoted can be hired."))
	row.db_set("status", "Hired")
	doc.update({"status": "Hired", "partner": row.partner, "hired_quote": row.name, "hired_on": frappe.utils.now()})
	doc.save(ignore_permissions=True)
	return project_dict(doc)


def set_hire_reason(name, reason=None):
	"""Why they picked this partner ("Why Tridots Tech?"). Skipping leaves it blank."""
	doc = get_own_project(name)
	if not doc.partner:
		frappe.throw(_("Hire a partner first."))
	if reason and reason not in HIRE_REASONS:
		frappe.throw(_("Pick one of the reasons."))
	doc.db_set("hire_reason", reason or "")


def complete_task(name, task):
	doc = get_own_project(name)
	if task not in HOSTING_TASKS:
		frappe.throw(_("Unknown task."))
	if doc.status != "Hired":
		frappe.throw(_("Hire a partner first."))
	done = frappe.parse_json(doc.done_tasks) or []
	if task not in done:
		doc.db_set("done_tasks", frappe.as_json(done + [task]))
	return project_dict(doc)


def complete_project(name):
	doc = get_own_project(name)
	if doc.status != "Hired":
		frappe.throw(_("Only a project with a partner can be completed."))
	doc.update({"status": "Completed", "completed_on": frappe.utils.now()})
	doc.save(ignore_permissions=True)
	return project_dict(doc)


def referral_code(project, partner):
	"""The partner's Frappe Cloud referral code for this project. Partners don't have one on
	file yet, so it's derived the way the prototype does: stable for each project and partner."""
	n = 7
	for ch in f"{partner}{project}":
		n = (n * 33 + ord(ch)) % 99999
	return f"{partner[:3].upper()}-{n:05d}"


def hired_partner(doc):
	"""Who was hired and on what quote, for the Partner panel and step 2."""
	if not doc.partner:
		return None
	p = frappe.db.get_value("Partner", doc.partner, ["partner_name", "logo", "logo_icon"], as_dict=True) or {}
	quote = frappe.db.get_value("Project Quote", doc.hired_quote, ["amount", "timeline_weeks", "thread"], as_dict=True) or {}
	return {
		"partner": doc.partner,
		"partner_name": p.get("partner_name") or doc.partner,
		"logo": p.get("logo_icon") or p.get("logo"),
		"amount": quote.get("amount"),
		"timeline_weeks": quote.get("timeline_weeks"),
		"thread": quote.get("thread"),
		"referral_code": referral_code(doc.name, doc.partner),
	}


# ---- Demo: partners reply with quotes ----
# Partners have no way to send a quote yet, so the project page has a button that makes
# every partner still Awaiting reply with one, posted in their thread as a Quote message.
# Amounts fall within the customer's budget range; the same quote always gets the same
# numbers.
BUDGET_RANGES = {
	"Under ₹5 lakh": (250000, 500000),
	"₹5 to 15 lakh": (600000, 1400000),
	"₹15 to 40 lakh": (1600000, 3800000),
	"Over ₹40 lakh": (4200000, 7500000),
	"Not decided yet": (500000, 1200000),
}
QUOTE_NOTES = (
	"We would phase this: the core modules live first, then the parts that need integration work. "
	"The figure is for both phases.",
	"This covers setup, data migration from your current system and two weeks of support after go-live.",
	"We have done three rollouts like this in your industry. The quote includes training for your team.",
	"Fixed price for the scope in your brief. Anything beyond it we would estimate separately.",
	"Includes a discovery week up front, so the plan is agreed before any configuration starts.",
)


def simulate_quotes(name):
	import random

	doc = get_own_project(name)
	if doc.status != "Shared":
		frappe.throw(_("Share the requirements first."))
	_backfill_quote_rows(doc)

	low, high = BUDGET_RANGES.get(doc.budget, BUDGET_RANGES["Not decided yet"])
	sent = 0
	for row in frappe.get_all(
		"Project Quote", filters={"customer_project": doc.name, "status": "Awaiting"}, pluck="name"
	):
		quote = frappe.get_doc("Project Quote", row)
		sender = _partner_sender(quote)
		if not sender:
			continue
		rng = random.Random(quote.name)
		quote.amount = round((low + rng.random() * (high - low)) / 12500) * 12500
		quote.timeline_weeks = rng.randint(6, 10)
		quote.note = rng.choice(QUOTE_NOTES)
		message = frappe.get_doc(
			{
				"doctype": "Connect Message",
				"thread": quote.thread,
				"sender": sender,
				"message_type": "Quote",
				"content": frappe.as_json(
					{
						"quote": quote.name,
						"project": doc.name,
						"amount": quote.amount,
						"weeks": quote.timeline_weeks,
						"note": quote.note,
					}
				),
			}
		).insert(ignore_permissions=True)
		quote.quote_message = message.name
		quote.status = "Quoted"
		quote.quoted_on = frappe.utils.now_datetime()
		quote.save(ignore_permissions=True)
		sent += 1
	return {"sent": sent, **quote_counts(doc.name)}


def _partner_sender(quote):
	"""Someone on the partner's side of the thread to send it as: their admin if they're in it."""
	from connect.permissions import _get_partner_admin

	admin = _get_partner_admin(quote.partner)
	members = frappe.get_all(
		"Connect Thread Member",
		filters={"thread": quote.thread, "side": "Partner", "is_removed": 0},
		pluck="user",
	)
	return admin if admin in members else (members[0] if members else None)


def _backfill_quote_rows(doc):
	"""Briefs shared before quotes were tracked: their partners are the threads that got this
	project's Requirement card, sent by its owner when it was shared."""
	if frappe.db.exists("Project Quote", {"customer_project": doc.name}) or not doc.shared_on:
		return
	window = [
		frappe.utils.add_to_date(doc.shared_on, minutes=-5),
		frappe.utils.add_to_date(doc.shared_on, minutes=5),
	]
	looking_for = _("Custom implementation: {0}").format(doc.description)
	for m in frappe.get_all(
		"Connect Message",
		filters={"sender": doc.user, "message_type": "Requirement", "creation": ["between", window]},
		fields=["thread", "content"],
	):
		if (frappe.parse_json(m.content or "{}") or {}).get("looking_for") != looking_for:
			continue
		partner = frappe.db.get_value("Connect Thread", m.thread, "partner")
		if partner:
			_await_quote(doc.name, partner, m.thread)
