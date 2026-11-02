// The partner's Customers, as Frappe CRM's list: views in the breadcrumb, quick filters with
// Refresh, Filter, Sort and Columns, a full-width table and a footer with page size and count.
// Link requests are a view of their own and open in a docked panel. Design only for now: the
// rows are Pragati's sample data from partnerCustomers.ts.

import { computed, ref } from "vue"
import { dialog, toast } from "frappe-ui"
import {
	BILLING,
	STAGES,
	addCustomer,
	book,
	copyPartnerCode,
	editCustomer,
	findCustomer,
	handleRequest,
	invoicesOf,
	isLinked,
	loadSavedCustomers,
	money,
	pendingRequests,
	removeCustomer,
	restoreCustomer,
	sharePartnerCode,
	undoRequest,
} from "@app/utils/partnerCustomers"
import { FIRM, shortDate, teamName } from "@app/utils/partnerRecords"
import { startTracking } from "@app/utils/tracking"

const STAGE_OPTIONS = [
	{ label: "Any stage", value: "" },
	{ label: "Onboarding", value: "onboarding" },
	{ label: "Live", value: "live" },
	{ label: "Churned", value: "churned" },
]
const PAYS_OPTIONS = [
	{ label: "Anyone pays", value: "" },
	{ label: "Customer pays", value: "customer" },
	{ label: "Partner pays", value: "partner" },
]
const SOURCES = [["", "Any source"], ["connect", "Connect"], ["own", "Added by you"]]
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
const REQUEST_COLUMNS = { base: ["minmax(0,1fr)", "2rem"], md: ["minmax(0,1.5fr)", "minmax(0,1fr)", "9rem", "6rem", "2rem"] }
const EMAIL_PATTERN = /^\S+@\S+\.\S+$/

const bySort = {
	name: (a, b) => a.name.localeCompare(b.name),
	mrr: (a, b) => b.mrr - a.mrr,
	linked: (a, b) => (b.linked || "").localeCompare(a.linked || ""),
}

const matchesQuery = (query, ...fields) => !query || fields.some((field) => field?.toLowerCase().includes(query))

export default function setup(context) {
	startTracking(context)

	const view = ref("all")
	const query = ref("")
	const stage = ref("")
	const pays = ref("")
	const source = ref("")
	const sort = ref("name")
	const shownColumns = ref(COLUMNS.map((c) => c.key))
	const pageSize = ref(20)
	const refreshing = ref(false)

	const isShown = (key) => shownColumns.value.includes(key)
	const requests = computed(() => pendingRequests())

	const views = computed(() => [
		{ label: "All customers", value: "all", icon: "lucide-building-2" },
		{ label: `Link requests${requests.value.length ? ` (${requests.value.length})` : ""}`, value: "requests", icon: "lucide-link" },
	])
	const currentView = computed(() => views.value.find((v) => v.value === view.value))
	const viewMenu = computed(() =>
		views.value.map((v) => ({ label: v.label, icon: v.icon, onClick: () => switchView(v.value) })),
	)

	function switchView(value) {
		view.value = value
		openRequestId.value = null
	}

	const filterMenu = computed(() =>
		SOURCES.map(([value, label]) => ({ label, selected: source.value === value, onClick: () => (source.value = value) })),
	)
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

	async function refresh() {
		refreshing.value = true
		await loadSaved()
		refreshing.value = false
	}

	function loadSaved() {
		return loadSavedCustomers(context.call).catch(() => toast.error("Couldn't load your Connect customers."))
	}
	loadSaved()

	const rows = computed(() => {
		const q = query.value.trim().toLowerCase()
		return book.customers
			.filter((c) => matchesQuery(q, c.name, c.contact))
			.filter((c) => !stage.value || c.stage === stage.value)
			.filter((c) => !pays.value || c.billing === pays.value)
			.filter((c) => !source.value || c.source === source.value)
			// Saved customers stay above the sample ones, each sorted as asked.
			.sort((a, b) => Number(Boolean(b.isSaved)) - Number(Boolean(a.isSaved)) || bySort[sort.value](a, b))
			.map(toRow)
	})
	const page = computed(() => rows.value.slice(0, pageSize.value))
	const requestRows = computed(() => {
		const q = query.value.trim().toLowerCase()
		return requests.value.filter((r) => matchesQuery(q, r.company, r.contact)).map(toRequestRow)
	})
	const isFiltered = computed(() => Boolean(query.value.trim() || stage.value || pays.value || source.value))
	const footerCount = computed(() =>
		view.value === "all" ? `${page.value.length} of ${rows.value.length}` : `${requestRows.value.length} of ${requests.value.length}`,
	)

	// Everything a row shows, worked out once so the template only reads fields.
	function toRow(customer) {
		const stageInfo = STAGES[customer.stage]
		const actions = customerActions(customer)
		return {
			...customer,
			stageLabel: stageInfo.label,
			stageColor: stageInfo.color,
			paysLabel: BILLING[customer.billing],
			ownerName: customer.isSaved ? customer.ownerName : teamName(customer.owner),
			siteCount: customer.sites.length || customer.linkedSites.length,
			mrrLabel: customer.mrr ? money(customer.mrr) : "—",
			route: `/customers/${customer.id}`,
			actions,
		}
	}

	function toRequestRow(request) {
		return { ...request, enteredOn: shortDate(request.at), siteCount: request.sites.length, actions: requestActions(request) }
	}

	function clearFilters() {
		query.value = ""
		stage.value = ""
		pays.value = ""
		source.value = ""
	}

	// ── Row actions ─────────────────────────────────────────────────────────
	// The quick trips, so a look at one customer needs no page. Removing a linked customer
	// unlinks it, so it asks first; one added by hand that never linked is just deleted.
	function customerActions(customer) {
		// Unlinking and deleting are for sample customers; a saved one is worked on its own page.
		if (customer.isSaved) return []
		const linked = isLinked(customer)
		const lastInvoice = invoicesOf(customer).find((invoice) => invoice.status !== "accruing")
		return [
			customer.sites.length && customer.billing !== "partner" && {
				label: "Open in Frappe Cloud",
				icon: "lucide-external-link",
				onClick: () => window.open("https://frappecloud.com/dashboard", "_blank", "noopener"),
			},
			lastInvoice && {
				label: `Download ${lastInvoice.month} invoice`,
				icon: "lucide-download",
				onClick: () => toast.success(`${customer.name}'s ${lastInvoice.month} invoice downloaded`),
			},
			{ label: "Edit details", icon: "lucide-pencil", onClick: () => startEdit(customer) },
			customer.billing === "customer" && linked && !customer.billingSwitch && {
				label: "Switch to Partner pays",
				icon: "lucide-wallet",
				onClick: () => context.router.push(`/customers/${customer.id}`),
			},
			linked && { label: "Unlink", icon: "lucide-unlink", theme: "red", onClick: () => unlink(customer) },
			!linked && { label: "Delete", icon: "lucide-trash-2", theme: "red", onClick: () => remove(customer) },
		].filter(Boolean)
	}

	function unlink(customer) {
		dialog.danger({
			title: `Unlink ${customer.name}?`,
			message: "Their MRR stops counting toward your tier, and you lose sight of their sites and invoices.",
			confirmLabel: "Unlink",
			onConfirm: ({ close }) => {
				removeCustomer(customer.id)
				toast.success(`${customer.name} unlinked`)
				close()
			},
		})
	}

	function remove(customer) {
		removeCustomer(customer.id)
		toast.success(`${customer.name} deleted`, { action: { label: "Undo", onClick: () => restoreCustomer(customer.id) } })
	}

	// ── Link requests ───────────────────────────────────────────────────────
	const openRequestId = ref(null)
	const openRequest = computed(() => requests.value.find((r) => r.id === openRequestId.value) || null)
	const openRequestMatch = computed(() => {
		const match = openRequest.value?.matches && findCustomer(openRequest.value.matches)
		return match ? `${match.name}, added by you` : ""
	})
	const openRequestEntered = computed(() => (openRequest.value ? `Entered your code ${shortDate(openRequest.value.at)}` : ""))

	function requestActions(request) {
		return [
			{ label: "Approve", icon: "lucide-check", onClick: () => decide(request, "approved") },
			{ label: "Decline", icon: "lucide-x", onClick: () => decide(request, "declined") },
		]
	}

	// A few seconds to undo instead of an "Are you sure?": approving by mistake exposes a
	// stranger's invoices, declining sends a rejection.
	function decide(request, outcome) {
		handleRequest(request, outcome)
		openRequestId.value = null
		const done = outcome === "approved" ? `${request.company} linked` : `${request.company} declined`
		toast.success(done, { action: { label: "Undo", onClick: () => undoRequest(request) } })
	}

	// ── Add customer and Edit details ───────────────────────────────────────
	// Saved as Onboarding, then the dialog ends on the partner code: sharing it is the next step,
	// and nothing links until the customer enters it.
	const addOpen = ref(false)
	const addStep = ref("form")
	const addForm = ref({ name: "", contact: "", email: "" })
	const addErrors = ref({})
	const editOpen = ref(false)
	const editingId = ref(null)
	const editForm = ref({ name: "", contact: "", email: "" })
	const editErrors = ref({})

	function formErrors(form, exceptId = null) {
		const errors = {}
		if (!form.name.trim()) errors.name = "Enter the company name"
		if (!EMAIL_PATTERN.test(form.email.trim())) errors.email = "Enter a valid email, like name@company.com"
		const name = form.name.trim().toLowerCase()
		const email = form.email.trim().toLowerCase()
		const duplicate = book.customers.find((c) => c.id !== exceptId && (c.name.toLowerCase() === name || c.email === email))
		if (duplicate && !errors.name) errors.name = `${duplicate.name} is already in your customers`
		return errors
	}

	function startAdd() {
		addForm.value = { name: "", contact: "", email: "" }
		addErrors.value = {}
		addStep.value = "form"
		addOpen.value = true
	}

	function saveAdd() {
		addErrors.value = formErrors(addForm.value)
		if (Object.keys(addErrors.value).length) return
		const { name, contact, email } = addForm.value
		addCustomer({ name: name.trim(), contact: contact.trim(), email: email.trim().toLowerCase() })
		addStep.value = "share"
	}

	function finishAdd() {
		addOpen.value = false
	}

	function startEdit(customer) {
		editingId.value = customer.id
		editForm.value = { name: customer.name, contact: customer.contact || "", email: customer.email || "" }
		editErrors.value = {}
		editOpen.value = true
	}

	function saveEdit() {
		editErrors.value = formErrors(editForm.value, editingId.value)
		if (Object.keys(editErrors.value).length) return
		const { name, contact, email } = editForm.value
		editCustomer(editingId.value, { name: name.trim(), contact: contact.trim(), email: email.trim() })
		editOpen.value = false
		toast.success("Details saved")
	}

	return {
		firmCode: FIRM.code,
		view,
		currentView,
		viewMenu,
		query,
		stage,
		pays,
		stageOptions: STAGE_OPTIONS,
		paysOptions: PAYS_OPTIONS,
		filterMenu,
		hasSourceFilter: computed(() => Boolean(source.value)),
		sortMenu,
		sortLabel,
		columnsMenu,
		gridColumns,
		requestColumns: REQUEST_COLUMNS,
		isShown,
		pageSize,
		pageSizes: PAGE_SIZES,
		refreshing,
		refresh,
		page,
		requestRows,
		isFiltered,
		clearFilters,
		footerCount,
		emptyTitle: computed(() => (isFiltered.value ? "No customers match" : "No customers yet")),
		openRequestId,
		openRequest,
		showRequest: (id) => (openRequestId.value = id),
		closeRequest: () => (openRequestId.value = null),
		openRequestMatch,
		openRequestEntered,
		openRequestDecide: (outcome) => decide(openRequest.value, outcome),
		addOpen,
		addStep,
		addForm,
		addErrors,
		addTitle: computed(() => (addStep.value === "form" ? "Add customer" : "Share your partner code")),
		addShareText: computed(() => `${addForm.value.name.trim()} links once they enter this code in Frappe Cloud and you approve the request.`),
		startAdd,
		closeAdd: () => (addOpen.value = false),
		saveAdd,
		finishAdd,
		editOpen,
		editForm,
		editErrors,
		saveEdit,
		closeEdit: () => (editOpen.value = false),
		copyCode: () => copyPartnerCode(toast),
		shareCode: () => sharePartnerCode(toast),
	}
}
