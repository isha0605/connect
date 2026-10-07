// The Starter Pack list and basket, shared by the Starter Packs page and the recommendation
// page: tick packs, see what they come to, open a pack's scope, and check out.
//
// Expects the page to have the catalog resource and the pickedPacks, scopePackKey and
// showScope variables.

import { computed } from "vue"
import { MODULE_ICONS, commercialTerms } from "@app/utils/recommendation"

export function packBasket(context) {
	const { router, catalog, myContext, pickedPacks, scopePackKey, showScope } = context

	const packs = computed(() => catalog.data?.packs || [])
	const gstRate = computed(() => catalog.data?.gst_rate ?? 18)
	const picked = computed(() => packs.value.filter((p) => pickedPacks.value.includes(p.pack_key)))

	function money(amount) {
		return new Intl.NumberFormat("en-IN", {
			style: "currency",
			currency: catalog.data?.currency || "INR",
			maximumFractionDigits: 0,
		}).format(amount)
	}

	function isPicked(key) {
		return pickedPacks.value.includes(key)
	}

	function togglePack(key) {
		pickedPacks.value = isPicked(key)
			? pickedPacks.value.filter((k) => k !== key)
			: [...pickedPacks.value, key]
	}

	const scopePack = computed(() => packs.value.find((p) => p.pack_key === scopePackKey.value) || null)

	function moduleIcon(name) {
		return MODULE_ICONS[name] || "lucide-box"
	}

	function openScope(key) {
		scopePackKey.value = key
		showScope.value = true
	}

	const subtotal = computed(() => picked.value.reduce((sum, p) => sum + p.price, 0))
	const totalLabel = computed(() => money(subtotal.value * (1 + gstRate.value / 100)))
	const totalBreakdown = computed(() => {
		const hours = picked.value.reduce((sum, p) => sum + p.total_hours, 0)
		return `${money(subtotal.value)} plus ${gstRate.value}% GST · ${hours} hours`
	})
	const isGuest = computed(() => !myContext.data || myContext.data.user === "Guest")

	const commercial = computed(() => commercialTerms(gstRate.value, money))

	// Someone signed out signs up (or in) first, which carries on to checkout afterwards.
	function startCheckout() {
		const query = { packs: pickedPacks.value.join(",") }
		if (isGuest.value) {
			const next = router.resolve({ path: "/starter-pack-checkout", query }).fullPath
			router.push({ path: "/login-signup-redesign", query: { next } })
		} else {
			router.push({ path: "/starter-pack-checkout", query })
		}
	}

	return {
		packs,
		money,
		isPicked,
		togglePack,
		scopePack,
		openScope,
		moduleIcon,
		totalLabel,
		totalBreakdown,
		isGuest,
		commercialTerms: commercial,
		startCheckout,
	}
}
