// One customer, laid out like a deal in Frappe CRM: owner and stage in the top bar, the record in
// tabs, and a side panel of facts. The same tabs a lead has (Follow-ups, Activity, Notes), so a
// lead that's won keeps its history. Read from connect.api.partner_customers. A customer who wants
// to link waits on the team's Approve link; sites and MRR are demo data until they come from
// Frappe Cloud.

import { computed, ref, watch } from "vue"
import { toast } from "frappe-ui"
import {
	BILLING,
	STAGES,
	WANTS_TO_LINK,
	approveLink,
	isWaitingToLink,
	longDate,
	money,
	toCustomer,
} from "@app/utils/partnerCustomers"
import {
	FOLLOW_UP_MODES,
	activityRows,
	copyText,
	emptyFollowUp,
	followUpValues,
	toActivityEntries,
	toFollowUpRows,
	toNoteRows,
} from "@app/utils/partnerRecords"
import { startTracking } from "@app/utils/tracking"

const CONTACT_FIELDS = [
	{ key: "contact", label: "Name", type: "text" },
	{ key: "email", label: "Email", type: "email" },
	{ key: "phone", label: "Phone", type: "tel" },
]
const DETAIL_FIELDS = [
	{ key: "industry", label: "Industry", type: "text" },
	{ key: "country", label: "Country", type: "text" },
]
// A linked customer moves between these by hand; Wants to link only leaves through Approve link.
const LINKED_STAGES = Object.keys(STAGES).filter((stage) => stage !== WANTS_TO_LINK)

export default function setup(context) {
	startTracking(context)

	const { call } = context
	const customerId = computed(() => context.router.currentRoute.value.params.customer_id)
	// The customer as get_customer returns it, with its notes, follow-ups and activity.
	const record = ref(null)
	const team = ref([])
	const loading = ref(false)
	const customer = computed(() => (record.value ? toCustomer(record.value) : null))

	async function load() {
		if (!customerId.value) return
		// Another customer's record mustn't show while this one loads.
		if (record.value?.name !== customerId.value) record.value = null
		loading.value = !record.value
		try {
			const result = await call("connect.api.partner_customers.get_customer", { name: customerId.value })
			record.value = result.customer
			team.value = result.team
		} catch {
			record.value = null
		} finally {
			loading.value = false
		}
	}
	watch(customerId, load, { immediate: true })

	// Saves what the team changed, then reads the customer again for its Activity.
	async function save(values) {
		try {
			await call("connect.api.partner_customers.update_customer", { name: customerId.value, ...values })
			await load()
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't save the change.")
		}
	}

	// ── Top bar: owner, stage and Approve link ──────────────────────────────
	const isWaiting = computed(() => Boolean(customer.value && isWaitingToLink(customer.value)))
	const stageMenu = computed(() =>
		LINKED_STAGES.map((stage) => ({
			label: stage,
			onClick: () => stage !== customer.value.stage && save({ stage }),
		})),
	)
	const ownerMenu = computed(() =>
		team.value.map((member) => ({
			label: member.full_name || member.user,
			onClick: () => member.user !== customer.value.owner && save({ assigned_to: member.user }),
		})),
	)

	const approving = ref(false)
	async function approve() {
		approving.value = true
		try {
			await approveLink(call, customerId.value)
			toast.success(`${customer.value.name} linked. They're Onboarding now.`)
			await load()
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't approve the link.")
		} finally {
			approving.value = false
		}
	}

	// ── Tabs ────────────────────────────────────────────────────────────────
	const tab = ref("sites")
	watch(customerId, () => (tab.value = "sites"))
	const tabs = computed(() =>
		[
			{ value: "sites", label: "Sites", iconLeft: "lucide-globe" },
			{ value: "followups", label: "Follow-ups", iconLeft: "lucide-phone" },
			{ value: "activity", label: "Activity", iconLeft: "lucide-history" },
			{ value: "notes", label: "Notes", iconLeft: "lucide-notebook-pen" },
			customer.value?.source === "Connect" && { value: "connect", label: "Connect", iconLeft: "lucide-message-square" },
		].filter(Boolean),
	)

	const isPartnerPays = computed(() => customer.value?.billing === "Partner")
	const sites = computed(() =>
		(customer.value?.sites || []).map((site) => ({
			...site,
			meta: isPartnerPays.value
				? site.plan
				: [site.plan, site.region, site.status, site.apps.join(", ")].filter(Boolean).join(" · "),
			amountLabel: money(site.amount),
		})),
	)

	// ── Follow-ups ──────────────────────────────────────────────────────────
	const followUpOpen = ref(false)
	const followUpForm = ref(emptyFollowUp())

	function startFollowUp() {
		followUpForm.value = emptyFollowUp(customer.value.contact || "")
		followUpOpen.value = true
	}

	async function saveFollowUp() {
		try {
			record.value = await call("connect.api.partner_customers.log_customer_follow_up", {
				name: customerId.value,
				values: followUpValues(followUpForm.value),
			})
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't add the follow-up.")
			return
		}
		followUpOpen.value = false
		toast.success("Follow-up added")
	}

	// ── Activity ────────────────────────────────────────────────────────────
	const expandedGroups = ref({})
	const activity = computed(() =>
		record.value ? activityRows(toActivityEntries(record.value.activity), expandedGroups.value) : [],
	)

	function toggleGroup(id) {
		expandedGroups.value = { ...expandedGroups.value, [id]: !expandedGroups.value[id] }
	}

	// ── Notes: the team's own about this customer, never sent to them ─────
	const noteDraft = ref("")

	async function addNote() {
		const text = noteDraft.value.trim()
		if (!text) return
		try {
			const notes = await call("connect.api.partner_customers.add_customer_note", { name: customerId.value, content: text })
			record.value = { ...record.value, notes }
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't add the note.")
			return
		}
		noteDraft.value = ""
		toast.success("Note added")
	}

	// ── Side panel: the customer's details come from their Connect account ─
	const draft = ref({})
	watch(
		customer,
		(value) => (draft.value = value ? Object.fromEntries([...CONTACT_FIELDS, ...DETAIL_FIELDS].map((f) => [f.key, value[f.key] || ""])) : {}),
		{ immediate: true },
	)

	function commit(key) {
		const current = customer.value[key] || ""
		if (draft.value[key].trim() !== current) toast.info("Their details come from their Connect account.")
		draft.value[key] = current
	}

	const openSections = ref({ contact: true, details: true, billing: true })
	function toggleSection(key) {
		openSections.value = { ...openSections.value, [key]: !openSections.value[key] }
	}

	return {
		customer,
		loadingSaved: loading,
		crumb: computed(() => customer.value?.name || (loading.value ? "" : "Not found")),
		ownerName: computed(() => customer.value?.ownerName || "Assign"),
		hasOwner: computed(() => Boolean(customer.value?.owner)),
		stageLabel: computed(() => customer.value?.stage || ""),
		stageMenu,
		ownerMenu,
		isWaiting,
		approving,
		approve,
		tab,
		tabs,
		sites,
		isPartnerPays,
		sitesEmptyTitle: computed(() => (isWaiting.value ? "Not linked yet" : "No sites yet")),
		sitesEmptyText: computed(() =>
			isWaiting.value ? "Approve the link to see their Frappe Cloud sites." : "Their Frappe Cloud sites show here.",
		),
		followUps: computed(() => toFollowUpRows(record.value?.follow_ups || [])),
		followUpOpen,
		followUpForm,
		followUpModes: FOLLOW_UP_MODES,
		startFollowUp,
		saveFollowUp,
		closeFollowUp: () => (followUpOpen.value = false),
		activity,
		toggleGroup,
		notes: computed(() => toNoteRows(record.value?.notes || [])),
		noteDraft,
		addNote,
		draft,
		commit,
		contactFields: CONTACT_FIELDS,
		detailFields: DETAIL_FIELDS,
		openSections,
		toggleSection,
		sourceLabel: computed(() => customer.value?.source || ""),
		mrrLabel: computed(() => (customer.value?.mrr ? money(customer.value.mrr) : "—")),
		whoPaysLabel: computed(() => BILLING[customer.value?.billing] || "—"),
		linkedLabel: computed(() => {
			const c = customer.value
			if (!c) return ""
			if (isWaitingToLink(c)) return "Waiting for your approval"
			return c.linkedOn ? longDate(c.linkedOn) : "Linked"
		}),
		isDemo: computed(() => Boolean(customer.value?.isDemo && customer.value.sites.length)),
		emailHref: computed(() => (customer.value?.email ? `mailto:${customer.value.email}` : "")),
		emailTooltip: computed(() => `Email ${customer.value?.contact || customer.value?.name || ""}`),
		copyLink: () => copyText(window.location.href, toast, "Link copied"),
	}
}
