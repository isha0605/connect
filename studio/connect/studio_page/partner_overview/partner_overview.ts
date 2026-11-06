// The partner's Overview: their tier, up to three things to do next, and how far they are from the
// next tier on Frappe Cloud MRR, certified consultants and PMM level. Sample data for now: Connect
// doesn't yet store tier targets, MRR, the partner code or partner managers.

import { computed } from "vue"
import { startTracking } from "@app/utils/tracking"

const STEPS_SHOWN = 3

// Each tier's perks and what a partner needs to reach it. Sample values until Frappe Cloud shares them.
const TIERS = [
	{ name: "Bronze", perks: "10% off Frappe Cloud · Listed in the directory", mrr: 0, certified: 1, pmm: 3 },
	{ name: "Silver", perks: "20% off Frappe Cloud · Full directory profile", mrr: 250000, certified: 2, pmm: 4 },
	{ name: "Gold", perks: "30% off Frappe Cloud · Featured in the directory", mrr: 630000, certified: 4, pmm: 5 },
]

const SAMPLE = {
	tier: "Silver",
	partner_code: "EyZnHMkVq1",
	mrr_updated: "Last 12 months · updated 2 hours ago",
	mrr: [
		["Dec 2025", 182000], ["Jan 2026", 195400], ["Feb 2026", 210800], ["Mar 2026", 208300],
		["Apr 2026", 231900], ["May 2026", 246500], ["Jun 2026", 262000], ["Jul 2026", 279300],
		["Aug 2026", 301200], ["Sep 2026", 318600], ["Oct 2026", 345740], ["Nov 2026", 504640],
	].map(([month, amount]) => ({ month, amount })),
	certified: 5,
	not_certified: ["Rahul Verma", "Ishita Bose"],
	free_certifications: 2,
	pmm: 4,
	last_audit: { date: "14 Mar 2026", auditor: "Aditi Rao" },
	// The audit the partner asked for and hasn't had yet, if any.
	upcoming_audit: null,
	managers: [
		{ name: "Aditi Rao", email: "aditi@example.com" },
		{ name: "Karan Mehta", email: "karan@example.com" },
	],
}

const rupees = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })

function lakhs(amount) {
	return `₹${(amount / 100000).toFixed(1).replace(/\.0$/, "")}L`
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

export default function setup(context) {
	startTracking(context)
	const { router, toast } = context
	const data = SAMPLE

	const tierIndex = TIERS.findIndex((tier) => tier.name === data.tier)
	const tier = TIERS[tierIndex]
	const nextTier = TIERS[tierIndex + 1] || null
	const mrr = data.mrr.at(-1)?.amount || 0

	const tierSteps = TIERS.map((step, index) => ({
		name: step.name,
		isFirst: index === 0,
		isDone: index < tierIndex,
		isCurrent: index === tierIndex,
		isNext: index > tierIndex,
	}))

	// What the next tier needs, against where the partner is.
	const goals = nextTier
		? {
				mrrShort: Math.max(nextTier.mrr - mrr, 0),
				certifiedShort: Math.max(nextTier.certified - data.certified, 0),
				pmmShort: data.pmm < nextTier.pmm,
			}
		: null

	const metCount = goals ? [!goals.mrrShort, !goals.certifiedShort, !goals.pmmShort].filter(Boolean).length : 3

	// Most useful first: an audit takes the longest to book, then revenue, then certifications.
	const doNext = computed(() => {
		if (!goals) return []
		const steps = []
		if (goals.pmmShort) steps.push(auditStep())
		if (goals.mrrShort) {
			steps.push({
				key: "mrr", icon: "lucide-trending-up", isPrimary: false, route: "/customers", action: "See customers",
				title: `Grow Frappe Cloud MRR by ${rupees.format(goals.mrrShort)}`,
				detail: "Bring new customers to Frappe Cloud, or move existing ones to bigger plans.",
			})
		}
		if (data.not_certified.length && data.free_certifications) {
			steps.push({
				key: "free-certs", icon: "lucide-award", isPrimary: false, route: "/partner-certifications", action: "Apply for free",
				title: `${joinNames(data.not_certified)} ${data.not_certified.length > 1 ? "aren't" : "isn't"} certified`,
				detail: `Link a certificate they already have, or use one of your ${data.free_certifications} free certifications.`,
			})
		} else if (goals.certifiedShort) {
			steps.push({
				key: "certs", icon: "lucide-award", isPrimary: false, route: "/partner-certifications", action: "See certifications",
				title: `Certify ${goals.certifiedShort} more consultant${goals.certifiedShort > 1 ? "s" : ""}`,
				detail: `${nextTier.name} needs ${nextTier.certified} certified consultants. You have ${data.certified}.`,
			})
		}
		return steps.slice(0, STEPS_SHOWN).map((step, index, shown) => ({ ...step, isLast: index === shown.length - 1 }))
	})

	function auditStep() {
		const audit = data.upcoming_audit
		if (audit) {
			return {
				key: "audit", icon: "lucide-calendar-check", isPrimary: false, route: "/partner-audits", action: "See audit",
				title: `PMM ${nextTier.pmm} audit on ${audit.date}`,
				detail: "Frappe has your request. Your auditor confirms the agenda a week before.",
			}
		}
		return {
			key: "audit", icon: "lucide-clipboard-check", isPrimary: true, route: "/partner-audits", action: "Request audit",
			title: `Request a PMM ${nextTier.pmm} audit`,
			detail: `${nextTier.name} needs PMM ${nextTier.pmm}. Audits are booked at least 60 days ahead, so ask early.`,
		}
	}

	function copyPartnerCode() {
		navigator.clipboard
			.writeText(data.partner_code)
			.then(() => toast.success("Partner code copied"))
			.catch(() => toast.error("Couldn't copy. Select the code and copy it instead."))
	}

	return {
		breadcrumbItems: [{ label: "Overview", route: "/partner-overview" }],
		partnerCode: data.partner_code,
		copyPartnerCode,
		tier,
		tierSteps,
		nextTier,
		doNext,
		allMet: !nextTier || metCount === 3,
		goTo: (route) => router.push(route),
		goToStep: (step) => router.push(step.route),
		progressTitle: nextTier ? `Progress to ${nextTier.name}` : `You're ${tier.name}`,
		metLabel: `${metCount} of 3 met`,
		mrr: {
			points: data.mrr,
			target: nextTier?.mrr || 0,
			targetLabel: nextTier ? `${nextTier.name} ${lakhs(nextTier.mrr)}` : "",
			amount: rupees.format(mrr),
			short: goals?.mrrShort ? `${rupees.format(goals.mrrShort)} to ${nextTier.name}` : "Target met",
			badge: goals?.mrrShort ? `${Math.floor((mrr / nextTier.mrr) * 100)}% there` : "Met",
			isMet: !goals?.mrrShort,
			updated: data.mrr_updated,
		},
		certs: {
			count: String(data.certified),
			needs: nextTier ? `${nextTier.name} needs ${nextTier.certified}` : "",
			isMet: !goals?.certifiedShort,
			notCertified: data.not_certified.length
				? `${data.not_certified.length} team member${data.not_certified.length > 1 ? "s" : ""} not certified`
				: "",
			free: data.free_certifications ? `${data.free_certifications} free certifications left` : "",
		},
		pmm: {
			level: String(data.pmm),
			needs: nextTier ? `${nextTier.name} needs ${nextTier.pmm}` : "",
			isMet: !goals?.pmmShort,
			lastAudit: data.last_audit ? `Last audit ${data.last_audit.date}` : "No audit yet",
			auditor: data.last_audit ? `By ${data.last_audit.auditor}` : "",
		},
		managers: data.managers.map((manager) => ({
			...manager,
			initials: initials(manager.name),
			href: `mailto:${manager.email}`,
			label: `Email ${manager.name}`,
		})),
	}
}
