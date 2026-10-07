// Starter Pack checkout, in two states on one page:
// - paying (?packs=a,b): the order summary priced from the catalog, the buyer's details,
//   and "Pay", which places the order and sends them to Razorpay's hosted payment page;
// - back from Razorpay (?reference_id=<Gateway Payment Request>): the order as the server
//   sees it, re-read from the gateway — never the redirect's own say-so.
// Card and UPI details are only ever entered on Razorpay's page, not here.
//
// Paying needs an account: someone signed out is sent to sign in (or up) first and comes back
// here. Their name, email and company come from the account, can be corrected here, and go onto
// the order and its payment request; the order itself takes their user and Customer.

import { computed, watch } from "vue"
import { orderKey, rememberOrderKey } from "@app/utils/checkoutSession"

export default function setup(context) {
	const {
		route,
		router,
		call,
		toast,
		myContext,
		catalog,
		checkoutName,
		checkoutEmail,
		checkoutCompany,
		checkoutPhone,
		termsAccepted,
		paying,
		orderData,
		loadError,
	} = context

	const referenceId = String(route.query.reference_id || "")
	const packKeys = String(route.query.packs || "").split(",").filter(Boolean)

	// Signed out: sign in first, and come back here. Signed in: start from the account.
	const isGuest = computed(() => !myContext.data || myContext.data.user === "Guest")
	watch(
		() => myContext.data,
		(data) => {
			if (!data) return
			if (data.user === "Guest") {
				if (!referenceId && packKeys.length) {
					router.replace({ path: "/login-signup-redesign", query: { next: route.fullPath } })
				}
				return
			}
			checkoutName.value = checkoutName.value || data.full_name || ""
			checkoutEmail.value = checkoutEmail.value || data.user
			checkoutCompany.value = checkoutCompany.value || data.customer?.customer_name || ""
		},
		{ immediate: true },
	)

	function money(amount) {
		return new Intl.NumberFormat("en-IN", {
			style: "currency",
			currency: catalog.data?.currency || "INR",
			maximumFractionDigits: 0,
		}).format(amount || 0)
	}

	// Paying: priced from the catalog for display only; the server prices the order again.
	// Back from Razorpay: exactly what was sold, from the order.
	const lines = computed(() => {
		if (referenceId) {
			return (orderData.value?.packs || []).map((p) => ({ name: p.pack_name, hours: p.total_hours, price: p.price }))
		}
		return (catalog.data?.packs || [])
			.filter((p) => packKeys.includes(p.pack_key))
			.map((p) => ({ name: p.pack_name, hours: p.total_hours, price: p.price }))
	})
	const gstRate = computed(() => (referenceId ? orderData.value?.gst_rate : catalog.data?.gst_rate) ?? 18)
	const subtotal = computed(() => lines.value.reduce((sum, l) => sum + l.price, 0))
	const gst = computed(() => subtotal.value * (gstRate.value / 100))
	const totalLabel = computed(() => money(subtotal.value + gst.value))

	// Which right-hand panel to show.
	const view = computed(() => {
		if (!referenceId) return packKeys.length ? "pay" : "empty"
		if (loadError.value) return "error"
		const status = orderData.value?.payment_status
		if (!status) return "loading"
		return (
			{ Paid: "paid", Unpaid: "pending", Failed: "failed", Refunded: "refunded", "Partially Refunded": "refunded" }[
				status
			] || "error"
		)
	})

	function loadOrder() {
		loadError.value = false
		orderData.value = {}
		call("connect.api.starter_pack.get_order", { payment_request: referenceId, key: orderKey(referenceId) })
			.then((data) => {
				orderData.value = data
				// A paid order goes on to its setup steps — this page's job is just to gate on status.
				if (data.payment_status === "Paid") {
					router.replace({ path: "/starter-pack-implementation", query: { order: data.order } })
				}
			})
			.catch(() => {
				loadError.value = true
			})
	}
	if (referenceId) loadOrder()

	function goToPayment(promise) {
		paying.value = true
		promise
			.then((res) => {
				rememberOrderKey(res)
				window.location.href = res.payment_url
			})
			.catch((err) => {
				paying.value = false
				toast.error((err && err.messages && err.messages.join(", ")) || "Couldn't start the payment")
			})
	}

	function payNow() {
		if (isGuest.value) {
			router.push({ path: "/login-signup-redesign", query: { next: route.fullPath } })
			return
		}
		if (!checkoutName.value || !checkoutEmail.value || !checkoutCompany.value || !termsAccepted.value) return
		goToPayment(
			call("connect.api.starter_pack.checkout", {
				packs: JSON.stringify(packKeys),
				buyer_name: checkoutName.value,
				buyer_email: checkoutEmail.value,
				company_name: checkoutCompany.value,
				phone: checkoutPhone.value,
				terms_accepted: 1,
			}),
		)
	}

	function retryPayment() {
		const order = orderData.value.order
		goToPayment(call("connect.api.starter_pack.pay", { order, key: orderKey(order) }))
	}

	function goBack() {
		if (window.history.length > 1) router.back()
		else router.push("/starter-pack-recommendation")
	}

	function backToPacks() {
		router.push("/starter-pack-recommendation")
	}

	return {
		isGuest,
		money,
		lines,
		gstRate,
		subtotalLabel: computed(() => money(subtotal.value)),
		gstLabel: computed(() => money(gst.value)),
		totalLabel,
		view,
		loadOrder,
		payNow,
		retryPayment,
		goBack,
		backToPacks,
	}
}
