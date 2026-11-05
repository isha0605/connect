import { toTime } from "@app/utils/partnerRecords"

// What the partner's Leads pages share. A lead is a customer's conversation with the partner
// (a Partner Lead) and every requirement they sent in it; connect.api.leads serves it.

// The PRM portal's stages. Won comes from the customer hiring the partner, never by hand.
export const PRM_STAGES = [
	"Open", "Qualification", "Demo/Making", "Proposal/Quotation", "Follow Up",
	"Negotiation", "Ready to Close", "Won", "Lost", "Junk", "Closed",
]
export const CLOSED_STAGES = ["Won", "Lost", "Junk", "Closed"]
export const PROBABILITY = ["Hot", "Warm", "Cold"]
export const LOST_REASONS = ["Lost to competitor", "No budget", "Not responding", "Chose another product", "Other"]

// A coloured dot for the stage, as CRM shows status; colour only where the lead is finished.
const STAGE_COLORS = { Won: "var(--surface-green-7)", Lost: "var(--surface-red-6)", Junk: "var(--surface-gray-5)", Closed: "var(--surface-gray-5)" }
export const stageColor = (stage) => STAGE_COLORS[stage] || "var(--surface-blue-7)"

export const isClosed = (lead) => CLOSED_STAGES.includes(lead.stage)
export const lastAt = (lead) => toTime(lead.last_message_at)

// The assignable team as Select options, with "Unassigned" first. With CRM sync on, someone
// without a CRM user is marked: they can't take a lead until they're on the CRM.
export const ownerOptions = (team) => [
	{ label: "Unassigned", value: "none" },
	...team.map((member) => ({ label: ownerLabel(member), value: member.user })),
]

const ownerLabel = (member) => {
	const name = member.full_name || member.user
	return member.in_crm === false ? `${name} · Not in CRM` : name
}

// The lead's title is its newest requirement. With several, a badge beside it counts them all.
export const leadTitle = (lead) => lead.project_name
export const requirementBadge = (lead) => (lead.requirement_count > 1 ? String(lead.requirement_count) : "")

// The badge's tooltip names them, newest first: "3 requirements: erp, p2, billing".
const NAMED = 5
export function requirementTooltip(lead) {
	const names = lead.requirement_names || []
	const shown = names.slice(0, NAMED).join(", ")
	const rest = names.length > NAMED ? ` and ${names.length - NAMED} more` : ""
	return `${lead.requirement_count} requirements: ${shown}${rest}`
}
