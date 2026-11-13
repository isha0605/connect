// One lead, the same shape as a customer: tabs (Messages, Follow-ups, Activity, Notes) and a
// docked panel of facts on the right. A lead is the customer's whole conversation with the
// partner, with every requirement they sent in it; Messages is that thread, the same one
// Messaging shows, and a reply here goes into it. Notes and follow-ups are the team's own about
// the customer (only the partner's team sees them); Activity is this lead's history.

import { computed, ref, watch } from "vue"
import { toast } from "frappe-ui"
import { LOST_REASONS, PRM_STAGES, PROBABILITY, isClosed, leadTitle, ownerOptions } from "@app/utils/partnerLeads"
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
import { useConversation } from "@app/utils/partnerConversation"
import { startTracking } from "@app/utils/tracking"

const TABS = [
	{ value: "messages", label: "Messages", iconLeft: "lucide-message-square" },
	{ value: "followups", label: "Follow-ups", iconLeft: "lucide-phone" },
	{ value: "activity", label: "Activity", iconLeft: "lucide-history" },
	{ value: "notes", label: "Notes", iconLeft: "lucide-sticky-note" },
]
const STAGE_OPTIONS = PRM_STAGES.filter((stage) => stage !== "Won").map((stage) => ({ label: stage, value: stage }))
const PROBABILITY_OPTIONS = PROBABILITY.map((p) => ({ label: p, value: p }))
const REASON_OPTIONS = LOST_REASONS.map((r) => ({ label: r, value: r }))

export default function setup(context) {
	startTracking(context)
	const { call } = context

	const leadId = computed(() => context.router.currentRoute.value.params.lead_id)
	const data = ref(null)
	const team = ref([])
	const me = ref("")
	const canInvite = ref(false)
	const loading = ref(true)

	async function load() {
		// The route has no params on the first run, before the router resolves it.
		if (!leadId.value) return
		try {
			const result = await call("connect.api.leads.get_lead", { name: leadId.value })
			data.value = result.lead
			team.value = result.team
			me.value = result.me
			canInvite.value = result.can_invite
		} catch {
			data.value = null
		} finally {
			loading.value = false
		}
	}

	const lead = computed(() => (data.value ? toLead(data.value) : null))
	const closed = computed(() => (lead.value ? isClosed(lead.value) : false))
	const nameOf = (user) => team.value.find((member) => member.user === user)?.full_name || user || ""

	// ── Stage, owner, probability ───────────────────────────────────────────
	// Lost always asks why. Moving a closed lead back to an open stage reopens it.
	const lostOpen = ref(false)
	const lostReason = ref(LOST_REASONS[0])

	// The server records the change in the lead's Activity, so the lead is read again after.
	async function save(values) {
		try {
			await call("connect.api.leads.update_lead", { name: leadId.value, ...values })
			await load()
			return true
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't save the change.")
			return false
		}
	}

	function setStage(stage) {
		if (stage === lead.value.stage) return
		if (stage === "Lost") {
			lostReason.value = LOST_REASONS[0]
			lostOpen.value = true
			return
		}
		save({ stage })
	}

	async function confirmLost() {
		if (await save({ stage: "Lost", lost_reason: lostReason.value })) {
			lostOpen.value = false
			toast.success("Marked as lost")
		}
	}

	// With CRM sync on, a lead's CRM Lead goes to the same person, so they need a user there.
	function setOwner(user) {
		const next = user === "none" ? "" : user
		if (next === (lead.value.owner || "")) return
		const member = team.value.find((m) => m.user === next)
		if (member?.in_crm === false) {
			toast.error(`${nameOf(next)} isn't on your CRM. Create their account there, then match them in Settings → Users.`)
			return
		}
		save({ owner: next })
	}

	function setProbability(probability) {
		save({ probability })
	}

	// ── The CRM's owner ─────────────────────────────────────────────────────
	// The lead's CRM Lead has one owner. Say when the two sides can't agree on who it is.
	const crmNote = computed(() => {
		const current = data.value
		if (!current) return ""
		if (current.crm_owner) {
			const why = current.crm_owner_on_team ? "who can't take leads on Connect" : "who isn't on your Connect team"
			return `Assigned in your CRM to ${current.crm_owner}, ${why}.`
		}
		const owner = team.value.find((member) => member.user === current.owner)
		if (owner?.in_crm === false) {
			return `${nameOf(owner.user)} isn't on your CRM, so its Lead there stays with whoever has it. Create their account there, then match them in Settings → Users.`
		}
		return ""
	})
	// A CRM user can be named without an email (Administrator); only an email can be invited.
	const canInviteCrmOwner = computed(
		() => canInvite.value && Boolean(data.value?.crm_owner?.includes("@")) && !data.value.crm_owner_on_team,
	)
	const inviting = ref(false)

	// Brings the CRM's owner onto the team as Sales, then gives them the lead here too.
	async function inviteCrmOwner() {
		const email = data.value.crm_owner
		inviting.value = true
		try {
			await call("connect.api.account.add_team_member", { email, access_level: "Sales" })
			if (await save({ owner: email })) toast.success(`Invited ${email} to your team`)
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't invite them.")
		} finally {
			inviting.value = false
		}
	}

	// ── Tabs ────────────────────────────────────────────────────────────────
	const tab = ref("messages")
	const sideOpen = ref(false)

	// ── Messages ────────────────────────────────────────────────────────────
	const conversation = useConversation({
		call,
		toast,
		record: data,
		reload: load,
		followUpMethod: "connect.api.leads.log_lead_follow_up",
		me,
		socket: context.socket,
	})

	// ── Follow-ups and activity ─────────────────────────────────────────────
	const followUpOpen = ref(false)
	const followUpForm = ref(emptyFollowUp())

	function startFollowUp() {
		followUpForm.value = emptyFollowUp(lead.value.company?.contact || "")
		followUpOpen.value = true
	}

	async function saveFollowUp() {
		try {
			const records = await call("connect.api.leads.log_lead_follow_up", {
				name: leadId.value,
				values: followUpValues(followUpForm.value),
			})
			data.value = { ...data.value, ...records }
			followUpOpen.value = false
			toast.success("Follow-up added")
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't add the follow-up.")
		}
	}

	const expandedGroups = ref({})
	function toggleGroup(id) {
		expandedGroups.value = { ...expandedGroups.value, [id]: !expandedGroups.value[id] }
	}

	// ── Notes: the team's own about this customer, never sent to the business ──
	const noteDraft = ref("")
	const notes = computed(() => toNoteRows(data.value?.notes || []))

	async function addNote() {
		const text = noteDraft.value.trim()
		if (!text) return
		try {
			const saved = await call("connect.api.leads.add_lead_note", { name: leadId.value, content: text })
			data.value = { ...data.value, notes: saved }
			noteDraft.value = ""
			toast.success("Note added")
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't add the note.")
		}
	}

	// ── The panel ───────────────────────────────────────────────────────────
	const openSections = ref({ lead: true, requirements: true, project: true, company: true })
	function toggleSection(key) {
		openSections.value = { ...openSections.value, [key]: !openSections.value[key] }
	}

	const companyRows = computed(() => {
		const company = lead.value?.company
		if (!company) return []
		return [
			{ label: "Name", value: company.name },
			{ label: "Contact", value: company.contact },
			{ label: "Email", value: company.email },
			{ label: "Phone", value: company.phone },
		].filter((row) => row.value)
	})

	const ownerChoices = computed(() => ownerOptions(team.value))

	// Declared last: the first run resets state defined above.
	watch(
		leadId,
		() => {
			tab.value = "messages"
			sideOpen.value = false
			conversation.resetDraft()
			noteDraft.value = ""
			loading.value = true
			load()
		},
		{ immediate: true },
	)

	return {
		lead,
		loading,
		closed,
		crumb: computed(() => lead.value?.title || (loading.value ? "" : "Not found")),
		ownerName: computed(() => nameOf(lead.value?.owner) || "Assign"),
		hasOwner: computed(() => Boolean(lead.value?.owner)),
		ownerValue: computed(() => lead.value?.owner || "none"),
		ownerMenu: computed(() => ownerChoices.value.map((o) => ({ label: o.label, onClick: () => setOwner(o.value) }))),
		stageMenu: STAGE_OPTIONS.map((o) => ({ label: o.label, onClick: () => setStage(o.value) })),
		stageOptions: STAGE_OPTIONS,
		ownerOptions: ownerChoices,
		probabilityOptions: PROBABILITY_OPTIONS,
		setStage,
		setOwner,
		setProbability,
		crmNote,
		canInviteCrmOwner,
		inviting,
		inviteCrmOwner,
		requirementRows: computed(() => lead.value?.requirements || []),
		requirementsTitle: computed(() => `Requirements (${lead.value?.requirements.length || 0})`),
		tab,
		tabs: TABS,
		sideOpen,
		openSide: () => (sideOpen.value = true),
		closeSide: () => (sideOpen.value = false),
		companyLabel: computed(() => lead.value?.company?.name || data.value?.company || ""),
		...conversation,
		followUps: computed(() => toFollowUpRows(data.value?.follow_ups || [])),
		followUpOpen,
		followUpForm,
		followUpModes: FOLLOW_UP_MODES,
		startFollowUp,
		saveFollowUp,
		closeFollowUp: () => (followUpOpen.value = false),
		activity: computed(() => activityRows(toActivityEntries(data.value?.activity || []), expandedGroups.value)),
		toggleGroup,
		noteDraft,
		notes,
		addNote,
		openSections,
		toggleSection,
		companyRows,
		emailHref: computed(() => (lead.value?.company?.email ? `mailto:${lead.value.company.email}` : "")),
		emailTooltip: computed(() => `Email ${lead.value?.company?.contact || ""}`),
		copyLink: () => copyText(window.location.href, toast, "Link copied"),
		lostOpen,
		lostReason,
		reasonOptions: REASON_OPTIONS,
		confirmLost,
		closeLost: () => (lostOpen.value = false),
	}
}

// The server's lead in the shape the page's blocks read.
function toLead(lead) {
	return {
		id: lead.name,
		title: leadTitle(lead),
		project: lead.project_name,
		scope: lead.scope,
		budget: lead.budget,
		industry: lead.industry,
		projectRows: lead.project_rows,
		askedFor: lead.asked_for,
		stage: lead.stage,
		lostReason: lead.lost_reason,
		probability: lead.probability || "",
		owner: lead.owner || "",
		requirements: lead.requirements.map((r) => ({ id: r.name, label: r.project_name, value: r.status_label })),
		// No company until they're revealed: the panel says when their details will show.
		company: lead.is_customer_revealed
			? { name: lead.company, contact: lead.contact.name, email: lead.contact.email, phone: lead.contact.phone }
			: null,
	}
}
