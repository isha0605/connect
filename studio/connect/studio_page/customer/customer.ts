// One customer, laid out like a deal in Frappe CRM: owner and stage in the top bar, the record in
// tabs, and a side panel of facts edited in place. The same tabs a lead has (Follow-ups,
// Activity, Notes), so a lead that's won keeps its history. A saved customer (one who hired the
// partner on Connect) is read from connect.api.partner_customers; the sample ones from
// partnerCustomers.ts stay in the page's memory.

import { computed, ref, watch } from "vue"
import { dialog, toast } from "frappe-ui"
import {
	STAGES,
	customerActivity,
	editCustomer,
	findCustomer,
	invoicesOf,
	isLinked,
	isSampleCustomer,
	longDate,
	money,
	removeCustomer,
	restoreCustomer,
	sitesOf,
	toBookCustomer,
} from "@app/utils/partnerCustomers"
import {
	ASSIGNABLE,
	FIRM,
	FOLLOW_UP_MODES,
	ME,
	activityRows,
	copyText,
	clockOrDate,
	emptyFollowUp,
	followUpRows,
	followUpValues,
	logActivity,
	saveFollowUpForm,
	teamName,
	toActivityEntries,
	toFollowUpRows,
	toNoteRows,
} from "@app/utils/partnerRecords"
import { startTracking } from "@app/utils/tracking"

const TIER_DISCOUNT = 10
const EMAIL_PATTERN = /^\S+@\S+\.\S+$/

const CONTACT_FIELDS = [
	{ key: "contact", label: "Name", type: "text" },
	{ key: "email", label: "Email", type: "email" },
	{ key: "phone", label: "Phone", type: "tel" },
]
const DETAIL_FIELDS = [
	{ key: "industry", label: "Industry", type: "text" },
	{ key: "country", label: "Country", type: "text" },
]
export default function setup(context) {
	startTracking(context)

	const { call } = context
	const customerId = computed(() => context.router.currentRoute.value.params.customer_id)
	// The saved customer as get_customer returns it, with its notes, follow-ups and activity.
	const saved = ref(null)
	const savedTeam = ref([])
	const loadingSaved = ref(false)
	const customer = computed(() => (saved.value ? toBookCustomer(saved.value) : findCustomer(customerId.value)))

	async function loadSaved() {
		if (!customerId.value || isSampleCustomer(customerId.value)) {
			saved.value = null
			return
		}
		// Another customer's record mustn't show while this one loads.
		if (saved.value?.name !== customerId.value) saved.value = null
		loadingSaved.value = !saved.value
		try {
			const result = await call("connect.api.partner_customers.get_customer", { name: customerId.value })
			saved.value = result.customer
			savedTeam.value = result.team
		} catch {
			saved.value = null
		} finally {
			loadingSaved.value = false
		}
	}
	watch(customerId, loadSaved, { immediate: true })

	// Saves what the team changed on a saved customer, then reads it again for its Activity.
	async function saveSaved(values) {
		try {
			await call("connect.api.partner_customers.update_customer", { name: customerId.value, ...values })
			await loadSaved()
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't save the change.")
		}
	}
	const isPartnerPays = computed(() => customer.value?.billing === "partner")
	const meName = teamName(ME)

	// ── Top bar: owner and stage ────────────────────────────────────────────
	function change(field, label, from, to, display = (value) => value) {
		if (from === to) return
		if (saved.value) {
			saveSaved(field === "stage" ? { stage: STAGES[to].label } : { assigned_to: to })
			return
		}
		editCustomer(customer.value.id, { [field]: to })
		logActivity(customer.value.id, { by: meName, kind: "change", field: label, from: display(from) || "Not set", to: display(to) || "Not set" })
	}

	const stageMenu = computed(() =>
		Object.entries(STAGES).map(([value, stage]) => ({
			label: stage.label,
			onClick: () => change("stage", "Stage", customer.value.stage, value, (v) => STAGES[v]?.label),
		})),
	)
	const assignable = computed(() =>
		saved.value
			? savedTeam.value.map((member) => ({ id: member.user, name: member.full_name || member.user }))
			: ASSIGNABLE,
	)
	const ownerMenu = computed(() =>
		assignable.value.map((person) => ({
			label: person.name,
			onClick: () => change("owner", "Owner", customer.value.owner, person.id, teamName),
		})),
	)

	// ── Tabs ────────────────────────────────────────────────────────────────
	const tab = ref("sites")
	watch(customerId, () => (tab.value = "sites"))
	const tabs = computed(() =>
		[
			{ value: "sites", label: "Sites", iconLeft: "lucide-globe" },
			{ value: "invoices", label: "Invoices", iconLeft: "lucide-receipt" },
			{ value: "followups", label: "Follow-ups", iconLeft: "lucide-phone" },
			{ value: "activity", label: "Activity", iconLeft: "lucide-history" },
			{ value: "notes", label: "Notes", iconLeft: "lucide-notebook-pen" },
			customer.value?.source === "connect" && { value: "connect", label: "Connect", iconLeft: "lucide-message-square" },
		].filter(Boolean),
	)

	const sites = computed(() =>
		customer.value
			? sitesOf(customer.value).map((site) => ({
					...site,
					meta: isPartnerPays.value
						? site.plan
						: [site.plan, site.region, site.status, site.apps.join(", ")].filter(Boolean).join(" · "),
					amountLabel: site.amount != null ? money(site.amount, site.currency) : "",
				}))
			: [],
	)
	const invoices = computed(() =>
		customer.value
			? invoicesOf(customer.value).map((invoice) => ({ ...invoice, amountLabel: money(invoice.amount, invoice.currency) }))
			: [],
	)

	// ── Follow-ups ──────────────────────────────────────────────────────────
	const followUps = computed(() => {
		if (saved.value) return toFollowUpRows(saved.value.follow_ups)
		return customer.value ? followUpRows(customer.value.id) : []
	})
	const followUpOpen = ref(false)
	const followUpForm = ref(emptyFollowUp())

	function startFollowUp() {
		followUpForm.value = emptyFollowUp(customer.value.contact || "")
		followUpOpen.value = true
	}

	async function saveFollowUp() {
		if (saved.value) {
			try {
				saved.value = await call("connect.api.partner_customers.log_customer_follow_up", {
					name: customerId.value,
					values: followUpValues(followUpForm.value),
				})
			} catch (error) {
				toast.error(error?.messages?.[0] || "Couldn't add the follow-up.")
				return
			}
		} else {
			saveFollowUpForm(customer.value.id, followUpForm.value)
		}
		followUpOpen.value = false
		toast.success("Follow-up added")
	}

	// ── Activity ────────────────────────────────────────────────────────────
	const expandedGroups = ref({})
	const activity = computed(() => {
		if (!customer.value) return []
		const entries = saved.value ? toActivityEntries(saved.value.activity) : customerActivity(customer.value)
		return activityRows(entries, expandedGroups.value)
	})

	function toggleGroup(id) {
		expandedGroups.value = { ...expandedGroups.value, [id]: !expandedGroups.value[id] }
	}

	// ── Notes: the team's own about this customer, never sent to them ─────
	const noteDraft = ref("")
	const sampleNotes = ref({})
	const notes = computed(() => {
		if (saved.value) return toNoteRows(saved.value.notes)
		return sampleNotes.value[customerId.value] || []
	})

	async function addNote() {
		const text = noteDraft.value.trim()
		if (!text) return
		if (saved.value) {
			try {
				const notesSaved = await call("connect.api.partner_customers.add_customer_note", { name: customerId.value, content: text })
				saved.value = { ...saved.value, notes: notesSaved }
			} catch (error) {
				toast.error(error?.messages?.[0] || "Couldn't add the note.")
				return
			}
		} else {
			const note = { id: `note-${Date.now()}`, text, byName: meName, time: clockOrDate(Date.now()) }
			sampleNotes.value = { ...sampleNotes.value, [customerId.value]: [note, ...notes.value] }
		}
		noteDraft.value = ""
		toast.success("Note added")
	}

	// ── Side panel: fields edited in place, saved on blur ───────────────────
	const draft = ref({})
	watch(
		customer,
		(value) => (draft.value = value ? Object.fromEntries([...CONTACT_FIELDS, ...DETAIL_FIELDS].map((f) => [f.key, value[f.key] || ""])) : {}),
		{ immediate: true },
	)

	function commit(key) {
		const field = [...CONTACT_FIELDS, ...DETAIL_FIELDS].find((f) => f.key === key)
		const value = draft.value[key].trim()
		const current = customer.value[key] || ""
		// A saved customer's details are their own Connect account's.
		if (saved.value) {
			if (value !== current) toast.info("Their details come from their Connect account.")
			draft.value[key] = current
			return
		}
		if ((key === "email" && value && !EMAIL_PATTERN.test(value)) || (key === "contact" && !value)) {
			if (key === "email") toast.error("Enter a valid email")
			draft.value[key] = current
			return
		}
		change(key, field.label === "Name" ? "Contact" : field.label, current, value)
	}

	const openSections = ref({ contact: true, details: true, billing: true })
	function toggleSection(key) {
		openSections.value = { ...openSections.value, [key]: !openSections.value[key] }
	}

	const partnerCodeLabel = computed(() => {
		const c = customer.value
		if (!c) return ""
		if (c.linked) return `Linked ${longDate(c.linked)}`
		if (c.codeShared) return `Shared ${longDate(c.codeShared)}, not linked yet`
		return "Not linked yet"
	})
	// Whether the Billing section offers "Switch to Partner pays" for this customer.
	const canSwitchBilling = computed(() => {
		const c = customer.value
		// Only a linked, active customer who pays Frappe themselves, with no request already waiting.
		return Boolean(c && c.billing === "customer" && !c.billingSwitch && c.stage !== "churned" && c.linked)
	})

	// ── Quick actions ───────────────────────────────────────────────────────
	const moreMenu = computed(() => {
		// Unlinking and deleting are for sample customers.
		if (!customer.value || saved.value) return []
		return isLinked(customer.value)
			? [{ label: "Unlink", icon: "lucide-unlink", theme: "red", onClick: unlink }]
			: [{ label: "Delete", icon: "lucide-trash-2", theme: "red", onClick: remove }]
	})

	function unlink() {
		const { id, name } = customer.value
		dialog.danger({
			title: `Unlink ${name}?`,
			message: "Their MRR stops counting toward your tier, and you lose sight of their sites and invoices.",
			confirmLabel: "Unlink",
			onConfirm: ({ close }) => {
				removeCustomer(id)
				close()
				context.router.push("/customers")
				toast.success(`${name} unlinked`)
			},
		})
	}

	function remove() {
		const { id, name } = customer.value
		removeCustomer(id)
		context.router.push("/customers")
		toast.success(`${name} deleted`, { action: { label: "Undo", onClick: () => restoreCustomer(id) } })
	}

	// ── Switching to Partner pays ───────────────────────────────────────────
	// The owner starts it; the customer confirms in Frappe Cloud, since their billing moves away
	// from them.
	const switchOpen = ref(false)
	function requestSwitch() {
		editCustomer(customer.value.id, { billingSwitch: "requested" })
		logActivity(customer.value.id, { by: meName, kind: "note", text: "asked the customer to switch to Partner pays" })
		switchOpen.value = false
		toast.success(`Sent to ${customer.value.contact || customer.value.name} to confirm`)
	}


	return {
		customer,
		loadingSaved,
		crumb: computed(() => customer.value?.name || (loadingSaved.value ? "" : "Not found")),
		ownerName: computed(() => (saved.value ? customer.value.ownerName : teamName(customer.value?.owner)) || "Assign"),
		hasOwner: computed(() => Boolean(customer.value?.owner)),
		stageLabel: computed(() => (customer.value ? STAGES[customer.value.stage].label : "")),
		stageMenu,
		ownerMenu,
		tab,
		tabs,
		sites,
		invoices,
		isPartnerPays,
		followUps,
		followUpOpen,
		followUpForm,
		followUpModes: FOLLOW_UP_MODES,
		startFollowUp,
		saveFollowUp,
		closeFollowUp: () => (followUpOpen.value = false),
		activity,
		toggleGroup,
		notes,
		noteDraft,
		addNote,
		draft,
		commit,
		contactFields: CONTACT_FIELDS,
		detailFields: DETAIL_FIELDS,
		openSections,
		toggleSection,
		sourceLabel: computed(() => (customer.value?.source === "connect" ? "Connect" : "Added by you")),
		mrrLabel: computed(() => (customer.value?.mrr ? money(customer.value.mrr, FIRM.currency) : "—")),
		whoPaysLabel: computed(() => (isPartnerPays.value ? "You" : "The customer")),
		partnerCodeLabel,
		canSwitchBilling,
		moreMenu,
		emailHref: computed(() => (customer.value?.email ? `mailto:${customer.value.email}` : "")),
		emailTooltip: computed(() => `Email ${customer.value?.contact || customer.value?.name || ""}`),
		copyLink: () => copyText(window.location.href, toast, "Link copied"),
		switchOpen,
		openSwitch: () => (switchOpen.value = true),
		closeSwitch: () => (switchOpen.value = false),
		requestSwitch,
		switchLines: computed(() => {
			const c = customer.value
			if (!c) return []
			return [
				`Frappe bills you for ${c.name} once ${c.contact || c.name} confirms in Frappe Cloud.`,
				`Your ${TIER_DISCOUNT}% tier discount applies to it.`,
				"You'll see the monthly amount only, not their plans and invoices.",
			]
		}),
	}
}
