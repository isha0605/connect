// Starter Pack checkout, in two states on one page:
// - paying (?packs=a,b): the order summary priced from the catalog, the buyer's details,
//   and "Pay", which places the order and sends them to Razorpay's hosted payment page;
// - back from Razorpay (?reference_id=<Gateway Payment Request>): the order as the server
//   sees it, re-read from the gateway — never the redirect's own say-so.
// Card and UPI details are only ever entered on Razorpay's page, not here.

import { computed, watch } from "vue"

export default function setup(context) {
	const {
		route,
		router,
		call,
		toast,
		catalog,
		myContext,
		myCustomer,
		checkoutCompany,
		checkoutPhone,
		termsAccepted,
		paying,
		orderData,
		loadError,
	} = context

	const referenceId = String(route.query.reference_id || "")
	const packKeys = String(route.query.packs || "").split(",").filter(Boolean)

	const isGuest = computed(() => !myContext.data || myContext.data.user === "Guest")
	const userEmail = computed(() => (isGuest.value ? "" : myContext.data.user))

	watch(
		() => myCustomer.data,
		(customer) => {
			if (customer && !checkoutCompany.value) checkoutCompany.value = customer.customer_name
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
		call("connect.api.starter_pack.get_order", { payment_request: referenceId })
			.then((data) => {
				orderData.value = data
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
				window.location.href = res.payment_url
			})
			.catch((err) => {
				paying.value = false
				toast.error((err && err.messages && err.messages.join(", ")) || "Couldn't start the payment")
			})
	}

	function payNow() {
		if (isGuest.value) {
			const back = window.location.pathname + window.location.search
			window.location.href = `/login?redirect-to=${encodeURIComponent(back)}`
			return
		}
		if (!checkoutCompany.value || !termsAccepted.value) return
		goToPayment(
			call("connect.api.starter_pack.checkout", {
				packs: JSON.stringify(packKeys),
				company_name: checkoutCompany.value,
				phone: checkoutPhone.value,
				terms_accepted: 1,
			}),
		)
	}

	function retryPayment() {
		goToPayment(call("connect.api.starter_pack.pay", { order: orderData.value.order }))
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
		userEmail,
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
