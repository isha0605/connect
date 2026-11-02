// The partner's Leads, styled as Frappe CRM's list: views in the breadcrumb, quick filters with
// Refresh, Filter, Sort and Columns, a full-width table and a footer with page size and count.
// A row opens the lead's page. No Create: every lead here is a brief a customer sent.

import { computed, ref } from "vue"
import { PRM_STAGES, isClosed, lastAt, ownerOptions, stageColor } from "@app/utils/partnerLeads"
import { clockOrDate } from "@app/utils/partnerRecords"
import { startTracking } from "@app/utils/tracking"

// "To reply" is the default: only what waits on the firm.
const VIEWS = [
	{ label: "To reply", value: "needs", icon: "lucide-reply" },
	{ label: "Mine", value: "mine", icon: "lucide-user" },
	{ label: "Open", value: "open", icon: "lucide-inbox" },
	{ label: "Closed", value: "closed", icon: "lucide-archive" },
]
const IN_VIEW = {
	needs: (lead) => lead.needs_reply,
	mine: (lead, me) => !isClosed(lead) && lead.owner === me,
	open: (lead) => !isClosed(lead),
	closed: (lead) => isClosed(lead),
}
const EMPTY_TITLES = { needs: "All caught up", mine: "None assigned to you", open: "No open leads", closed: "No closed leads" }

const STAGE_OPTIONS = [{ label: "Any stage", value: "" }, ...PRM_STAGES.map((stage) => ({ label: stage, value: stage }))]
const PROBABILITIES = ["", "Hot", "Warm", "Cold"]
const PROBABILITY_ORDER = ["Hot", "Warm", "Cold", ""]
const SORTS = [
	{ value: "reply", label: "Last reply" },
	{ value: "stage", label: "Stage" },
	{ value: "probability", label: "Probability" },
	{ value: "name", label: "Lead name" },
]
const COLUMNS = [
	{ key: "company", label: "Company", width: "minmax(0,1fr)" },
	{ key: "stage", label: "Stage", width: "11rem" },
	{ key: "owner", label: "Assigned to", width: "11rem" },
	{ key: "probability", label: "Probability", width: "7rem" },
]
const PAGE_SIZES = [20, 50, 100].map((n) => ({ label: String(n), value: n }))

export default function setup(context) {
	startTracking(context)
	const { call } = context

	const leads = ref([])
	const team = ref([])
	const me = ref("")
	const loading = ref(true)
	const loadError = ref("")

	const view = ref("needs")
	const query = ref("")
	const stage = ref("")
	const owner = ref("")
	const probability = ref("")
	const sort = ref("reply")
	const shownColumns = ref(COLUMNS.map((c) => c.key))
	const pageSize = ref(20)
	const refreshing = ref(false)

	const isShown = (key) => shownColumns.value.includes(key)
	const currentView = computed(() => VIEWS.find((v) => v.value === view.value))
	const viewMenu = VIEWS.map((v) => ({ label: v.label, icon: v.icon, onClick: () => (view.value = v.value) }))

	const filterMenu = computed(() =>
		PROBABILITIES.map((p) => ({ label: p || "Any probability", selected: probability.value === p, onClick: () => (probability.value = p) })),
	)
	const sortMenu = computed(() =>
		SORTS.map((o) => ({ label: o.label, selected: sort.value === o.value, onClick: () => (sort.value = o.value) })),
	)
	const columnsMenu = computed(() =>
		COLUMNS.map((c) => ({ label: c.label, selected: isShown(c.key), onClick: () => toggleColumn(c.key) })),
	)

	function toggleColumn(key) {
		shownColumns.value = isShown(key) ? shownColumns.value.filter((k) => k !== key) : [...shownColumns.value, key]
	}

	const gridColumns = computed(() => ({
		base: ["minmax(0,1fr)", "auto"],
		md: ["minmax(0,2fr)", ...COLUMNS.filter((c) => isShown(c.key)).map((c) => c.width), "6rem"],
	}))

	async function load() {
		try {
			const data = await call("connect.api.leads.list_leads")
			leads.value = data.leads
			team.value = data.team
			me.value = data.me
			loadError.value = ""
		} catch {
			loadError.value = "Couldn't load your leads. Refresh to try again."
		} finally {
			loading.value = false
		}
	}
	load()

	async function refresh() {
		refreshing.value = true
		await load()
		refreshing.value = false
	}

	// Only the business moves a row. "To reply" goes oldest waiting first, the order to answer in.
	function compare(a, b) {
		if (sort.value === "stage") return PRM_STAGES.indexOf(a.stage) - PRM_STAGES.indexOf(b.stage)
		if (sort.value === "probability") return PROBABILITY_ORDER.indexOf(a.probability) - PROBABILITY_ORDER.indexOf(b.probability)
		if (sort.value === "name") return a.project_name.localeCompare(b.project_name)
		return view.value === "needs" ? lastAt(a) - lastAt(b) : lastAt(b) - lastAt(a)
	}

	function matches(lead, q) {
		if (q && !lead.project_name.toLowerCase().includes(q) && !lead.company?.toLowerCase().includes(q)) return false
		if (stage.value && lead.stage !== stage.value) return false
		if (owner.value && (owner.value === "none" ? lead.owner : lead.owner !== owner.value)) return false
		return !probability.value || lead.probability === probability.value
	}

	const rows = computed(() => {
		const q = query.value.trim().toLowerCase()
		return leads.value
			.filter((lead) => IN_VIEW[view.value](lead, me.value))
			.filter((lead) => matches(lead, q))
			.sort(compare)
			.map(toRow)
	})
	const page = computed(() => rows.value.slice(0, pageSize.value))
	const isFiltered = computed(() => Boolean(query.value.trim() || stage.value || owner.value || probability.value))

	// Bold while a reply waits on you, as CRM bolds an unseen row.
	function toRow(lead) {
		const waiting = lead.needs_reply
		return {
			...lead,
			project: lead.project_name,
			route: `/leads/${lead.name}`,
			companyLabel: lead.company,
			stageColor: stageColor(lead.stage),
			ownerName: lead.owner_name || lead.owner || "",
			probabilityLabel: lead.probability || "—",
			updated: clockOrDate(lastAt(lead)),
			titleWeight: waiting ? "500" : "420",
			titleColor: waiting ? "var(--ink-gray-9)" : "var(--ink-gray-8)",
		}
	}

	function clearFilters() {
		query.value = ""
		stage.value = ""
		owner.value = ""
		probability.value = ""
	}

	return {
		view,
		currentView,
		viewMenu,
		query,
		stage,
		owner,
		stageOptions: STAGE_OPTIONS,
		ownerOptions: computed(() => [{ label: "Anyone", value: "" }, ...ownerOptions(team.value)]),
		filterMenu,
		hasProbabilityFilter: computed(() => Boolean(probability.value)),
		sortMenu,
		sortLabel: computed(() => SORTS.find((o) => o.value === sort.value).label),
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
		footerCount: computed(() => `${page.value.length} of ${rows.value.length}`),
		emptyTitle: computed(() => {
			if (loading.value) return "Loading leads…"
			if (loadError.value) return loadError.value
			return isFiltered.value ? "No leads match" : EMPTY_TITLES[view.value]
		}),
		emptyIcon: computed(() => (view.value === "needs" && !isFiltered.value ? "lucide-check-check" : "lucide-inbox")),
		showOpenLeads: () => (view.value = "open"),
	}
}
