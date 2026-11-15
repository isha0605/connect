// The partner's Overview: their tier, up to three things to do next, and where they stand on Frappe
// Cloud MRR, certified consultants and PMM level against the next tier. Sample data for now: Connect
// doesn't yet read the partner's own revenue, audits, partner code or partner managers here.

import { computed } from "vue"
import { startTracking } from "@app/utils/tracking"

const STEPS_SHOWN = 3

// The tiers, lowest first, with the targets from Partner Tier. Perks are sample text; a tier
// without known perks shows none.
const TIERS = [
	{ name: "Beginner", perks: "", mrr: 0, certified: 0, pmm: 0 },
	{ name: "Entry", perks: "", mrr: 0, certified: 2, pmm: 2 },
	{ name: "Emerging", perks: "", mrr: 30000, certified: 2, pmm: 2 },
	{ name: "Bronze", perks: "10% off Frappe Cloud · Listed in the directory", mrr: 63000, certified: 2, pmm: 3 },
	{ name: "Silver", perks: "20% off Frappe Cloud · Full directory profile", mrr: 250000, certified: 3, pmm: 4 },
	{ name: "Gold", perks: "30% off Frappe Cloud · Featured in the directory", mrr: 630000, certified: 4, pmm: 5 },
]

// The tiers partners know as levels. The ones below Bronze are steps on the way.
const PARTNER_LEVELS = ["Bronze", "Silver", "Gold"]

// How far from `first` to `latest` each month has come: mostly rising, with the odd dip.
const SAMPLE_SHAPE = [0, 0.05, 0.12, 0.1, 0.22, 0.3, 0.38, 0.47, 0.6, 0.72, 0.9, 1]

// MRR for the last 12 months, from `first` to `latest`.
function sampleMrr(first, latest) {
	const months = ["Dec 2025", "Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026",
		"Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026", "Nov 2026"]
	return months.map((month, index) => ({
		month,
		amount: Math.round(first + (latest - first) * SAMPLE_SHAPE[index]),
	}))
}

const MANAGERS = [
	{ name: "Aditi Rao", email: "aditi@example.com" },
	{ name: "Karan Mehta", email: "karan@example.com" },
]

// Everyday work waiting elsewhere, shown beside Do next. Only the first two show.
const ATTENTION_SHOWN = 2
const NEW_LEADS = (count) => ({ label: plural(count, "new lead"), route: "/leads" })
const BILL_DUE = { label: "Bill due Dec 5", route: "/partner-invoicing" }

// One partner per tier, so each tier's Do next can be seen with ?tier=<name>. "Ready" is a Silver
// partner who meets everything for Gold.
const DEFAULT_SAMPLE = "Silver"
const SAMPLES = {
	Beginner: {
		tier: "Beginner", mrr: sampleMrr(0, 0), certified: 0, not_certified: ["Rahul Verma", "Ishita Bose", "Neha Kapoor"],
		pmm: 0, last_audit: null, open_findings: 0, upcoming_audit: null, stories: [],
		attention: [{ label: "Publish your listing", route: "/partner-listing" }],
	},
	Entry: {
		tier: "Entry", mrr: sampleMrr(0, 12000), certified: 2, not_certified: ["Neha Kapoor"],
		pmm: 2, last_audit: "2026-02-18", open_findings: 0, upcoming_audit: null,
		stories: [{ industry: "Manufacturing", has_logo: true }],
		attention: [NEW_LEADS(1)],
	},
	Emerging: {
		tier: "Emerging", mrr: sampleMrr(22000, 45000), certified: 2, not_certified: [],
		pmm: 2, last_audit: "2025-12-09", open_findings: 1, upcoming_audit: null,
		stories: [{ industry: "Retail", has_logo: true }],
		attention: [BILL_DUE],
	},
	Bronze: {
		tier: "Bronze", mrr: sampleMrr(90000, 180000), certified: 2, not_certified: ["Rahul Verma"],
		pmm: 3, last_audit: "2026-01-22", open_findings: 0, upcoming_audit: null,
		stories: [{ industry: "Manufacturing", has_logo: true }, { industry: "Manufacturing", has_logo: false }],
		attention: [NEW_LEADS(2)],
	},
	Silver: {
		tier: "Silver", mrr: sampleMrr(182000, 504640), certified: 5, not_certified: ["Rahul Verma", "Ishita Bose"],
		pmm: 4, last_audit: "2026-04-11", open_findings: 2, upcoming_audit: "2026-11-24",
		stories: [{ industry: "Manufacturing", has_logo: true }, { industry: "Manufacturing", has_logo: true }],
		attention: [NEW_LEADS(2), BILL_DUE, { label: "1 customer link", route: "/customers" }],
	},
	Ready: {
		tier: "Silver", mrr: sampleMrr(300000, 655000), certified: 5, not_certified: [],
		pmm: 5, last_audit: "2026-11-02", open_findings: 0, upcoming_audit: null,
		stories: [
			{ industry: "Manufacturing", has_logo: true }, { industry: "Manufacturing", has_logo: true },
			{ industry: "Retail", has_logo: false },
		],
		attention: [NEW_LEADS(1)],
	},
	// Last month dipped below Gold's target, to show a "keep your tier" step.
	Gold: {
		tier: "Gold", mrr: sampleMrr(640000, 590000), certified: 4, not_certified: [],
		pmm: 5, last_audit: "2026-06-03", open_findings: 0, upcoming_audit: null,
		stories: [
			{ industry: "Manufacturing", has_logo: true }, { industry: "Manufacturing", has_logo: true },
			{ industry: "Textile Manufacturing", has_logo: true },
		],
		attention: [{ label: "Bill overdue", route: "/partner-invoicing", isUrgent: true }, NEW_LEADS(3)],
	},
}

// The listing's own rules: an industry with this many stories gets a verified tick (STORIES_FOR_TICK
// in connect/partner/industries.py), and client logos show once this many stories have one
// (MIN_CLIENT_LOGOS in utils/partnerProfile.ts).
const STORIES_FOR_TICK = 2
const LOGOS_TO_SHOW = 4

const REQUIREMENT_NAMES = { mrr: "MRR", certified: "certified consultants", pmm: "PMM" }

const rupees = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })
const shortDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" })

// ₹5.05L, ₹45k, ₹0: short enough to read at a glance on a card.
function compactRupees(amount) {
	if (amount >= 100000) return `₹${Number((amount / 100000).toFixed(2))}L`
	if (amount >= 1000) return `₹${Math.round(amount / 1000)}k`
	return `₹${amount}`
}

function formatDate(isoDate) {
	return shortDate.format(new Date(`${isoDate}T00:00:00`))
}

function plural(count, word, many = `${word}s`) {
	return `${count} ${count === 1 ? word : many}`
}

function initials(name) {
	return name
		.split(" ")
		.map((part) => part[0])
		.join("")
		.slice(0, 2)
		.toUpperCase()
}

function joinNames(names) {
	return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0] || ""
}

// What the partner is short of against a tier's requirements.
function shortfall(target, data, mrr) {
	return {
		mrr: Math.max(target.mrr - mrr, 0),
		certified: Math.max(target.certified - data.certified, 0),
		pmm: data.pmm < target.pmm,
	}
}

// Steps that keep the current tier: the tier review moves a partner down when they fall short of it.
function keepSteps(tier, short, mrr) {
	const steps = []
	if (short.mrr) {
		steps.push({
			key: "keep-mrr", icon: "lucide-circle-alert", route: "/customers", action: "See customers",
			title: `Keep ${tier.name}: bring MRR back to ${rupees.format(tier.mrr)}`,
			detail: `Last month was ${rupees.format(mrr)}. The tier review uses last month's Frappe Cloud revenue.`,
		})
	}
	if (short.certified) {
		steps.push({
			key: "keep-certs", icon: "lucide-circle-alert", route: "/partner-certifications", action: "See certifications",
			title: `Keep ${tier.name}: certify ${plural(short.certified, "more consultant")}`,
			detail: `${tier.name} needs ${tier.certified} certified consultants.`,
		})
	}
	return steps
}

// The audit comes first when the next tier needs a higher PMM level: audits are booked 60+ days ahead.
function auditSteps(data, nextTier) {
	const steps = []
	if (data.upcoming_audit) {
		steps.push({
			key: "audit", icon: "lucide-calendar-check", route: "/partner-audits", action: "See audit", isInfo: true,
			title: `PMM ${nextTier.pmm} audit on ${formatDate(data.upcoming_audit)}`,
			detail: "Frappe has your request. Your auditor confirms the agenda a week before.",
		})
	}
	if (data.open_findings) {
		steps.push({
			key: "findings", icon: "lucide-clipboard-list", route: "/partner-audits", action: "See findings",
			title: `Close ${plural(data.open_findings, "open audit finding")}`,
			detail: "Your last audit raised them. Add what you changed for each one.",
		})
	}
	if (!data.upcoming_audit) {
		steps.push({
			key: "audit", icon: "lucide-clipboard-check", route: "/partner-audits", action: "Request audit",
			title: `Request a PMM ${nextTier.pmm} audit`,
			detail: `${nextTier.name} needs PMM ${nextTier.pmm}. Audits are booked at least 60 days ahead, so ask early.`,
		})
	}
	return steps
}

// Names the team members to certify, up to the number the next tier still needs.
function certificationStep(data, nextTier, missing) {
	const toCertify = data.not_certified.slice(0, missing)
	return {
		key: "certs", icon: "lucide-award", route: "/partner-certifications", action: "See certifications",
		title: toCertify.length ? `Certify ${joinNames(toCertify)}` : `Certify ${plural(missing, "more consultant")}`,
		detail: `${nextTier.name} needs ${nextTier.certified} certified consultants. You have ${data.certified}.`,
	}
}

// A partner whose tier never needed revenue is bringing their first customers, not growing.
function revenueStep(tier, nextTier, missing, mrr) {
	const isFirstRevenue = tier.mrr === 0
	return {
		key: "mrr", icon: "lucide-trending-up", route: "/customers", action: "See customers",
		title: isFirstRevenue
			? "Bring your first customers to Frappe Cloud"
			: `Grow Frappe Cloud MRR by ${rupees.format(missing)}`,
		detail: isFirstRevenue
			? `${nextTier.name} needs ${rupees.format(nextTier.mrr)} a month. You're at ${rupees.format(mrr)}.`
			: "Bring new customers to Frappe Cloud, or move existing ones to bigger plans.",
	}
}

// A partner exactly at a tier's certified count drops a tier if one consultant leaves.
function safetyStep(tier, lowerTier, data) {
	if (!tier.certified || !lowerTier || data.certified !== tier.certified) return null
	const backup = data.not_certified[0]
	return {
		key: "backup", icon: "lucide-award", route: "/partner-certifications", action: "See certifications",
		title: backup ? `Certify ${backup} as a backup` : "Certify a backup consultant",
		detail: `${tier.name} needs ${tier.certified} and you have exactly ${tier.certified}. If one leaves, you drop to ${lowerTier.name}.`,
	}
}

// Ways to strengthen the listing, from the profile's own rules for ticks and client logos.
function listingSteps(data) {
	if (!data.stories.length) {
		return [{
			key: "first-story", icon: "lucide-star", route: "/partner-listing", action: "See listing",
			title: "Add your first success story",
			detail: `Stories show on your profile. ${STORIES_FOR_TICK} in one industry earn it a verified tick.`,
		}]
	}

	const steps = []
	const perIndustry = {}
	data.stories.forEach((story) => (perIndustry[story.industry] = (perIndustry[story.industry] || 0) + 1))
	const almost = Object.keys(perIndustry).find((industry) => perIndustry[industry] === STORIES_FOR_TICK - 1)
	if (almost) {
		steps.push({
			key: "tick", icon: "lucide-badge-check", route: "/partner-listing", action: "See listing",
			title: `Add one more ${almost} success story`,
			detail: `A second story earns ${almost} a verified tick on your profile.`,
		})
	}
	const logos = data.stories.filter((story) => story.has_logo).length
	if (logos < LOGOS_TO_SHOW) {
		steps.push({
			key: "logos", icon: "lucide-building-2", route: "/partner-listing", action: "See listing",
			title: `Add client logos to ${plural(LOGOS_TO_SHOW - logos, "more story", "more stories")}`,
			detail: `Your profile shows client logos once ${LOGOS_TO_SHOW} stories have one. You have ${logos}.`,
		})
	}
	return steps
}

export default function setup(context) {
	startTracking(context)
	const { route, router, toast } = context

	const data = SAMPLES[route.query.tier] || SAMPLES[DEFAULT_SAMPLE]
	const tierIndex = TIERS.findIndex((tier) => tier.name === data.tier)
	const tier = TIERS[tierIndex]
	const nextTier = TIERS[tierIndex + 1] || null
	const mrr = data.mrr.at(-1)?.amount || 0

	// The cards compare against the next tier, or against the current one at the top.
	const target = nextTier || tier
	const toKeep = shortfall(tier, data, mrr)
	const toReach = nextTier ? shortfall(nextTier, data, mrr) : null
	const toTarget = toReach || toKeep
	const left = Object.keys(REQUIREMENT_NAMES).filter((key) => toTarget[key]).map((key) => REQUIREMENT_NAMES[key])

	// The banner shows the partner levels only. Below Bronze, all three are still ahead.
	const tierSteps = TIERS.map((step, index) => ({ step, index }))
		.filter(({ step }) => PARTNER_LEVELS.includes(step.name))
		.map(({ step, index }, position) => ({
			name: step.name,
			isFirst: position === 0,
			isDone: index < tierIndex,
			isCurrent: index === tierIndex,
			isNext: index > tierIndex,
		}))

	// Keeping the tier comes first, then the next tier's gaps from slowest to fix to fastest.
	const doNext = computed(() => {
		const steps = keepSteps(tier, toKeep, mrr)
		if (toReach) {
			if (toReach.pmm) steps.push(...auditSteps(data, nextTier))
			if (toReach.certified) steps.push(certificationStep(data, nextTier, toReach.certified))
			if (toReach.mrr) steps.push(revenueStep(tier, nextTier, toReach.mrr, mrr))
		}
		// Free slots go to protecting the tier, then to strengthening the listing.
		const safety = safetyStep(tier, TIERS[tierIndex - 1], data)
		if (safety && !toKeep.certified) steps.push(safety)
		steps.push(...listingSteps(data))

		// Only the first step gets a button; the rest are quiet rows that open their page.
		return steps.slice(0, STEPS_SHOWN).map((step, index, shown) => ({
			...step,
			isPrimary: index === 0 && !step.isInfo,
			isLast: index === shown.length - 1,
		}))
	})

	const attention = data.attention.slice(0, ATTENTION_SHOWN)

	function copyPartnerCode() {
		navigator.clipboard
			.writeText("EyZnHMkVq1")
			.then(() => toast.success("Partner code copied"))
			.catch(() => toast.error("Couldn't copy. Select the code and copy it instead."))
	}

	const lastAudit = data.last_audit ? `Last audit ${formatDate(data.last_audit)}` : "No audit yet"

	return {
		breadcrumbItems: [{ label: "Overview", route: "/partner-overview" }],
		partnerCode: "EyZnHMkVq1",
		copyPartnerCode,
		tier,
		tierSteps,
		nextTier,
		doNext,
		attention,
		allMet: !left.length,
		allMetText: nextTier
			? `You meet everything for ${nextTier.name}. The next tier review moves you up.`
			: `You're ${tier.name}. Keep all three to stay here.`,
		goTo: (path) => router.push(path),
		goToStep: (step) => router.push(step.route),
		openOnEnter: (event, path) => event.key === "Enter" && router.push(path),
		openStepOnEnter: (event, step) => event.key === "Enter" && !step.isPrimary && router.push(step.route),
		progressTitle: nextTier ? `Progress to ${nextTier.name}` : `Staying ${tier.name}`,
		leftLabel: left.length ? `${left.length} ${nextTier ? "to go" : "at risk"}: ${joinNames(left)}` : "All three met",
		mrr: {
			points: data.mrr,
			amount: compactRupees(mrr),
			target: target.mrr ? `/ ${compactRupees(target.mrr)}` : "",
		},
		certs: { count: String(data.certified), target: `/ ${target.certified}` },
		pmm: {
			level: String(data.pmm),
			target: `/ ${target.pmm}`,
			auditBadge: data.upcoming_audit ? `Audit ${formatDate(data.upcoming_audit)}` : "",
			meta: data.open_findings ? `${lastAudit} · ${data.open_findings} open` : lastAudit,
		},
		managers: MANAGERS.map((manager) => ({
			...manager,
			initials: initials(manager.name),
			href: `mailto:${manager.email}`,
			label: `Email ${manager.name}`,
		})),
	}
}
