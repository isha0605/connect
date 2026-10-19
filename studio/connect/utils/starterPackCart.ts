// The Starter Pack cart, shared by the landing, details and cart pages: which packs the
// visitor has picked, kept in this browser until checkout. Core and Core + Manufacturing
// are alternatives, so picking one replaces the other. Also the terms every pack is sold on.
//
// Each cart pack is a Starter Pack of the same key, and checkout charges the catalog's prices,
// so once the catalog is in, the cart shows its prices, hours and GST rate too. The figures
// below are only what shows until then.

import { computed, ref } from "vue"
import { rememberOrderKey } from "@app/utils/checkoutSession"

const STORAGE_KEY = "connect_starter_pack_cart"
const DEFAULT_GST_RATE = 18

export const CART_PACKS = {
	core: {
		title: "Core",
		modules: "Accounting, Selling, Buying and Stock",
		hours: "5 hrs within 5 sessions",
		price: 10000,
		logo: "/assets/connect/images/app_icons/erpnext.png",
	},
	"core-manufacturing": {
		title: "Core + Manufacturing",
		modules: "Everything in Core, plus Manufacturing",
		hours: "10 hrs within 5 sessions",
		price: 20000,
		logo: "/assets/connect/images/app_icons/erpnext.png",
	},
	"hr-payroll": {
		title: "HR and Payroll",
		modules: "HRMS and Payroll",
		hours: "10 hrs within 5 sessions",
		price: 20000,
		logo: "/assets/connect/images/app_icons/frappe-hr.png",
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

// one cart and one catalog for every page in this tab; the browser keeps the cart across reloads
const cartKeys = ref(readCart())
const catalog = ref(null)
let catalogRequested = false
const checkingOut = ref(false)

function saveCart(keys) {
	cartKeys.value = keys
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(keys))
	} catch {
		// private windows can refuse storage; the cart still lasts for this visit
	}
}

// After a paid order: what was in the cart has been bought.
export function clearCart() {
	saveCart([])
}

export function money(amount) {
	return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(amount)
}

// A cart pack priced as checkout will charge it.
function priced(key) {
	const pack = (catalog.value?.packs || []).find((p) => p.pack_key === key)
	if (!pack) return { price: CART_PACKS[key].price, hours: CART_PACKS[key].hours }
	return { price: pack.price, hours: `${pack.total_hours} hrs within 5 sessions` }
}

export function starterPackCart(context) {
	const { router, myContext, call, toast } = context

	if (!catalogRequested && call) {
		catalogRequested = true
		call("connect.api.starter_pack.get_catalog")
			.then((data) => {
				catalog.value = data
			})
			.catch(() => {
				// the cart still shows its own figures; checkout prices the order regardless
				catalogRequested = false
			})
	}

	const gstRate = computed(() => catalog.value?.gst_rate ?? DEFAULT_GST_RATE)
	const items = computed(() =>
		cartKeys.value.map((key) => {
			const { price, hours } = priced(key)
			return { key, ...CART_PACKS[key], price, hours, priceLabel: money(price) }
		}),
	)
	const cartCount = computed(() => cartKeys.value.length)
	const subtotal = computed(() => items.value.reduce((sum, item) => sum + item.price, 0))
	const gst = computed(() => Math.round((subtotal.value * gstRate.value) / 100))

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

	// A pack button's text. With the other base pack in the cart, picking this one swaps them:
	// Core + Manufacturing is an upgrade from Core, and Core a switch back.
	function packButtonLabel(key, label) {
		if (inCart(key)) return "In cart"
		if (key === "core-manufacturing" && inCart("core")) return "Upgrade to this"
		if (key === "core" && inCart("core-manufacturing")) return "Switch to this"
		return label
	}

	function viewCart() {
		router.push("/starter-pack-cart")
	}

	const isGuest = computed(() => !myContext?.data || myContext.data.user === "Guest")

	// Places the order for the cart's packs and sends the buyer to Razorpay. Razorpay
	// sends them back to the checkout page, which checks the payment with the gateway and opens
	// the project; the cart empties there, once the order is paid. Someone signed out signs up
	// first and comes back to the cart. An order needs a company and an email: an account without
	// either (Administrator's id is no email) goes to the checkout page's form, which asks.
	async function checkout() {
		const packs = [...cartKeys.value]
		if (!packs.length || checkingOut.value) return
		if (isGuest.value) {
			router.push({ path: "/login-signup-redesign", query: { next: "/starter-pack-cart" } })
			return
		}
		const account = myContext.data
		const company = account.customer?.customer_name
		if (!company || !String(account.user).includes("@")) {
			router.push({ path: "/starter-pack-checkout", query: { packs: packs.join(",") } })
			return
		}

		checkingOut.value = true
		try {
			// the account has no phone number; the buyer's last order may
			const last = await call("connect.api.starter_pack.last_checkout_details", { email: account.user }).catch(() => null)
			const res = await call("connect.api.starter_pack.checkout", {
				packs: JSON.stringify(packs),
				buyer_name: account.full_name || account.user,
				buyer_email: account.user,
				company_name: company,
				phone: last?.phone || undefined,
				terms_accepted: 1,
			})
			rememberOrderKey(res)
			window.location.href = res.payment_url
		} catch (err) {
			checkingOut.value = false
			toast.error((err && err.messages && err.messages.join(", ")) || "Couldn't start the payment")
		}
	}

	return {
		cartItems: items,
		cartCount,
		cartSubtotal: computed(() => money(subtotal.value)),
		cartGst: computed(() => money(gst.value)),
		cartTotal: computed(() => money(subtotal.value + gst.value)),
		gstRate,
		inCart,
		addToCart,
		removeFromCart,
		toggleCart,
		packButtonLabel,
		viewCart,
		checkout,
		checkingOut,
		isGuest,
	}
}
