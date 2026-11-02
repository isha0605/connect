// One lead, the same shape as a customer: tabs (Messages, Follow-ups, Activity, Notes) and a
// docked panel of facts on the right. Messages is the customer's thread with the partner, the
// same one Messaging shows, and a reply here goes into it. Notes and follow-ups are the team's own
// about the customer (only the partner's team sees them); Activity is this lead's history.

import { computed, ref, watch } from "vue"
import { toast } from "frappe-ui"
import { LOST_REASONS, PRM_STAGES, PROBABILITY, isClosed, ownerOptions } from "@app/utils/partnerLeads"
import {
	FOLLOW_UP_MODES,
	activityRows,
	clockOrDate,
	copyText,
	emptyFollowUp,
	followUpValues,
	toActivityEntries,
	toFollowUpRows,
	toNoteRows,
	toTime,
} from "@app/utils/partnerRecords"
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
const RUPEES = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })

const escapeHtml = (text) => String(text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
const paragraphs = (text) => escapeHtml(text).split("\n").map((line) => `<p>${line}</p>`).join("")

function plainText(html) {
	const element = document.createElement("div")
	element.innerHTML = html || ""
	return element.textContent.trim()
}

// Messaging stores plain text: one line per paragraph, without the quoted reply.
function composerText(html) {
	const element = document.createElement("div")
	element.innerHTML = html || ""
	element.querySelectorAll("blockquote").forEach((quote) => quote.remove())
	const blocks = [...element.querySelectorAll("p, li")]
	const lines = blocks.length ? blocks.map((block) => block.textContent) : [element.textContent]
	return lines.join("\n").trim()
}

export default function setup(context) {
	startTracking(context)
	const { call } = context

	const leadId = computed(() => context.router.currentRoute.value.params.lead_id)
	const data = ref(null)
	const team = ref([])
	const me = ref("")
	const loading = ref(true)

	async function load() {
		// The route has no params on the first run, before the router resolves it.
		if (!leadId.value) return
		try {
			const result = await call("connect.api.leads.get_lead", { name: leadId.value })
			data.value = result.lead
			team.value = result.team
			me.value = result.me
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

	function setOwner(user) {
		const next = user === "none" ? "" : user
		if (next === (lead.value.owner || "")) return
		save({ owner: next })
	}

	function setProbability(probability) {
		save({ probability })
	}

	// ── Tabs ────────────────────────────────────────────────────────────────
	const tab = ref("messages")
	const sideOpen = ref(false)

	// ── Messages ────────────────────────────────────────────────────────────
	const messages = computed(() => {
		const current = data.value
		if (!current) return []
		return current.messages.map((m) => ({
			...m,
			time: clockOrDate(toTime(m.at)),
			isYou: m.from === "you",
			avatarLabel: m.from === "you" ? current.partner_name : m.author,
			// Until the customer is interested in your quote, they're an anonymous company.
			isAnonymous: m.from === "them" && !current.is_customer_revealed,
			isWaiting: m.kind === "bid" && !current.is_customer_revealed,
			body: messageBody(m),
			price: m.amount ? RUPEES.format(m.amount) : "",
			weeksLabel: m.weeks ? `about ${m.weeks} weeks` : "",
			menu: m.kind === "text" ? messageMenu(m) : [],
		}))
	})

	function messageBody(message) {
		if (message.kind !== "text") return ""
		if (!message.file_url) return paragraphs(message.text)
		return `<p><a href="${encodeURI(message.file_url)}" target="_blank" rel="noopener">${escapeHtml(message.text)}</a></p>`
	}

	function messageMenu(message) {
		return [
			{ label: "Copy text", icon: "lucide-copy", onClick: () => copyText(message.text || "", toast, "Copied") },
			{ label: "Copy link", icon: "lucide-link", onClick: () => copyText(`${window.location.href.split("#")[0]}#msg-${message.id}`, toast, "Link copied") },
		]
	}

	// Connect messages are short, so the reply box is always open. It posts into the thread.
	const reply = ref("")
	const replyTo = ref(null)
	const sending = ref(false)
	const isReplyEmpty = computed(() => !composerText(reply.value))

	async function send() {
		if (isReplyEmpty.value || sending.value) return
		sending.value = true
		try {
			await call("connect.api.messages.send_message", {
				thread: data.value.thread,
				content: composerText(reply.value),
				reply_to: replyTo.value,
			})
			reply.value = ""
			replyTo.value = null
			await load()
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't send the message.")
		} finally {
			sending.value = false
		}
	}

	// A card's own Reply quotes it into the box, as Helpdesk does, and sends as a reply to it.
	function quoteReply(message) {
		replyTo.value = message.id
		reply.value = `<blockquote><p>${escapeHtml(message.text)}</p></blockquote><p></p>`
	}

	function onComposerKey(event) {
		if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return
		event.preventDefault()
		send()
	}

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
	const openSections = ref({ lead: true, project: true, company: true })
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
			reply.value = ""
			replyTo.value = null
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
		crumb: computed(() => lead.value?.project || (loading.value ? "" : "Not found")),
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
		tab,
		tabs: TABS,
		sideOpen,
		openSide: () => (sideOpen.value = true),
		closeSide: () => (sideOpen.value = false),
		companyLabel: computed(() => lead.value?.company?.name || data.value?.company || ""),
		messages,
		reply,
		setReply: (html) => (reply.value = html),
		isReplyEmpty,
		send,
		quoteReply,
		onComposerKey,
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
		// No company until they're revealed: the panel says when their details will show.
		company: lead.is_customer_revealed
			? { name: lead.company, contact: lead.contact.name, email: lead.contact.email, phone: lead.contact.phone }
			: null,
	}
}
