import frappe

# The packs as the Starter Pack pages sell them: Core, Core + Manufacturing (an alternative to
# Core, not an add-on) and HR and Payroll. They replace the four packs seed_starter_packs made,
# which stay, switched off, as past orders link to them. "Not included" rows are kept for
# reference; the catalog doesn't send them to the pages.

SETUP = (
	"Setup",
	[
		(
			"Covers",
			"Your site and ERPNext instance, company and print settings, chart of accounts, fiscal year"
			" and initial system configuration.",
		)
	],
)
BUYING_SELLING = (
	"Buying and selling",
	[
		("Buying", "Material request, purchase order, purchase receipt, purchase invoice, payment"),
		("Selling", "Quotation, sales order, delivery note, sales invoice, payment"),
		(
			"Not included",
			"Loyalty programs, E-commerce integrations, Multi-level approval workflows, Supplier portal setup",
		),
	],
)
STOCK = ("Stock", [("Covers", "Stock transfer, stock reconciliation, stock ledger, stock balance")])
ACCOUNTING = (
	"Accounting",
	[
		(
			"Covers",
			"Journal entry, payment reconciliation, bank reconciliation, profit and loss, balance sheet,"
			" trial balance, accounts receivable, accounts payable",
		),
		("Not included", "Multiple entities, Cost centers, Budgeting, Multi-currency"),
	],
)
MANUFACTURING = (
	"Manufacturing",
	[
		("Covers", "Bill of materials, work order, stock entry, job card"),
		(
			"Not included",
			"Capacity planning, Production forecasting, Custom planning algorithms,"
			" PLC and machinery integrations",
		),
	],
)
DATA_USERS = (
	"Data and users",
	[
		(
			"Covers",
			"How to import items, customers and addresses with Excel templates, update stock and account"
			" opening balances, and create users with basic permissions.",
		)
	],
)
HRMS = (
	"HRMS",
	[
		(
			"Covers",
			"Employee master, leave policies, leave applications, attendance and shifts, expense claims,"
			" standard approval workflows, custom fields like skills and certifications",
		),
		("Not included", "Advanced KPI frameworks, Third-party integrations"),
	],
)
PAYROLL = (
	"Payroll",
	[
		("Covers", "Salary structures, payroll cycle, tax configuration for India, salary slips"),
		("Not included", "Multi-country payroll, Advanced scripted calculations"),
	],
)

# (pack_key, pack_name, price, total_hours, delivery_days, modules)
PACKS = [
	("core", "Core", 10000, 5, 30, [SETUP, BUYING_SELLING, STOCK, ACCOUNTING, DATA_USERS]),
	(
		"core-manufacturing",
		"Core + Manufacturing",
		20000,
		10,
		60,
		[SETUP, BUYING_SELLING, STOCK, ACCOUNTING, MANUFACTURING, DATA_USERS],
	),
	("hr-payroll", "HR and Payroll", 20000, 10, 30, [HRMS, PAYROLL]),
]

OLD_PACKS = ["accounts_sales_purchase_stock", "manufacturing", "hr", "payroll"]


def execute():
	"""Only creates packs that don't exist yet, so it never overwrites a price or section
	someone has since edited in Desk."""
	for pack_key, pack_name, price, total_hours, delivery_days, modules in PACKS:
		if frappe.db.exists("Starter Pack", pack_key):
			continue
		pack = frappe.new_doc("Starter Pack")
		pack.update(
			{
				"pack_key": pack_key,
				"pack_name": pack_name,
				"price": price,
				"total_hours": total_hours,
				"delivery_days": delivery_days,
				"is_active": 1,
			}
		)
		for module_name, sections in modules:
			for label, content in sections:
				pack.append("sections", {"module_name": module_name, "label": label, "content": content})
		pack.insert(ignore_permissions=True)

	for pack_key in OLD_PACKS:
		if frappe.db.exists("Starter Pack", pack_key):
			frappe.db.set_value("Starter Pack", pack_key, "is_active", 0)
