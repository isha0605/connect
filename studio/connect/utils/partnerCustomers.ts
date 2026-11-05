// What the partner's Customers pages share. A customer is a Partner Customer: someone who hired the
// partner on Connect (connect.api.partner_customers). Their sites and MRR come from Frappe Cloud,
// demo data until Connect can read them (is_demo).

// Wants to link until the team approves linking the customer's Frappe Cloud account.
export const WANTS_TO_LINK = "Wants to link"

export const STAGES = {
	[WANTS_TO_LINK]: { color: "var(--surface-amber-6)" },
	Onboarding: { color: "var(--surface-blue-7)" },
	Live: { color: "var(--surface-green-7)" },
	Churned: { color: "var(--surface-gray-5)" },
}

// Who pays Frappe Cloud. Set by Frappe Cloud; Connect only shows it.
export const BILLING = { Customer: "Customer pays", Partner: "Partner pays" }

const CURRENCY_FORMAT = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })
const DAY_YEAR = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" })

export const money = (amount) => CURRENCY_FORMAT.format(amount)
export const longDate = (value) => DAY_YEAR.format(new Date(String(value).replace(" ", "T")))
export const isWaitingToLink = (customer) => customer.stage === WANTS_TO_LINK

// A customer as the server sends it, in the shape the pages read.
export const toCustomer = (row) => ({
	id: row.name,
	name: row.company,
	contact: row.contact || "",
	email: row.email || "",
	phone: row.phone || "",
	industry: row.industry || "",
	country: row.country || "",
	source: row.source,
	billing: row.billing_by,
	stage: row.stage,
	project: row.project_name,
	owner: row.assigned_to || "",
	ownerName: row.assigned_to_name || "",
	linkedOn: row.linked_on,
	sites: row.sites || [],
	mrr: row.mrr || 0,
	isDemo: Boolean(row.is_demo),
})

// Approving the link moves the customer to Onboarding; the server checks who may.
export const approveLink = (call, id) =>
	call("connect.api.partner_customers.update_customer", { name: id, stage: "Onboarding" })
