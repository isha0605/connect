// The partner's Customers, as Frappe CRM's list: quick filters with Refresh, Filter, Sort and
// Columns, a full-width table and a footer with page size and count. Customers who want to link
// come first, as they wait on the team: approving the link moves them to Onboarding. Sites and MRR
// are demo data until they come from Frappe Cloud.

import { computed, ref } from "vue"
import { toast } from "frappe-ui"
import { BILLING, STAGES, approveLink, isWaitingToLink, money, toCustomer } from "@app/utils/partnerCustomers"
import { matchesFilters } from "@app/utils/listFilters"
import { startTracking } from "@app/utils/tracking"

const STAGE_CHOICES = Object.keys(STAGES).map((stage) => ({ label: stage, value: stage }))
const STAGE_OPTIONS = [{ label: "Any stage", value: "" }, ...STAGE_CHOICES]
const BILLING_CHOICES = Object.entries(BILLING).map(([value, label]) => ({ label, value }))
const PAYS_OPTIONS = [{ label: "Anyone pays", value: "" }, ...BILLING_CHOICES]
const SORTS = [
	{ value: "name", label: "Name" },
	{ value: "mrr", label: "MRR" },
	{ value: "linked", label: "Linked" },
]
const COLUMNS = [
	{ key: "contact", label: "Contact", width: "minmax(0,1fr)" },
	{ key: "stage", label: "Stage", width: "8rem" },
	{ key: "pays", label: "Who pays", width: "8rem" },
	{ key: "owner", label: "Owner", width: "10rem" },
	{ key: "sites", label: "Sites", width: "5rem" },
	{ key: "mrr", label: "MRR", width: "7rem" },
]
const PAGE_SIZES = [20, 50, 100].map((n) => ({ label: String(n), value: n }))

// What the Filter button can filter on. Owners are whoever owns a customer on the list.
function filterFields(owners) {
	return [
		{ fieldname: "name", label: "Customer", type: "text" },
		{ fieldname: "contact", label: "Contact", type: "text" },
		{ fieldname: "stage", label: "Stage", type: "select", options: STAGE_CHOICES },
		{ fieldname: "billing", label: "Who pays", type: "select", options: BILLING_CHOICES },
		{ fieldname: "ownerName", label: "Owner", type: "select", options: owners.map((name) => ({ label: name, value: name })) },
	]
}

const bySort = {
	name: (a, b) => a.name.localeCompare(b.name),
	mrr: (a, b) => b.mrr - a.mrr,
	linked: (a, b) => String(b.linkedOn || "").localeCompare(String(a.linkedOn || "")),
}

const matchesQuery = (query, ...fields) => !query || fields.some((field) => field?.toLowerCase().includes(query))

export default function setup(context) {
	startTracking(context)

	const query = ref("")
	const stage = ref("")
	const pays = ref("")
	const filters = ref([])
	const sort = ref("name")
	const shownColumns = ref(COLUMNS.map((c) => c.key))
	const pageSize = ref(20)
	const refreshing = ref(false)
	const customers = ref([])

	const isShown = (key) => shownColumns.value.includes(key)
	const sortMenu = computed(() =>
		SORTS.map((o) => ({ label: o.label, selected: sort.value === o.value, onClick: () => (sort.value = o.value) })),
	)
	const columnsMenu = computed(() =>
		COLUMNS.map((c) => ({ label: c.label, selected: isShown(c.key), onClick: () => toggleColumn(c.key) })),
	)
	const sortLabel = computed(() => SORTS.find((o) => o.value === sort.value).label)

	function toggleColumn(key) {
		shownColumns.value = isShown(key) ? shownColumns.value.filter((k) => k !== key) : [...shownColumns.value, key]
	}

	const gridColumns = computed(() => ({
		base: ["minmax(0,1fr)", "auto", "2rem"],
		md: ["minmax(0,1.5fr)", ...COLUMNS.filter((c) => isShown(c.key)).map((c) => c.width), "2rem"],
	}))

	// A Member opening /customers by URL sees why instead of an empty list.
	const noAccess = ref("")
	async function load() {
		try {
			const data = await context.call("connect.api.partner_customers.list_customers")
			customers.value = data.customers.map(toCustomer)
		} catch (err) {
			if (err?.exc_type === "PermissionError") noAccess.value = err.messages?.[0] || "You can't see customers."
			else toast.error("Couldn't load your customers.")
		}
	}
	load()

	async function refresh() {
		refreshing.value = true
		await load()
		refreshing.value = false
	}

	const rank = (customer) => (isWaitingToLink(customer) ? 0 : 1)
	const allRows = computed(() =>
		[...customers.value].sort((a, b) => rank(a) - rank(b) || bySort[sort.value](a, b)).map(toRow),
	)
	const owners = computed(() => [...new Set(allRows.value.map((row) => row.ownerName).filter(Boolean))].sort())

	const rows = computed(() => {
		const q = query.value.trim().toLowerCase()
		return allRows.value
			.filter((c) => matchesQuery(q, c.name, c.contact))
			.filter((c) => !stage.value || c.stage === stage.value)
			.filter((c) => !pays.value || c.billing === pays.value)
			.filter((c) => matchesFilters(c, filters.value))
	})
	const page = computed(() => rows.value.slice(0, pageSize.value))
	const isFiltered = computed(() => Boolean(query.value.trim() || stage.value || pays.value || filters.value.length))
	const footerCount = computed(() => `${page.value.length} of ${rows.value.length}`)

	// Everything a row shows, worked out once so the template only reads fields.
	function toRow(customer) {
		return {
			...customer,
			stageLabel: customer.stage,
			stageColor: STAGES[customer.stage]?.color,
			paysLabel: BILLING[customer.billing] || "—",
			siteCount: customer.sites.length,
			mrrLabel: customer.mrr ? money(customer.mrr) : "—",
			route: `/customers/${customer.id}`,
			actions: isWaitingToLink(customer)
				? [{ label: "Approve link", icon: "lucide-check", onClick: () => approve(customer) }]
				: [],
		}
	}

	async function approve(customer) {
		try {
			await approveLink(context.call, customer.id)
			toast.success(`${customer.name} linked. They're Onboarding now.`)
			await load()
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't approve the link.")
		}
	}

	function clearFilters() {
		query.value = ""
		stage.value = ""
		pays.value = ""
		filters.value = []
	}

	return {
		query,
		stage,
		pays,
		stageOptions: STAGE_OPTIONS,
		paysOptions: PAYS_OPTIONS,
		filters,
		filterFields: computed(() => filterFields(owners.value)),
		sortMenu,
		sortLabel,
		columnsMenu,
		gridColumns,
		isShown,
		pageSize,
		pageSizes: PAGE_SIZES,
		refreshing,
		refresh,
		page,
		isFiltered,
		clearFilters,
		footerCount,
		emptyTitle: computed(() => noAccess.value || (isFiltered.value ? "No customers match" : "No customers yet")),
		hasDemoData: computed(() => customers.value.some((c) => c.isDemo && c.sites.length)),
	}
}
