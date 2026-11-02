// What a partner's lead or customer record carries besides its own facts: the firm, its team,
// follow-ups the team logged and the activity history, keyed by record id. Sample data from
// Pragati's prototype (src/data/records.js and partnerAccount.js); nothing here is saved.

import { reactive } from "vue"

export const FIRM = { name: "Software@Work", code: "EyZnHMkVq1", currency: "INR" }

// Who's acting in the sample data: the firm's owner.
export const ME = "farhan-qureshi"

export const TEAM = [
	{ id: "farhan-qureshi", name: "Farhan Qureshi", roles: ["owner"] },
	{ id: "anuja-deshmukh", name: "Anuja Deshmukh", roles: ["owner"] },
	{ id: "rahul-verma", name: "Rahul Verma", roles: ["sales"] },
	{ id: "ishita-bose", name: "Ishita Bose", roles: ["finance"] },
	{ id: "aakash-gupta", name: "Aakash Gupta", roles: ["sales"] },
]

// The people a lead or customer can be assigned to.
export const ASSIGNABLE = TEAM.filter((person) => person.roles.includes("sales") || person.roles.includes("owner"))

export const teamName = (id) => TEAM.find((person) => person.id === id)?.name || ""

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" })
export const shortDate = (iso) => DAY.format(new Date(iso))

// Today's messages show the time, older ones the date, as Frappe CRM's lists do.
export function clockOrDate(time) {
	const date = new Date(time)
	return new Date().toDateString() === date.toDateString()
		? date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase()
		: date.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

export function timeAgo(time) {
	const minutes = Math.round((Date.now() - time) / 60000)
	const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" })
	if (minutes < 60) return format.format(-Math.max(minutes, 1), "minute")
	if (minutes < 60 * 24) return format.format(-Math.round(minutes / 60), "hour")
	if (minutes < 60 * 24 * 30) return format.format(-Math.round(minutes / 1440), "day")
	if (minutes < 60 * 24 * 365) return format.format(-Math.round(minutes / 43200), "month")
	return format.format(-Math.round(minutes / 525600), "year")
}

// Frappe sends "2026-10-30 20:16:18.138995"; Safari only parses it with a "T".
export const toTime = (value) => (value ? new Date(String(value).replace(" ", "T")).getTime() : 0)

export async function copyText(text, toast, done) {
	try {
		await navigator.clipboard.writeText(text)
		toast.success(done)
	} catch {
		toast.error("Couldn't copy. Select the text and copy it instead.")
	}
}

// ── Follow-ups and activity ─────────────────────────────────────────────────
const hoursAgo = (hours) => Date.now() - hours * 3600000
const at = (iso, hour = 10) => new Date(`${iso}T${String(hour).padStart(2, "0")}:00:00`).getTime()

export const FOLLOW_UP_ICONS = { Call: "lucide-phone", Demo: "lucide-presentation", Email: "lucide-mail", Meeting: "lucide-users" }
export const FOLLOW_UP_MODES = Object.keys(FOLLOW_UP_ICONS).map((mode) => ({ label: mode, value: mode }))
const ACTIVITY_ICONS = { created: "lucide-sparkles", change: "lucide-pencil", note: "lucide-link" }

// `by` is a Team id; `spokeTo` is whoever picked up.
const SEED_FOLLOW_UPS = {
	"pv-northwind": [
		{ id: "f-nw-1", at: hoursAgo(1), by: "farhan-qureshi", mode: "Call", spokeTo: "Meera Iyer", notes: "Walked through goods receipt. They want barcode labels printed at the dock, not the office." },
	],
	"pv-anonymous": [
		{ id: "f-an-1", at: hoursAgo(19), by: "rahul-verma", mode: "Email", spokeTo: "", notes: "Quote breakdown sent through Connect. No reply yet." },
	],
	kestrel: [
		{ id: "f-ks-3", at: at("2026-10-21", 12), by: "rahul-verma", mode: "Meeting", spokeTo: "Arjun Nair", notes: "Quarterly review. Asked for a second warehouse next year." },
		{ id: "f-ks-2", at: at("2026-09-04"), by: "farhan-qureshi", mode: "Call", spokeTo: "Arjun Nair", notes: "Purchase approvals slow. Agreed to add a second approver." },
		{ id: "f-ks-1", at: at("2025-08-12", 14), by: "farhan-qureshi", mode: "Demo", spokeTo: "Arjun Nair", notes: "Training for the stores team." },
	],
	halcyon: [
		{ id: "f-hc-1", at: at("2026-10-02", 11), by: "anuja-deshmukh", mode: "Call", spokeTo: "Ritu Sharma", notes: "Renewal is in March. Happy with support." },
	],
	"rivermark-textiles": [
		{ id: "f-rm-1", at: at("2026-10-28", 15), by: "rahul-verma", mode: "Meeting", spokeTo: "Kavya Iyer", notes: "Kick-off. Project champion is Kavya; BOMs come from the floor supervisor." },
	],
}

// `kind`: created | change (field, from, to) | note (text). `by` is a display name.
const SEED_ACTIVITY = {
	"pv-northwind": [
		{ id: "a-nw-1", at: hoursAgo(5.5), by: "Farhan Qureshi", kind: "change", field: "Assigned to", from: "Unassigned", to: "Farhan Qureshi" },
		{ id: "a-nw-2", at: hoursAgo(5), by: "Farhan Qureshi", kind: "change", field: "Stage", from: "Open", to: "Qualification" },
		{ id: "a-nw-3", at: hoursAgo(4.1), by: "Farhan Qureshi", kind: "change", field: "Stage", from: "Qualification", to: "Proposal/Quotation" },
		{ id: "a-nw-4", at: hoursAgo(2.5), by: "Farhan Qureshi", kind: "change", field: "Stage", from: "Proposal/Quotation", to: "Negotiation" },
	],
	"pv-anonymous": [
		{ id: "a-an-1", at: hoursAgo(27), by: "Farhan Qureshi", kind: "change", field: "Assigned to", from: "Unassigned", to: "Rahul Verma" },
		{ id: "a-an-2", at: hoursAgo(20.1), by: "Rahul Verma", kind: "change", field: "Stage", from: "Open", to: "Proposal/Quotation" },
	],
	kestrel: [
		{ id: "a-ks-1", at: at("2025-07-14"), by: "Connect", kind: "created", text: "sent this brief" },
		{ id: "a-ks-2", at: at("2025-07-30", 16), by: "Farhan Qureshi", kind: "change", field: "Stage", from: "Negotiation", to: "Won" },
		{ id: "a-ks-3", at: at("2025-08-02", 12), by: "Arjun Nair", kind: "note", text: "linked their sites to your partner code" },
		{ id: "a-ks-4", at: at("2025-08-20", 9), by: "Arjun Nair", kind: "change", field: "Billing", from: "Customer pays", to: "Partner pays" },
		{ id: "a-ks-5", at: at("2025-09-15", 9), by: "Farhan Qureshi", kind: "change", field: "Stage", from: "Onboarding", to: "Live" },
	],
}

const records = reactive({ followUps: SEED_FOLLOW_UPS, activity: SEED_ACTIVITY })

export function addFollowUp(id, followUp) {
	;(records.followUps[id] ||= []).unshift({ id: `f-${Date.now()}`, at: Date.now(), by: ME, ...followUp })
}

export function logActivity(id, entry) {
	;(records.activity[id] ||= []).push({ id: `a-${Date.now()}-${Math.random()}`, at: Date.now(), ...entry })
}

// Oldest first, as a timeline reads.
export const activityOf = (id) => [...(records.activity[id] || [])].sort((a, b) => a.at - b.at)

// Newest first, with what a row shows worked out.
export const followUpRows = (id) =>
	[...(records.followUps[id] || [])]
		.sort((a, b) => b.at - a.at)
		.map((followUp) => ({
			...followUp,
			icon: FOLLOW_UP_ICONS[followUp.mode],
			title: followUp.spokeTo ? `${followUp.mode} with ${followUp.spokeTo}` : followUp.mode,
			byName: teamName(followUp.by) || "Someone",
			dateLabel: shortDate(new Date(followUp.at).toISOString().slice(0, 10)),
		}))

// Consecutive changes by one person fold into one entry with "Show +N changes".
function groupActivity(entries) {
	const groups = []
	for (const entry of entries) {
		const last = groups.at(-1)
		if (entry.kind === "change" && last?.kind === "change" && last.by === entry.by) last.rest.push(entry)
		else groups.push({ ...entry, rest: [] })
	}
	return groups
}

const describe = (entry) =>
	entry.kind === "change" ? { verb: "changed ", field: entry.field, from: entry.from, to: entry.to } : { verb: entry.text }

// The timeline's rows; `expanded` holds the group ids whose folded changes are shown.
export function activityRows(entries, expanded) {
	const groups = groupActivity(entries)
	return groups.map((group, index) => {
		const isOpen = Boolean(expanded[group.id])
		const shown = [group, ...(isOpen ? group.rest : [])]
		const count = group.rest.length
		return {
			id: group.id,
			icon: ACTIVITY_ICONS[group.kind],
			isLast: index === groups.length - 1,
			lines: shown.map((entry) => ({ id: entry.id, by: entry.by, ago: timeAgo(entry.at), ...describe(entry) })),
			toggleLabel: count ? `${isOpen ? "Hide" : "Show"} +${count} ${count === 1 ? "change" : "changes"} from ${group.by}` : "",
		}
	})
}

// Log a follow-up: the dialog's form, starting today with a call to `contact`.
export const TODAY = new Date().toISOString().slice(0, 10)
export const emptyFollowUp = (contact = "") => ({ date: TODAY, mode: "Call", spokeTo: contact, notes: "" })

export function saveFollowUpForm(id, form) {
	const { date, mode, spokeTo, notes } = form
	const followUp = { at: date === TODAY ? Date.now() : new Date(`${date}T12:00:00`).getTime(), mode, spokeTo: spokeTo.trim(), notes: notes.trim() }
	addFollowUp(id, followUp)
	logActivity(id, { by: teamName(ME), kind: "note", text: `logged a ${mode.toLowerCase()}${followUp.spokeTo ? ` with ${followUp.spokeTo}` : ""}` })
}

// ── Saved records (connect.partner.doctype.partner_customer.customer_records) ──
// The same shapes as the sample ones above, so a lead's and a customer's tabs read them alike.
export const toActivityEntries = (activity) => activity.map((entry) => ({ ...entry, at: toTime(entry.at) }))

export const toNoteRows = (notes) =>
	notes.map((note) => ({ id: note.id, text: note.text, byName: note.by_name || note.by, time: clockOrDate(toTime(note.at)) }))

export const toFollowUpRows = (followUps) =>
	followUps.map((followUp) => ({
		id: followUp.id,
		notes: followUp.notes,
		icon: FOLLOW_UP_ICONS[followUp.mode],
		title: followUp.spoke_to ? `${followUp.mode} with ${followUp.spoke_to}` : followUp.mode,
		byName: followUp.by_name || followUp.by,
		dateLabel: shortDate(String(followUp.at).slice(0, 10)),
	}))

// The Log a follow-up dialog's form as log_*_follow_up takes it: today's is now, an earlier one midday.
export function followUpValues(form) {
	const pad = (n) => String(n).padStart(2, "0")
	const now = new Date()
	const clock = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
	return {
		followed_up_on: `${form.date} ${form.date === TODAY ? clock : "12:00:00"}`,
		mode: form.mode,
		spoke_to: form.spokeTo.trim(),
		notes: form.notes.trim(),
	}
}
