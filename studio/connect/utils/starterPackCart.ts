// The Starter Pack cart, shared by the landing, details and cart pages: which packs the
// visitor has picked, kept in this browser until checkout. Core and Core + Manufacturing
// are alternatives, so picking one replaces the other. Also the terms every pack is sold on.

import { computed, ref } from "vue"

const STORAGE_KEY = "connect_starter_pack_cart"
const GST_RATE = 18

export const CART_PACKS = {
	core: {
		title: "Core",
		modules: "Accounting, Selling, Buying and Stock",
		hours: "5 hrs within 5 sessions",
		price: 10000,
		logo: "/assets/connect/images/app_icons/erpnext.png",
		// the catalog packs checkout charges for
		catalogPacks: ["accounts_sales_purchase_stock"],
	},
	"core-manufacturing": {
		title: "Core + Manufacturing",
		modules: "Everything in Core, plus Manufacturing",
		hours: "10 hrs within 5 sessions",
		price: 20000,
		logo: "/assets/connect/images/app_icons/erpnext.png",
		catalogPacks: ["accounts_sales_purchase_stock", "manufacturing"],
	},
	"hr-payroll": {
		title: "HR and Payroll",
		modules: "HRMS and Payroll",
		hours: "10 hrs within 5 sessions",
		price: 20000,
		logo: "/assets/connect/images/app_icons/frappe-hr.png",
		catalogPacks: ["hr", "payroll"],
	},
}
const BASE_PACKS = ["core", "core-manufacturing"]

export const STARTER_PACK_TERMS = [
	{ title: "Eligibility", items: [{ text: "For Frappe Cloud customers on plans of ₹820/month and above" }] },
	{
		title: "Sessions",
		items: [
			{ text: "Your pack's hours are guided onboarding sessions, scheduled in advance" },
			{ text: "Missed sessions can't be rescheduled or carried forward, and count as used" },
		],
	},
	{
		title: "Scope",
		items: [
			{ text: "Covers the modules your pack lists, and their basic, standard features" },
			{ text: "Other modules and advanced features are outside the scope" },
			{
				text: "Topics outside the scope can be explored through ERPNext documentation, videos and community resources, or with an ERPNext partner",
			},
			{ text: "Frappe decides whether a question, request or use case is in scope" },
		],
	},
	{
		title: "Payment",
		items: [
			{ text: "Payment to Frappe in full, in advance" },
			{ text: "18% GST charged on top" },
			{ text: "Fees are non-refundable and non-transferable" },
		],
	},
	{
		title: "What we need from you",
		items: [{ text: "Nominate a project champion" }, { text: "Attend each session at its scheduled time" }],
	},
]

function readCart() {
	try {
		const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]")
		return Array.isArray(saved) ? saved.filter((key) => key in CART_PACKS) : []
	} catch {
		return []
	}
}

// one cart for every page in this tab; the browser keeps it across reloads
const cartKeys = ref(readCart())

function saveCart(keys) {
	cartKeys.value = keys
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(keys))
	} catch {
		// private windows can refuse storage; the cart still lasts for this visit
	}
}

export function money(amount) {
	return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(amount)
}

export function starterPackCart(context) {
	const { router, myContext } = context

	const items = computed(() => cartKeys.value.map((key) => ({ key, ...CART_PACKS[key], priceLabel: money(CART_PACKS[key].price) })))
	const cartCount = computed(() => cartKeys.value.length)
	const subtotal = computed(() => items.value.reduce((sum, item) => sum + item.price, 0))
	const gst = computed(() => Math.round((subtotal.value * GST_RATE) / 100))

	function inCart(key) {
		return cartKeys.value.includes(key)
	}

	function addToCart(key) {
		if (!(key in CART_PACKS)) return
		const others = BASE_PACKS.includes(key) ? BASE_PACKS : [key]
		saveCart([...cartKeys.value.filter((k) => !others.includes(k)), key])
	}

	function removeFromCart(key) {
		saveCart(cartKeys.value.filter((k) => k !== key))
	}

	// "In cart" is the same button, so a second click takes the pack out again
	function toggleCart(key) {
		inCart(key) ? removeFromCart(key) : addToCart(key)
	}

	function viewCart() {
		router.push("/starter-pack-cart")
	}

	const isGuest = computed(() => !myContext?.data || myContext.data.user === "Guest")

	// Checkout charges for catalog packs; someone signed out signs up first and carries on there.
	function checkout() {
		const packs = [...new Set(items.value.flatMap((item) => item.catalogPacks))]
		if (!packs.length) return
		const target = router.resolve({ path: "/starter-pack-checkout", query: { packs: packs.join(",") } }).fullPath
		if (isGuest.value) router.push({ path: "/login-signup-redesign", query: { next: target } })
		else router.push(target)
	}

	return {
		cartItems: items,
		cartCount,
		cartSubtotal: computed(() => money(subtotal.value)),
		cartGst: computed(() => money(gst.value)),
		cartTotal: computed(() => money(subtotal.value + gst.value)),
		gstRate: GST_RATE,
		inCart,
		addToCart,
		removeFromCart,
		toggleCart,
		viewCart,
		checkout,
		isGuest,
	}
}
