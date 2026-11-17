// The partner's Audits: the audits Frappe ran for them and, inside each, the non-conformances (NCs)
// the auditor raised, each with what happened to it so far.
// Sample data for now: nothing is stored or sent until the page reads the Partner Audit and Partner
// Non Conformance records. openAudit is a page variable, so the editor can show an audit from the
// Data panel.

import { computed, onScopeDispose, ref, watch } from "vue"
import { startTracking } from "@app/utils/tracking"

const AUDIT_TYPES = ["Online", "In-Person", "Hybrid"]
const AUDIT_STATUSES = ["Requested", "Scheduled", "In Progress", "Completed", "On Hold", "Cancelled"]
const AUDIT_THEMES = { Requested: "gray", Scheduled: "blue", "In Progress": "amber", Completed: "green", "On Hold": "amber", Cancelled: "red" }
const NC_STATUSES = ["Open", "In progress", "In review", "Closed"]

const GRAY = "var(--ink-gray-4)"
const BLUE = "var(--ink-blue-6)"
const GREEN = "var(--ink-green-6)"
const AMBER = "var(--ink-amber-5)"
const RED = "var(--ink-red-6)"
const THEME_DOTS = { gray: GRAY, blue: BLUE, green: GREEN, amber: AMBER, red: RED }
const NC_DOTS = { Open: BLUE, "In progress": BLUE, "In review": BLUE, Closed: GREEN }
const STEP_DOTS = { raised: GRAY, submitted: GRAY, sent_back: AMBER, closed: GREEN }

const SAMPLE_AUDITS = [
	{
		name: "PA-0003", pmm_level: 5, mode_of_audit: "Online", status: "Scheduled", auditor: "Karan Mehta", proposed_audit_date: "2026-12-02",
		audit_date: "2026-12-04", result: "", non_conformances: [],
	},
	{
		name: "PA-0002", pmm_level: 5, mode_of_audit: "In-Person", status: "Completed", auditor: "Karan Mehta", proposed_audit_date: "2026-04-11",
		audit_date: "2026-04-11", result: "Not met",
		non_conformances: [
			nc("PNC-00055", "Sales", "SLAs are not applied to leads", "In progress", "2026-11-10",
				"Leads sit in the CRM with no response time set. Several waited more than a week for a first reply.",
				"Set a first-response SLA on every lead source and review breaches in the weekly sales meeting.",
				[
					step("raised", "2026-04-11"),
					step("submitted", "2026-10-20", "Set a 24-hour first-response SLA on the web form lead source."),
					step("sent_back", "2026-10-28", "The SLA is set on the web form only. Add it to email and phone leads too."),
				]),
			nc("PNC-00056", "Implementation", "No documented handover from sales to implementation", "Open", "2026-12-20",
				"The implementation team learns the customer's scope from the first call, not from sales.",
				"Write a handover note for every won deal and go through it with the project lead before kickoff.",
				[step("raised", "2026-04-11")]),
			nc("PNC-00057", "Implementation", "Weekly project updates are not shared with customers", "In review", "2026-12-15",
				"Customers learn about delays only at milestone reviews.",
				"Send every active customer a written update each week.",
				[
					step("raised", "2026-04-11"),
					step("submitted", "2026-11-12", "A weekly update email now goes to every active customer on Fridays.", "weekly-update-sample.pdf"),
				]),
			nc("PNC-00058", "Sales", "No process for collecting feedback during the sales cycle", "Closed", "2026-06-30",
				"Prospects who drop out are never asked why.",
				"Ask every prospect for feedback after the demo and after a lost deal.",
				closedSteps("2026-05-20", "Demo feedback is collected with a short form shared by email.", "2026-05-26")),
			nc("PNC-00059", "Support", "No monthly customer satisfaction scores", "Closed", "2026-06-30",
				"There is no regular measure of how supported customers feel.",
				"Send a satisfaction survey to every support customer each month.",
				closedSteps("2026-05-18", "A monthly survey goes to all support customers.", "2026-05-26")),
			nc("PNC-00060", "Support", "No root cause analysis for repeat tickets", "Closed", "2026-06-30",
				"Repeated issues are fixed one by one without finding the cause.",
				"Find the cause of any issue reported three times and record the fix.",
				closedSteps("2026-06-02", "Repeat tickets are now tagged and reviewed every two weeks.", "2026-06-10")),
			nc("PNC-00061", "General", "No weekly review of delivery metrics", "Closed", "2026-06-30",
				"Delivery and support metrics are not reviewed on a schedule.",
				"Review utilisation and response times with the leads every week.",
				closedSteps("2026-06-05", "Metrics are reviewed every Monday with the delivery and support leads.", "2026-06-12")),
		],
	},
	{
		name: "PA-0001", pmm_level: 4, mode_of_audit: "Online", status: "Completed", auditor: "Aditi Rao", proposed_audit_date: "2024-11-02",
		audit_date: "2024-11-02", result: "Met",
		non_conformances: [
			nc("PNC-00031", "Sales", "No qualification criteria for new leads", "Closed", "2024-12-31",
				"Every lead gets the same follow-up, whatever its size or fit.",
				"Agree on qualification criteria and record them on each lead.",
				[
					step("raised", "2024-11-02"),
					step("submitted", "2024-11-15", "Leads now carry a fit score, set at first contact."),
					step("closed", "2024-11-20"),
				]),
			nc("PNC-00032", "Implementation", "Project plans are not shared at kickoff", "Closed", "2024-12-31",
				"Customers see the project plan only after the first milestone.",
				"Share the project plan with the customer in the kickoff meeting.",
				closedSteps("2024-11-18", "The plan is now part of the kickoff deck.", "2024-11-22", "2024-11-02")),
			nc("PNC-00033", "Support", "No first-response target on tickets", "Closed", "2024-12-31",
				"Tickets have no target time for the first reply.",
				"Set a first-response target for each ticket priority.",
				closedSteps("2024-11-20", "Targets are set: 4 hours for urgent tickets, 1 day for the rest.", "2024-11-25", "2024-11-02")),
			nc("PNC-00034", "General", "Roles and owners are not documented", "Closed", "2024-12-31",
				"Nobody can say who owns sales, delivery and support decisions.",
				"Write down the owner of each area and share it with the team.",
				closedSteps("2024-11-22", "An owners page is on the company wiki.", "2024-11-28", "2024-11-02")),
		],
	},
]

function nc(name, department, statement, status, due, finding, measures, history) {
	return { name, department, statement, status, due, finding, measures, history }
}

function step(kind, on, note = "", evidence = "") {
	return { kind, on, note, evidence }
}

function closedSteps(submittedOn, note, closedOn, raisedOn = "2026-04-11") {
	return [step("raised", raisedOn), step("submitted", submittedOn, note), step("closed", closedOn)]
}

// Dates are plain YYYY-MM-DD: read them as local days, so no time zone moves them a day.
function toDate(value) {
	return new Date(`${value}T00:00:00`)
}

const fullDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" })
const shortDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" })

function formatDate(value) {
	return value ? fullDate.format(toDate(value)) : "—"
}

// The year shows only when it isn't this year.
function formatStepDate(value) {
	const date = toDate(value)
	return (date.getFullYear() === new Date().getFullYear() ? shortDate : fullDate).format(date)
}

// The partner's own date, not UTC's, which is a day behind in the morning in India.
function today() {
	const now = new Date()
	return [now.getFullYear(), now.getMonth() + 1, now.getDate()].map((part) => String(part).padStart(2, "0")).join("-")
}

function auditTitle(audit) {
	return `PMM ${audit.pmm_level} audit`
}

function stepLabel(kind, auditor) {
	if (kind === "submitted") return "You submitted"
	if (kind === "sent_back") return `${auditor} sent it back`
	if (kind === "closed") return `${auditor} closed it`
	return `${auditor} raised this`
}

function options(values, allLabel) {
	return [{ label: allLabel, value: "All" }, ...values.map((value) => ({ label: value, value }))]
}

export default function setup(context) {
	startTracking(context)
	const { toast, router, route, openAudit } = context

	const audits = ref(structuredClone(SAMPLE_AUDITS))

	// ---- Which audit is open: the ?audit= query, mirrored into the openAudit page variable ----
	if (route.query.audit) openAudit.value = String(route.query.audit)
	watch(() => route.query.audit, (audit) => {
		openAudit.value = audit ? String(audit) : ""
	})

	function showAudit(name) {
		openNc.value = ""
		router.push({ query: { audit: name } })
	}

	// ---- The list ----
	const dateFilter = ref("")
	const statusFilter = ref("All")
	const rows = computed(() =>
		audits.value
			.filter((audit) => statusFilter.value === "All" || audit.status === statusFilter.value)
			.filter((audit) => !dateFilter.value || [audit.audit_date, audit.proposed_audit_date].includes(dateFilter.value))
			.map((audit) => ({
				name: audit.name,
				title: auditTitle(audit),
				date: formatDate(audit.audit_date || audit.proposed_audit_date),
				auditor: audit.auditor || "Not assigned yet",
				result: audit.result || "—",
				status: audit.status,
				dot: THEME_DOTS[AUDIT_THEMES[audit.status]] || GRAY,
			})),
	)

	// ---- One audit and its non-conformances ----
	const audit = computed(() => audits.value.find((row) => row.name === openAudit.value) || null)
	const ncStatusFilter = ref("All")
	const departmentFilter = ref("All")
	watch(openAudit, () => {
		ncStatusFilter.value = "All"
		departmentFilter.value = "All"
	})

	const auditDetails = computed(() => {
		const row = audit.value
		if (!row) return null
		return {
			title: auditTitle(row),
			date: formatDate(row.audit_date || row.proposed_audit_date),
			theme: AUDIT_THEMES[row.status] || "gray",
			auditor: row.auditor || "Not assigned yet",
			initial: (row.auditor || "").charAt(0),
			result: row.result || (row.status === "Completed" ? "—" : "After the audit"),
		}
	})

	const ncRows = computed(() =>
		(audit.value?.non_conformances || [])
			.filter((row) => ncStatusFilter.value === "All" || row.status === ncStatusFilter.value)
			.filter((row) => departmentFilter.value === "All" || row.department === departmentFilter.value)
			.map((row) => {
				const isClosed = row.status === "Closed"
				return {
					name: row.name,
					statement: row.statement,
					status: row.status,
					dot: NC_DOTS[row.status] || GRAY,
					due: isClosed ? "—" : formatDate(row.due),
					dueColor: !isClosed && row.due && row.due < today() ? RED : "var(--ink-gray-7)",
					active: row.name === openNc.value,
				}
			}),
	)

	// ---- The open non-conformance, in the side panel ----
	const openNc = ref("")
	const selectedNc = computed(() => (audit.value?.non_conformances || []).find((row) => row.name === openNc.value) || null)

	const panel = computed(() => {
		const row = selectedNc.value
		if (!row) return null
		const auditor = audit.value.auditor
		return {
			statement: row.statement,
			reference: `${row.name} · ${row.department}`,
			finding: row.finding,
			measures: row.measures || "Not added yet.",
			reviewingText: row.status === "In review" ? `${auditor} is reviewing your answer.` : "",
			steps: row.history.map((entry, index) => ({
				key: `${entry.kind}-${index}`,
				label: stepLabel(entry.kind, auditor),
				date: formatStepDate(entry.on),
				note: entry.note,
				evidence: entry.evidence,
				dot: STEP_DOTS[entry.kind] || GRAY,
				hasLine: index < row.history.length - 1,
			})),
		}
	})

	function closePanel() {
		openNc.value = ""
	}

	function onPanelKey(event) {
		if (event.key === "Escape") closePanel()
	}
	watch(openNc, (name) => {
		if (name) window.addEventListener("keydown", onPanelKey)
		else window.removeEventListener("keydown", onPanelKey)
	})
	onScopeDispose(() => window.removeEventListener("keydown", onPanelKey))

	function openReport() {
		toast.info("This sample audit has no report file.")
	}

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
			name: `PA-${String(audits.value.length + 1).padStart(4, "0")}`,
			pmm_level: Math.max(...audits.value.map((row) => row.pmm_level)),
			mode_of_audit: requestForm.value.type, status: "Requested", auditor: "", proposed_audit_date: date, audit_date: "",
			result: "", non_conformances: [],
		})
		requestOpen.value = false
		toast.info("Added to this page only. Audit requests don't reach Frappe yet.")
	}

	return {
		rows,
		dateFilter,
		statusFilter,
		statusOptions: options(AUDIT_STATUSES, "All statuses"),
		showAudit,
		audit,
		auditDetails,
		ncRows,
		ncStatusFilter,
		departmentFilter,
		ncStatusOptions: options(NC_STATUSES, "All statuses"),
		departmentOptions: computed(() =>
			options([...new Set((audit.value?.non_conformances || []).map((row) => row.department))].sort(), "All departments"),
		),
		hasNcs: computed(() => !!audit.value?.non_conformances.length),
		noNcText: computed(() =>
			audit.value?.status === "Completed"
				? "No non-conformances were raised in this audit."
				: "Non-conformances show here once the audit is done.",
		),
		breadcrumbItems: computed(() => {
			const items = [{ label: "Audits", route: "/partner-audits" }]
			if (audit.value) items.push({ label: auditTitle(audit.value), route: `/partner-audits?audit=${audit.value.name}` })
			return items
		}),
		openReport,
		selectNc: (name) => (openNc.value = name),
		panel,
		closePanel,
		requestOpen,
		requestForm,
		requestError,
		typeOptions: AUDIT_TYPES.map((type) => ({ label: type, value: type })),
		openRequest,
		sendRequest,
		minRequestDate: computed(() => today()),
	}
}
