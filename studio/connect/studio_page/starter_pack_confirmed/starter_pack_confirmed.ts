// Shown once a Starter Pack Order is actually paid — the checkout page redirects here.
// Everything on it comes from the order itself: no partner is invented if none has been
// assigned yet, because nothing in this codebase auto-assigns one. That still happens by
// hand in Desk after payment (see starter_pack_order.validate_partner).

import { computed } from "vue"
import { OUR_NEEDS, commercialTerms } from "@app/utils/recommendation"

export default function setup(context) {
	const { route, router, call, catalog, order, loadError, openModule, openTerms } = context

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

	const packNames = computed(() => (order.value?.packs || []).map((p) => p.pack_name))
	const packNamesLabel = computed(() => {
		const names = packNames.value
		if (names.length <= 1) return names[0] || ""
		return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`
	})
	const packWord = computed(() => (packNames.value.length > 1 ? "Starter Packs" : "Starter Pack"));

	const partner = computed(() => order.value?.partner || null)

	const heading = computed(() =>
		partner.value
			? `Your ${packNamesLabel.value} ${packWord.value} are confirmed`
			: `Your ${packNamesLabel.value} ${packWord.value} ${packNames.value.length > 1 ? "are" : "is"} confirmed`,
	)
	const subheading = computed(() =>
		partner.value
			? `We have matched you with ${partner.value.partner_name} — you can message them directly below.`
			: "We're matching you with a partner for your industry and region. You'll hear from us shortly.",
	)

	// Full scope detail per pack, joined against the catalog (get_order doesn't carry it —
	// pricing already came from the order, so only the module breakdown is looked up here).
	const packDetails = computed(() =>
		(order.value?.packs || []).map((p) => ({
			...p,
			modules: (catalog.data?.packs || []).find((c) => c.pack_key === p.starter_pack)?.modules || [],
		})),
	)

	function isModuleOpen(key) {
		return openModule.value === key
	}
	function toggleModule(key) {
		openModule.value = isModuleOpen(key) ? "" : key
	}

	const gstRate = computed(() => order.value?.gst_rate ?? catalog.data?.gst_rate ?? 18)
	const commercial = computed(() => commercialTerms(gstRate.value, money))
	function isTermsOpen(key) {
		return openTerms.value === key
	}
	function toggleTerms(key) {
		openTerms.value = isTermsOpen(key) ? "" : key
	}

	const activity = computed(() => {
		const items = [
			{
				key: "created",
				title: "Project created and confirmed",
				body: `ERPNext implementation for ${order.value?.order || ""}`,
			},
		]
		if (partner.value) {
			items.push({
				key: "partner",
				title: `${packNamesLabel.value} ${packWord.value} confirmed`,
				body: `${partner.value.partner_name} has been assigned and notified.`,
			})
		}
		return items
	})

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
		packDetails,
		money,
		isModuleOpen,
		toggleModule,
		activity,
		messagePartner,
		visitPartnerProfile,
		backToStarterPacks,
		load,
		commercialTerms: commercial,
		ourNeeds: OUR_NEEDS,
		isTermsOpen,
		toggleTerms,
	}
}
