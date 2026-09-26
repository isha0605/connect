// The Starter Pack recommendation: which packs the questionnaire's answers point to
// and why, the packs themselves (tick to add, "View details" for scope), and a basket
// that checks out through connect.api.starter_pack. The answers arrive in the URL;
// the rules that read them live in @app/utils/recommendation.

import { computed } from "vue"
import { answersFromQuery, answersToQuery, directoryQuery, recommend } from "@app/utils/recommendation"

const HOW_IT_WORKS = [
	{ title: "Pay in full", body: "To Frappe, up front" },
	{ title: "Frappe assigns a partner", body: "By industry and region" },
	{ title: "Coordinate with partner", body: "Share data and processes" },
]

const INCLUDED = [
	"ERPNext installed on Frappe Cloud",
	"Standard user roles",
	"One SMTP setup",
	"Standard module-wise dashboards",
	"Core system configuration",
	"One data import session",
	"One naming series session",
	"Opening balances",
]

// The pack exclusions that aren't already a reason to go custom (listed below them).
const NOT_INCLUDED = [
	{ label: "Custom print formats", hint: "" },
	{ label: "UAT training", hint: "" },
	{ label: "Custom workflows", hint: "" },
	{ label: "Complex notification automation", hint: "" },
	{ label: "Post go-live support beyond Day 1", hint: "Covered by an AMC" },
]

const CUSTOM_IF = [
	{ label: "More than 50 people will use it", hint: "" },
	{ label: "You need your data cleaned and migrated", hint: "You provide clean Excel or CSV data" },
	{ label: "You need custom scripting", hint: "" },
	{ label: "You need API integrations", hint: "Biometric devices, banks and payment gateways" },
]

const OUR_NEEDS = [
	"Keep strictly to the scope",
	"Nominate a project champion",
	"Have your data ready",
	"Approve internally without delay",
	"Make your users available for training",
]

const EXTRA_HOUR_RATE = 2000

export default function setup(context) {
	const {
		route,
		router,
		call,
		toast,
		catalog,
		myContext,
		myCustomer,
		partnerCountries,
		pickedPacks,
		scopePackKey,
		showScope,
		showCheckout,
		checkoutCompany,
		checkoutPhone,
		termsAccepted,
		checkingOut,
		feedbackSent,
	} = context

	const answers = answersFromQuery(route.query)
	const recommendation = answers ? recommend(answers) : null
	const recommended = recommendation?.verdict === "packs" ? recommendation.packs : []

	// Start with the recommended packs ticked; the customer can change that freely.
	pickedPacks.value = recommended.map((p) => p.key)

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

	const headline = computed(() => {
		if (!recommended.length) return "Starter Packs"
		return recommended.length > 1 ? "We recommend these Starter Packs" : "We recommend a Starter Pack"
	})

	// A "Recommended" badge only means something when it singles packs out.
	function isRecommended(key) {
		return recommended.length < packs.value.length && recommended.some((p) => p.key === key)
	}

	function isPicked(key) {
		return pickedPacks.value.includes(key)
	}

	function togglePack(key) {
		pickedPacks.value = isPicked(key)
			? pickedPacks.value.filter((k) => k !== key)
			: [...pickedPacks.value, key]
	}

	const whyReasons = recommendation?.verdict === "packs" ? recommendation.reasons : []
	const packReasons = computed(() =>
		recommended.map((r) => ({
			key: r.key,
			name: packs.value.find((p) => p.pack_key === r.key)?.pack_name || "",
			reason: `${r.reason}.`,
		})),
	)
	const packReasonsTitle = recommended.length > 1 ? "Why we recommend these packs" : "Why we recommend this pack"

	const scopePack = computed(() => packs.value.find((p) => p.pack_key === scopePackKey.value) || null)

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

	const commercialTerms = computed(() => [
		"Payment to Frappe in full, in advance",
		`${gstRate.value}% GST charged on top`,
		`Extra hours beyond the pack: ${money(EXTRA_HOUR_RATE)} per hour, plus ${gstRate.value}% GST`,
		"Scope is limited to what the pack lists. Anything else is a change request, and more hours",
		"Validity runs from the project start date",
		"For businesses running fewer than 50 users",
		"Your Frappe Cloud subscription is billed separately",
		`Product warranty applies on Frappe Cloud plans above ${money(4100)} + GST a month`,
	])

	function startCheckout() {
		if (isGuest.value) {
			const back = window.location.pathname + window.location.search
			window.location.href = `/login?redirect-to=${encodeURIComponent(back)}`
			return
		}
		if (!checkoutCompany.value) checkoutCompany.value = myCustomer.data?.customer_name || ""
		showCheckout.value = true
	}

	function payNow() {
		if (!checkoutCompany.value || !termsAccepted.value) return
		checkingOut.value = true
		call("connect.api.starter_pack.checkout", {
			packs: JSON.stringify(pickedPacks.value),
			company_name: checkoutCompany.value,
			phone: checkoutPhone.value,
			terms_accepted: 1,
		})
			.then((res) => {
				window.location.href = res.payment_url
			})
			.catch((err) => {
				checkingOut.value = false
				toast.error((err && err.messages && err.messages.join(", ")) || "Couldn't start the payment")
			})
	}

	function changeAnswers() {
		router.push({ path: "/find-partners-redesign", query: answersToQuery(answers || {}) })
	}

	function getQuotes() {
		router.push({
			path: "/partner-directory-redesign",
			query: directoryQuery(answers || {}, partnerCountries.data || []),
		})
	}

	return {
		howItWorks: HOW_IT_WORKS,
		included: INCLUDED,
		notIncluded: NOT_INCLUDED,
		customIf: CUSTOM_IF,
		ourNeeds: OUR_NEEDS,
		hasAnswers: !!answers,
		headline,
		packs,
		money,
		isRecommended,
		isPicked,
		togglePack,
		whyReasons,
		packReasons,
		packReasonsTitle,
		scopePack,
		openScope,
		totalLabel,
		totalBreakdown,
		isGuest,
		commercialTerms,
		startCheckout,
		payNow,
		changeAnswers,
		getQuotes,
	}
}
