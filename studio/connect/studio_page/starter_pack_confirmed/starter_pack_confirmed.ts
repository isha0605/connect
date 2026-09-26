// Shown once a Starter Pack Order is paid — the checkout page redirects here. Everything
// on it comes from the order: the partner is whoever the round robin (or an admin) assigned,
// and the activity lists only what actually happened, with its real time.

import { computed } from "vue"
import { MODULE_ICONS, OUR_NEEDS, PACK_PITCHES, commercialTerms } from "@app/utils/recommendation"

const ORDER_STATUS_BADGES = {
	New: { label: "Awaiting partner", theme: "gray" },
	"Partner Assigned": { label: "Partner assigned", theme: "blue" },
	"In Progress": { label: "In progress", theme: "blue" },
	Completed: { label: "Completed", theme: "green" },
}

const PAYMENT_BADGES = {
	Paid: { label: "Paid", theme: "green" },
	"Partially Refunded": { label: "Partially refunded", theme: "orange" },
	Refunded: { label: "Refunded", theme: "gray" },
}

// How many industries the partner card names before "and N more".
const INDUSTRIES_SHOWN = 3

export default function setup(context) {
	const { route, router, call, catalog, order, loadError, openKeys } = context

	const orderName = String(route.query.order || "")

	function load() {
		loadError.value = false
		order.value = null
		if (!orderName) {
			loadError.value = true
			return
		}
		call("connect.api.starter_pack.get_order", { order: orderName })
			.then((data) => {
				// Not paid (yet, or any more): checkout is the page that shows that and offers a retry.
				if (!PAYMENT_BADGES[data.payment_status]) {
					if (data.payment_request) {
						router.replace({ path: "/starter-pack-checkout", query: { reference_id: data.payment_request } })
					} else {
						loadError.value = true
					}
					return
				}
				order.value = data
			})
			.catch(() => {
				loadError.value = true
			})
	}
	load()

	function money(amount) {
		return new Intl.NumberFormat("en-IN", {
			style: "currency",
			currency: catalog.data?.currency || "INR",
			maximumFractionDigits: 0,
		}).format(amount || 0)
	}

	// get_order sends ISO datetimes with the site's offset, so this is right in any zone.
	function ago(value) {
		if (!value) return ""
		const at = new Date(value)
		const minutes = Math.floor((Date.now() - at.getTime()) / 60000)
		if (minutes < 1) return "just now"
		if (minutes < 60) return `${minutes} min ago`
		if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} hr ago`
		return at.toLocaleDateString("en-US", { month: "short", day: "numeric" })
	}

	const packs = computed(() => order.value?.packs || [])
	const packNamesLabel = computed(() => {
		const names = packs.value.map((p) => p.pack_name)
		if (names.length <= 1) return names[0] || ""
		return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`
	})
	const manyPacks = computed(() => packs.value.length > 1)

	const partner = computed(() => order.value?.partner || null)
	const partnerFirstName = computed(() => partner.value?.partner_name.split(" ")[0] || "your partner")

	const isRefunded = computed(() => order.value?.payment_status === "Refunded")
	const heading = computed(() => (isRefunded.value ? "Refunded" : "Confirmed"))
	const subheading = computed(() => {
		const what = `Your ${packNamesLabel.value} ${manyPacks.value ? "packs were" : "pack was"}`
		if (isRefunded.value) return `${what} refunded. Nothing more will be charged.`
		const paid = `Your ${packNamesLabel.value} ${manyPacks.value ? "packs are" : "pack is"} paid for`
		if (!partner.value) {
			return `${paid}. We're matching you with a Partner — they'll show up here as soon as one is assigned.`
		}
		return `${paid} and matched with a Partner. Message ${partnerFirstName.value} to agree a kickoff date, and they'll take it from there.`
	})

	const partnerStats = computed(() => {
		const p = partner.value
		if (!p) return []
		const stats = [
			{
				key: "rate",
				icon: "lucide-circle-dollar-sign",
				// hourly_rate carries no currency; the directory's partners quote in USD.
				text: p.hourly_rate ? `From $${Number(p.hourly_rate).toLocaleString("en-US")}/hr` : "Undisclosed",
				sub: "",
				muted: !p.hourly_rate,
			},
		]
		if (p.rating) {
			stats.push({
				key: "rating",
				icon: "lucide-star",
				text: Number(p.rating).toFixed(1),
				sub: `(${p.review_count})`,
				muted: false,
			})
		}
		if (p.response_time_hours) {
			stats.push({
				key: "response",
				icon: "lucide-clock",
				text: `Typically ${p.response_time_hours}h`,
				sub: "",
				muted: false,
			})
		}
		return stats
	})

	const partnerExpertise = computed(() => {
		const industries = partner.value?.industries || []
		if (!industries.length) return ""
		const rest = industries.length - INDUSTRIES_SHOWN
		const lead = industries.slice(0, INDUSTRIES_SHOWN).join(", ")
		return `Expertise across ${lead}${rest > 0 ? ` and ${rest} more` : ""}`
	})

	// Newest first, like the prototype. Each entry is something that happened to this order.
	const activity = computed(() => {
		const o = order.value
		if (!o) return []
		const items = []
		if (partner.value) {
			items.push({
				key: "partner",
				icon: "lucide-user-check",
				title: `Matched with ${partner.value.partner_name}`,
				when: ago(o.partner_assigned_on),
				cardIcon: "lucide-message-square",
				label: `Message ${partnerFirstName.value} to agree a kickoff date`,
				badge: null,
				action: "message",
			})
		}
		if (o.paid_on) {
			items.push({
				key: "paid",
				icon: "lucide-credit-card",
				title: "Payment received",
				when: ago(o.paid_on),
				cardIcon: "",
				label: `${money(o.amount)} paid, including ${o.gst_rate}% GST`,
				badge: PAYMENT_BADGES[o.payment_status] || null,
				action: "",
			})
		}
		items.push({
			key: "created",
			icon: "lucide-folder-plus",
			title: "Order placed",
			when: ago(o.created_on),
			cardIcon: "",
			label: `ERPNext implementation for ${o.company_name || o.order}`,
			badge: ORDER_STATUS_BADGES[o.status] || null,
			action: "",
		})
		return items
	})

	function runAction(action) {
		if (action === "message") messagePartner()
	}

	// The right-hand panel, one entry per pack bought. The scope comes from the catalog
	// (get_order carries prices only); every expandable row gets a key unique across packs,
	// so opening one never opens its twin in another pack.
	const packDetails = computed(() =>
		packs.value.map((p) => {
			const modules = (catalog.data?.packs || []).find((c) => c.pack_key === p.starter_pack)?.modules || []
			const notInScope = modules.flatMap((m) =>
				m.sections
					.filter((s) => s.label === "Not included")
					.flatMap((s) => s.content.split(",").map((item) => item.trim()).filter(Boolean)),
			)
			const key = p.starter_pack
			return {
				...p,
				pitch: PACK_PITCHES[key] || "",
				facts: [
					{ key: "price", icon: "lucide-circle-dollar-sign", text: money(p.price) },
					{ key: "effort", icon: "lucide-hourglass", text: `${p.total_hours} hrs of effort` },
					{ key: "delivery", icon: "lucide-calendar", text: `${p.delivery_days} days to deliver` },
				],
				modules: modules.map((m) => ({
					key: `${key}:module:${m.module_name}`,
					module_name: m.module_name,
					icon: MODULE_ICONS[m.module_name] || "lucide-box",
					rows: m.sections
						.filter((s) => s.label !== "Not included")
						.map((s) => ({ key: `${key}:row:${m.module_name}:${s.label}`, label: s.label, content: s.content })),
				})),
				notInScopeKey: `${key}:not-in-scope`,
				notInScopeLabel: `Not in scope (${notInScope.length})`,
				notInScope,
				terms: [
					{ key: `${key}:terms:commercial`, label: "Commercial terms", lines: commercial.value },
					{ key: `${key}:terms:needs`, label: "What we need from you", lines: OUR_NEEDS },
				],
			}
		}),
	)

	const gstRate = computed(() => order.value?.gst_rate ?? catalog.data?.gst_rate ?? 18)
	const commercial = computed(() => commercialTerms(gstRate.value, money))

	function isOpen(key) {
		return Boolean(openKeys.value?.[key])
	}
	function toggle(key) {
		openKeys.value = { ...(openKeys.value || {}), [key]: !isOpen(key) }
	}

	// Messaging has no way to deep-link into one partner's thread yet, so this can only
	// open the inbox in general — not jump straight to them the way the button implies.
	function messagePartner() {
		router.push("/messaging")
	}

	function visitPartnerProfile() {
		if (partner.value) router.push(`/partner-profile-redesign/${partner.value.name}`)
	}

	function backToStarterPacks() {
		router.push("/starter-packs-redesign")
	}

	return {
		heading,
		subheading,
		partner,
		partnerFirstName,
		partnerStats,
		partnerExpertise,
		packDetails,
		activity,
		runAction,
		isOpen,
		toggle,
		messagePartner,
		visitPartnerProfile,
		backToStarterPacks,
		load,
	}
}
