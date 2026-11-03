// The partner's Audits: the audits Frappe ran for them and, inside each, the non-conformances (NCs)
// the auditor raised. Partners only read them and can ask for a new audit. Sample data for now:
// nothing is stored or sent until audits have a home (Connect doctypes or a Frappe Cloud API).
// openAudit is a page variable, so the editor can show an audit from the Data panel.

import { computed, ref, watch } from "vue"
import { startTracking } from "@app/utils/tracking"

const AUDIT_TYPES = ["Online", "In-Person", "Hybrid"]
const AUDIT_STATUSES = ["Requested", "Scheduled", "In Progress", "Completed", "On Hold", "Cancelled"]
const AUDIT_THEMES = { Requested: "gray", Scheduled: "blue", "In Progress": "amber", Completed: "green", "On Hold": "amber", Cancelled: "red" }
const NC_THEMES = { Open: "blue", WIP: "amber", Closed: "green", Discarded: "gray", "On Hold": "amber" }

const SAMPLE_AUDITS = [
	{
		name: "PA-0003", mode_of_audit: "Hybrid", status: "Requested", conducted_by: "", proposed_audit_date: "2026-12-04", audit_date: "",
		non_conformances: [],
	},
	{
		name: "PA-0002", mode_of_audit: "Online", status: "Scheduled", conducted_by: "auditor@example.com", proposed_audit_date: "2026-11-20",
		audit_date: "2026-11-24", non_conformances: [],
	},
	{
		name: "PA-0001", mode_of_audit: "In-Person", status: "Completed", conducted_by: "auditor@example.com", proposed_audit_date: "2026-04-11",
		audit_date: "2026-04-11",
		non_conformances: [
			nc("PNC-00055", "Sales", "SLAs are not applied to leads", "Closed", "Leads wait days for a first reply because no response time is set.",
				"First-response SLAs are set on every lead source and tracked in the weekly review.", "2026-05-20"),
			nc("PNC-00057", "Sales", "No process for collecting feedback during the sales cycle.", "Closed",
				"Prospects who drop out are never asked why.",
				"Demo feedback is collected using a template that captures overall satisfaction, demo quality, business needs and product fit. "
				+ "The feedback link is shared through email. Although the process has been started, the response coverage is still low.",
				"2026-05-26"),
			nc("PNC-00058", "Implementation", "Weekly project updates are not being shared with customers.", "Closed",
				"Customers learn about delays only at milestone reviews.", "A weekly update email goes to every active customer on Fridays.",
				"2026-05-26"),
			nc("PNC-00059", "Support", "Missing process for collecting monthly customer satisfaction scores.", "Closed",
				"There is no regular measure of how supported customers feel.", "A monthly CSAT survey is sent to all support customers.",
				"2026-05-26"),
			nc("PNC-00060", "Implementation", "Missing Root Cause Analysis (RCA) and Corrective Actions practices.", "WIP",
				"Repeated issues are fixed one by one without finding the cause.", "", ""),
			nc("PNC-00061", "General", "Missing weekly review meetings for reporting metrics.", "WIP",
				"Delivery and support metrics are not reviewed on a schedule.", "", ""),
			nc("PNC-00062", "General", "Some of the metrics are missing from the dashboard", "Open",
				"Utilisation and first-response time are not on the management dashboard.", "", ""),
		],
	},
]

function nc(name, department, statement, status, description, measures, closedOn) {
	return {
		name, department, nc_statement: statement, status, nc_description: description, measures_to_close_nc: measures,
		auditor: "auditor@example.com", audit_date: "2026-04-11", expected_closure: "2026-06-30",
		closed_by: status === "Closed" ? "admin@partner.example.com" : "", closed_on: status === "Closed" ? closedOn : "",
	}
}

const longDate = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "long", day: "numeric" })

function formatDate(value) {
	return value ? longDate.format(new Date(value)) : "—"
}

function today() {
	return new Date().toISOString().slice(0, 10)
}

export default function setup(context) {
	startTracking(context)
	const { toast, router, route, openAudit } = context

	const audits = ref(SAMPLE_AUDITS.map((audit) => ({ ...audit })))

	// ---- Which audit is open: the ?audit= query, mirrored into the openAudit page variable ----
	if (route.query.audit) openAudit.value = String(route.query.audit)
	watch(() => route.query.audit, (audit) => {
		openAudit.value = audit ? String(audit) : ""
	})

	function showAudit(name) {
		openNc.value = ""
		router.push({ query: { audit: name } })
	}

	function showList() {
		router.push({ query: {} })
	}

	// ---- The list ----
	const dateFilter = ref("")
	const statusFilter = ref("All")
	const rows = computed(() =>
		audits.value
			.filter((audit) => statusFilter.value === "All" || audit.status === statusFilter.value)
			.filter((audit) => !dateFilter.value || [audit.audit_date, audit.proposed_audit_date].includes(dateFilter.value))
			.map((audit) => ({
				...audit,
				theme: AUDIT_THEMES[audit.status] || "gray",
				ncCount: String(audit.non_conformances.length),
				requested: formatDate(audit.proposed_audit_date),
				held: formatDate(audit.audit_date),
				conductedBy: audit.conducted_by || "Not assigned yet",
			})),
	)

	// ---- One audit and its non-conformances ----
	const audit = computed(() => audits.value.find((row) => row.name === openAudit.value) || null)
	const openNc = ref("")
	const ncCards = computed(() =>
		(audit.value?.non_conformances || []).map((row) => ({
			...row,
			theme: NC_THEMES[row.status] || "gray",
			active: row.name === selectedNc.value?.name,
		})),
	)
	const selectedNc = computed(() => {
		const list = audit.value?.non_conformances || []
		return list.find((row) => row.name === openNc.value) || list[0] || null
	})

	// ---- Request for Audit ----
	const requestOpen = ref(false)
	const requestForm = ref({ date: "", type: "Online" })
	const requestError = ref("")

	function openRequest() {
		requestForm.value = { date: "", type: "Online" }
		requestError.value = ""
		requestOpen.value = true
	}

	function sendRequest() {
		const date = requestForm.value.date
		if (!date || date <= today()) {
			requestError.value = "Pick a date after today."
			return
		}
		if (audits.value.some((row) => row.proposed_audit_date === date)) {
			requestError.value = "You already asked for an audit on this date. Pick another one."
			return
		}
		audits.value.unshift({
			name: `PA-${String(audits.value.length + 1).padStart(4, "0")}`, mode_of_audit: requestForm.value.type, status: "Requested",
			conducted_by: "", proposed_audit_date: date, audit_date: "", non_conformances: [],
		})
		requestOpen.value = false
		toast.info("Added to this page only. Audit requests don't reach Frappe yet.")
	}

	return {
		audits,
		rows,
		dateFilter,
		statusFilter,
		statusOptions: ["All", ...AUDIT_STATUSES].map((status) => ({ label: status === "All" ? "All statuses" : status, value: status })),
		showAudit,
		showList,
		audit,
		auditTitle: computed(() => (audit.value ? `${audit.value.mode_of_audit} audit` : "")),
		auditSummary: computed(() => {
			if (!audit.value) return ""
			const count = audit.value.non_conformances.length
			const when = audit.value.audit_date ? `held on ${formatDate(audit.value.audit_date)}` : `requested for ${formatDate(audit.value.proposed_audit_date)}`
			return `${audit.value.status} · ${when} · ${count === 1 ? "1 non-conformance" : `${count} non-conformances`}`
		}),
		auditTheme: computed(() => AUDIT_THEMES[audit.value?.status] || "gray"),
		noNcText: computed(() =>
			audit.value?.status === "Completed"
				? "No non-conformances were raised in this audit."
				: "Non-conformances show here once the audit is done.",
		),
		breadcrumbItems: computed(() => {
			const items = [{ label: "Audits", route: "/partner-audits" }]
			if (audit.value) items.push({ label: `${audit.value.mode_of_audit} audit`, route: `/partner-audits?audit=${audit.value.name}` })
			return items
		}),
		ncCards,
		selectNc: (name) => (openNc.value = name),
		nc: computed(() => {
			const row = selectedNc.value
			if (!row) return null
			return {
				...row,
				theme: NC_THEMES[row.status] || "gray",
				reference: `${row.name}  -  ${row.department}`,
				auditedOn: formatDate(row.audit_date),
				closedOn: formatDate(row.closed_on),
				expected: formatDate(row.expected_closure),
				isClosed: row.status === "Closed",
				measures: row.measures_to_close_nc || "Not added yet.",
			}
		}),
		requestOpen,
		requestForm,
		requestError,
		typeOptions: AUDIT_TYPES.map((type) => ({ label: type, value: type })),
		openRequest,
		sendRequest,
		minRequestDate: computed(() => today()),
	}
}
