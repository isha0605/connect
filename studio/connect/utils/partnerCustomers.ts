// The partner's Customers pages. Saved customers (connect.api.partner_customers: the ones who hired
// the partner on Connect) come first; below them is sample data copied from Pragati's prototype
// (src/data/partnerAccount.js, partnership.js and records.js) until sites, invoices and billing
// come from Frappe Cloud. Sample changes live in this module's state, and a refresh resets them.

import { reactive } from "vue"
import { FIRM, activityOf, copyText } from "@app/utils/partnerRecords"

const HOW_TO_LINK =
	"https://docs.frappe.io/partner-guide/frequently-asked-questions/how-to-link-partner-code-to-customer-account"

export const STAGES = {
	onboarding: { label: "Onboarding", color: "var(--surface-blue-7)" },
	live: { label: "Live", color: "var(--surface-green-7)" },
	churned: { label: "Churned", color: "var(--surface-gray-5)" },
}

export const BILLING = { customer: "Customer pays", partner: "Partner pays" }

// ── Money and dates ─────────────────────────────────────────────────────────
const CURRENCY_FORMAT = {
	INR: new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }),
	USD: new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }),
}
const DAY_YEAR = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" })

export const money = (amount, currency = FIRM.currency) => CURRENCY_FORMAT[currency].format(amount)
export const longDate = (iso) => DAY_YEAR.format(new Date(iso))

// ── Frappe Cloud invoices ───────────────────────────────────────────────────
const MONTHS = [
	{ key: "2026-10", label: "October 2026", open: true },
	{ key: "2026-09", label: "September 2026" },
	{ key: "2026-08", label: "August 2026" },
]
const RATE = { "2026-10": 84.1, "2026-09": 83.6, "2026-08": 83.4 }

// Per month: [customer, amount, currency, status]. Row order sets the invoice number.
const INVOICES = {
	"2026-10": [
		["Halcyon", 142400, "INR"], ["Kestrel", 96350, "INR"], ["Vantage", 980, "USD"],
		["Tessellate", 61200, "INR"], ["Meridian", 38900, "INR"], ["Orenda", 520, "USD"],
		["Silverpine", 24480, "INR"], ["Bluecrest", 6900, "INR"],
	],
	"2026-09": [
		["Halcyon", 148100, "INR"], ["Kestrel", 102760, "INR"], ["Vantage", 1040, "USD"],
		["Tessellate", 63880, "INR"], ["Meridian", 41200, "INR"], ["Orenda", 560, "USD"],
		["Silverpine", 26150, "INR"], ["Bluecrest", 7340, "INR", "unpaid"],
	],
	"2026-08": [
		["Halcyon", 139900, "INR"], ["Kestrel", 99420, "INR"], ["Vantage", 1010, "USD"],
		["Tessellate", 58700, "INR"], ["Meridian", 39600, "INR"], ["Orenda", 540, "USD"],
		["Silverpine", 25300, "INR"],
	],
}

const SITES = {
	Kestrel: [["kestrel.frappe.cloud", "Business"], ["kestrel-uat.frappe.cloud", "Starter"]],
	Meridian: [["meridian.frappe.cloud", "Business"]],
	Halcyon: [["halcyon-erp.frappe.cloud", "Business"], ["Dedicated server, Mumbai", "n2-standard-4"]],
	Silverpine: [["silverpine.frappe.cloud", "Business"]],
	Bluecrest: [["bluecrest.frappe.cloud", "Starter"]],
	Tessellate: [["tessellate.frappe.cloud", "Business"], ["tessellate-hr.frappe.cloud", "Starter"]],
	Orenda: [["orenda.frappe.cloud", "Business"]],
	Vantage: [["vantage-ops.frappe.cloud", "Business"]],
}

function invoiceFor(monthKey, customerName) {
	const rows = INVOICES[monthKey]
	const index = rows.findIndex(([name]) => name === customerName)
	if (index < 0) return null

	const [, amount, currency, status] = rows[index]
	const month = MONTHS.find((m) => m.key === monthKey)
	const number = String(410 + index * 37).padStart(4, "0")
	return {
		id: `${monthKey}-${index}`,
		month: month.label,
		invoice: `INV-${monthKey.slice(2).replace("-", "")}${number}`,
		amount,
		currency,
		converted: currency === FIRM.currency ? amount : Math.round(amount * RATE[monthKey]),
		status: month.open ? "accruing" : status || "paid",
	}
}

// The main site carries most of the bill; the others share 30% of it.
function sitesFor(customer, invoice) {
	if (!invoice) return []
	const sites = SITES[customer.name] || []
	const share = sites.length > 1 ? Math.round((invoice.amount * 0.3) / (sites.length - 1)) : 0
	return sites.map(([name, plan], index) => ({
		name,
		plan,
		amount: index === 0 ? invoice.amount - (sites.length - 1) * share : share,
		currency: invoice.currency,
		region: customer.region,
		status: customer.stage === "churned" ? "Suspended" : "Active",
		apps: index === 0 ? ["ERPNext", "Frappe HR"] : ["ERPNext"],
	}))
}

export const invoicesOf = (customer) =>
	MONTHS.map((m) => invoiceFor(m.key, customer.name)).filter(Boolean)

// ── Customers ───────────────────────────────────────────────────────────────
// `source` connect | own. `billing` customer | partner. `stage` onboarding | live | churned.
// `linked` is when the partner code was linked; `codeShared` is for one added by hand who hasn't.
const SEED_CUSTOMERS = [
	{ name: "Halcyon", contact: "Ritu Sharma", email: "ritu@halcyon.example", source: "own", billing: "customer", stage: "live", linked: "2023-04-11", region: "Mumbai", phone: "+91 98200 41120", industry: "Retail", country: "India", owner: "anuja-deshmukh" },
	{ name: "Kestrel", contact: "Arjun Nair", email: "arjun@kestrel.example", source: "connect", billing: "partner", stage: "live", linked: "2025-08-02", region: "Mumbai", project: "Stock and purchase on ERPNext", phone: "+91 98670 22145", industry: "Distribution", country: "India", owner: "farhan-qureshi" },
	{ name: "Vantage", contact: "Lena Fischer", email: "lena@vantage.example", source: "own", billing: "customer", stage: "live", linked: "2024-02-19", region: "Frankfurt", phone: "+49 69 2000 1144", industry: "Services", country: "Germany", owner: "anuja-deshmukh" },
	{ name: "Tessellate", contact: "Priya Menon", email: "priya@tessellate.example", source: "connect", billing: "customer", stage: "live", linked: "2025-11-20", region: "Mumbai", project: "Payroll on Frappe HR", phone: "+91 99300 51870", industry: "Services", country: "India", owner: "rahul-verma" },
	{ name: "Meridian", contact: "Vikram Shah", email: "vikram@meridian.example", source: "own", billing: "partner", stage: "live", linked: "2024-06-07", region: "Mumbai", phone: "+91 98190 33012", industry: "Manufacturing", country: "India", owner: "farhan-qureshi" },
	{ name: "Orenda", contact: "Omar Haddad", email: "omar@orenda.example", source: "own", billing: "customer", stage: "live", linked: "2025-01-15", region: "Bahrain", phone: "+973 3612 4471", industry: "Distribution", country: "Bahrain", owner: "anuja-deshmukh" },
	{ name: "Silverpine", contact: "Neha Kulkarni", email: "neha@silverpine.example", source: "own", billing: "partner", stage: "live", linked: "2024-09-30", region: "Mumbai", phone: "+91 98201 77310", industry: "Food and beverage", country: "India", owner: "farhan-qureshi" },
	{ name: "Bluecrest", contact: "Dev Patel", email: "dev@bluecrest.example", source: "own", billing: "customer", stage: "live", linked: "2025-05-12", region: "Mumbai", phone: "+91 98923 10046", industry: "Healthcare", country: "India", owner: "rahul-verma" },
	{ name: "Rivermark Textiles", contact: "Kavya Iyer", email: "kavya@rivermark.example", source: "connect", billing: "customer", stage: "onboarding", region: "Mumbai", project: "Manufacturing on ERPNext", phone: "+91 98336 90218", industry: "Manufacturing", country: "India", owner: "rahul-verma" },
	{ name: "Coastal Traders", contact: "Sameer Joshi", email: "sameer@coastal.example", source: "own", billing: "customer", stage: "onboarding", codeShared: "2026-10-21", region: "Mumbai", phone: "", industry: "Distribution", country: "India", owner: "rahul-verma" },
	{ name: "Granite Works", contact: "Rohan Das", email: "rohan@granite.example", source: "own", billing: "customer", stage: "churned", linked: "2023-09-01", region: "Mumbai", phone: "+91 98210 66503", industry: "Manufacturing", country: "India", owner: "farhan-qureshi" },
]

const toSlug = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-")

function withBilling(customer) {
	const invoice = invoiceFor(MONTHS[0].key, customer.name)
	return {
		...customer,
		id: toSlug(customer.name),
		mrr: invoice?.converted ?? 0,
		sites: sitesFor(customer, invoice),
		linkedSites: [],
		notes: "",
		billingSwitch: null,
	}
}

// A customer entered the partner code in Frappe Cloud. `matches` names one added by hand.
const SEED_REQUESTS = [
	{ id: "req-coastal", company: "Coastal Traders", contact: "Sameer Joshi", email: "sameer@coastal.example", at: "2026-10-29", matches: "coastal-traders",
		sites: [{ name: "coastal-traders.frappe.cloud", plan: "Business", region: "Mumbai" }] },
	{ id: "req-elmwood", company: "Elmwood Retail", contact: "Hannah Cole", email: "hannah@elmwood.example", at: "2026-10-27",
		sites: [{ name: "elmwood.frappe.cloud", plan: "Business", region: "London" }, { name: "elmwood-staging.frappe.cloud", plan: "Starter", region: "London" }] },
]

// One book shared by the list and the customer page, so a change on one shows on the other.
export const book = reactive({
	customers: SEED_CUSTOMERS.map(withBilling),
	removed: [],
	requests: SEED_REQUESTS,
	handled: {},
})

export const findCustomer = (id) => book.customers.find((c) => c.id === id) || null
export const isSampleCustomer = (id) => book.customers.some((c) => c.id === id && !c.isSaved)

// A saved customer in the shape the pages read. No sites, invoices or partner code yet.
export const toBookCustomer = (row) => ({
	id: row.name,
	isSaved: true,
	name: row.company,
	contact: row.contact || "",
	email: row.email || "",
	phone: row.phone || "",
	industry: row.industry || "",
	country: row.country || "",
	region: "",
	source: "connect",
	billing: "customer",
	stage: row.stage.toLowerCase(),
	project: row.project_name,
	owner: row.assigned_to || "",
	ownerName: row.assigned_to_name || "",
	mrr: 0,
	sites: [],
	linkedSites: [],
	notes: "",
	billingSwitch: null,
})

export async function loadSavedCustomers(call) {
	const data = await call("connect.api.partner_customers.list_customers")
	book.customers = [...data.customers.map(toBookCustomer), ...book.customers.filter((c) => !c.isSaved)]
}
export const pendingRequests = () => book.requests.filter((r) => !book.handled[r.id])
export const isLinked = (customer) => Boolean(customer.linked || customer.sites.length)

export const sitesOf = (customer) =>
	customer.sites.length
		? customer.sites
		: customer.linkedSites.map((site) => ({ ...site, status: "Active", apps: [] }))

export function addCustomer({ name, contact, email }) {
	const customer = withBilling({ name, contact, email, source: "own", billing: "customer", stage: "onboarding", owner: "", phone: "", industry: "", country: "" })
	book.customers.unshift(customer)
	return customer
}

export function editCustomer(id, changes) {
	Object.assign(findCustomer(id), changes)
}

export function removeCustomer(id) {
	const index = book.customers.findIndex((c) => c.id === id)
	if (index >= 0) book.removed.push({ index, customer: book.customers.splice(index, 1)[0] })
}

export function restoreCustomer(id) {
	const entry = book.removed.find((r) => r.customer.id === id)
	if (!entry) return
	book.customers.splice(entry.index, 0, entry.customer)
	book.removed = book.removed.filter((r) => r !== entry)
}

// Approving links the request's sites: to the matching customer added by hand, or to a new one.
export function handleRequest(request, outcome) {
	book.handled[request.id] = outcome
	if (outcome !== "approved") return

	const match = request.matches && findCustomer(request.matches)
	const linked = { linked: "2026-10-30", codeShared: null, linkedSites: request.sites }
	if (match) Object.assign(match, linked)
	else Object.assign(addCustomer({ name: request.company, contact: request.contact, email: request.email }), linked, { id: request.id.replace("req-", "") })
}

export function undoRequest(request) {
	delete book.handled[request.id]
}

// Oldest first. A customer with no recorded history still has the moment it linked.
export function customerActivity(customer) {
	const list = activityOf(customer.id)
	if (list.length || !customer.linked) return list
	const linkedAt = new Date(`${customer.linked}T10:00:00`).getTime()
	return [{ id: "linked", at: linkedAt, by: customer.contact || customer.name, kind: "note", text: "linked their sites to your partner code" }]
}

export const copyPartnerCode = (toast) => copyText(FIRM.code, toast, "Code copied")

export const sharePartnerCode = (toast) =>
	copyText(
		`To link your Frappe Cloud account with ${FIRM.name}, enter our partner code ${FIRM.code} in Frappe Cloud. How: ${HOW_TO_LINK}`,
		toast,
		"Message copied",
	)
