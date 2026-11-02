import { toTime } from "@app/utils/partnerRecords"

// What the partner's Leads pages share. A lead is a brief a customer sent the partner
// (a Project Quote); connect.api.leads serves it.

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

// The assignable team as Select options, with "Unassigned" first.
export const ownerOptions = (team) => [
	{ label: "Unassigned", value: "none" },
	...team.map((member) => ({ label: member.full_name || member.user, value: member.user })),
]
