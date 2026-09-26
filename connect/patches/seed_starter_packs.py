# Copyright (c) 2026
# For license information, please see license.txt

import frappe

# (pack_key, pack_name, price, total_hours, delivery_days, {module: [(label, content), ...]})
PACKS = [
	(
		"accounts_sales_purchase_stock",
		"Accounts, Sales, Purchase, Stock",
		10000,
		5,
		30,
		{
			"Accounting": [
				(
					"Masters",
					"Chart of Accounts, Fiscal Year, Financial Book, Accounting Period, Mode of Payment,"
					" GST and Tax Withholding Category (India)",
				),
				(
					"Transactions",
					"Payment / Receipt, Journal Voucher, Debit / Credit Note, Inter Bank,"
					" Bank Reconciliation, Payment Reconciliation",
				),
				(
					"Reports",
					"Balance Sheet, Trial Balance, Profit & Loss, Outstanding Receivable / Payable"
					" (detailed and summary), General Ledger, TDS Summary, Cash Flow",
				),
				("Settings", "Accounts Settings, GST Settings"),
				("Not included", "Multiple entities, Cost centers, Budgeting, Multi-currency"),
			],
			"Selling": [
				("Masters", "Customer list (addresses and contacts), Item master, Price list, Territory"),
				(
					"Transactions",
					"Quotation, Sales Order (with sales team and partner), Delivery Note, Sales Invoice,"
					" Accounting and inventory impact",
				),
				(
					"Reports",
					"Sales Analytics, Sales Order Trends, Inactive Customers, Item-wise Sales History,"
					" Pending SO Items, GSTR1, GST Registers",
				),
				("Settings", "Selling Settings"),
				("Not included", "Loyalty programs, E-commerce integrations"),
			],
			"Buying": [
				("Masters", "Supplier master (addresses and contacts), Terms and conditions, Payment terms"),
				(
					"Transactions",
					"Material Request, RFQ, Supplier Quotation (manual or portal), Purchase Order,"
					" Purchase Receipt, Purchase Invoice, Import purchase, Landed Cost Voucher",
				),
				(
					"Reports",
					"Purchase Analytics, Supplier reports, Item Purchase History, GST purchase registers,"
					" Reconciliation tools",
				),
				("Workflow", "Single-level Purchase Order approval"),
				("Not included", "Multi-level approval workflows, Supplier portal setup"),
			],
			"Inventory": [
				("Masters", "Item setup, Item Group, Warehouse, UOM, Batch, Serial No., Brand"),
				("Transactions", "Stock Entry, Stock Reconciliation"),
				("Reports", "Stock Ledger, Stock Balance, Reorder Level Report, Batch Expiry Status"),
				("Settings", "Stock Settings"),
			],
		},
	),
	(
		"manufacturing",
		"Manufacturing",
		10000,
		5,
		60,
		{
			"Manufacturing": [
				("Masters", "BOM, Operations, Workstation"),
				(
					"Transactions",
					"Work Orders (single and multi-level BOM), Job Card, Production stock entries",
				),
				(
					"Reports",
					"Work Order Summary, BOM Stock Report, Production Analytics, Job Card Summary,"
					" Work Order stock reports",
				),
				("Settings", "Manufacturing Settings"),
				(
					"Not included",
					"Capacity planning, Production forecasting, Custom planning algorithms,"
					" PLC and machinery integrations",
				),
			],
		},
	),
	(
		"hr",
		"HR",
		10000,
		5,
		30,
		{
			"HR": [
				(
					"Configuration",
					"Employee master, Leave management, Attendance and shifts, Leave policies,"
					" Expense claims, Standard approval workflows",
				),
				("Basic customization", "Adding fields to HRMS doctypes, like skills and certifications"),
				("Not included", "Advanced KPI frameworks, Third-party integrations"),
			],
		},
	),
	(
		"payroll",
		"Payroll",
		10000,
		5,
		30,
		{
			"Payroll": [
				(
					"Setup",
					"Salary structures, Payroll cycle, Standard tax configuration (India), Salary slip format",
				),
				("Not included", "Multi-country payroll, Advanced scripted calculations"),
			],
		},
	),
]

GST_RATE = 18


def execute():
	"""Seed the Starter Pack catalog. Only creates packs that don't exist yet, so
	it never overwrites a price or description someone has since edited in Desk."""
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
		for module_name, sections in modules.items():
			for label, content in sections:
				pack.append("sections", {"module_name": module_name, "label": label, "content": content})
		pack.insert(ignore_permissions=True)

	if not frappe.db.get_single_value("Starter Pack Settings", "gst_rate"):
		frappe.db.set_single_value("Starter Pack Settings", "gst_rate", GST_RATE)
