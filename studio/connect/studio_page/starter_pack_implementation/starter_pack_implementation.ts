import { computed, ref } from "vue"
import { toast, call } from "frappe-ui"
import { orderKey } from "@app/utils/checkoutSession"

// "Set up your Starter Pack": where checkout sends the buyer once their order is paid
// (/starter-pack-implementation?order=SPO-…). The right panel and "Pay upfront" come from
// the order; the other steps are still copy only, with no backend behind them yet.

const PAYMENT_BADGES = {
	Paid: { label: "Paid", theme: "gray" },
	"Partially Refunded": { label: "Partially refunded", theme: "orange" },
	Refunded: { label: "Refunded", theme: "gray" },
}

export default function setup(context) {
	const { route, router } = context

	// ---- The order ----
	const orderName = String(route.query.order || "")
	const order = ref(null)
	const loadError = ref(false)

	function fetchOrder() {
		// POST: an unpaid order is re-read from the gateway here (see get_order).
		return call("connect.api.starter_pack.get_order", { order: orderName, key: orderKey(orderName) })
	}

	function load() {
		if (!orderName) {
			loadError.value = true
			return
		}
		fetchOrder()
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
		return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(
			amount || 0,
		)
	}

	function formatDate(value) {
		if (!value) return ""
		return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
	}

	const projectTitle = computed(() => order.value?.project_title || "Starter Pack implementation")
	const breadcrumbItems = computed(() => [{ label: "Projects" }, { label: projectTitle.value }])
	const partner = computed(() => order.value?.partner || null)
	// With Frappe, the buyer works with one of its consultants: "Priya Sharma · Frappe".
	const consultant = computed(() => order.value?.consultant || null)
	const partnerName = computed(() => consultant.value?.label || partner.value?.partner_name || "Frappe")
	const partnerLogo = computed(() => consultant.value?.photo || partner.value?.logo || "")
	const scopeOfWork = computed(() => (order.value?.packs || []).map((p) => p.pack_name).join(", "))
	const cost = computed(() => money(order.value?.amount))
	const paymentBadge = computed(() => PAYMENT_BADGES[order.value?.payment_status] || PAYMENT_BADGES.Paid)
	const timeline = computed(() => (order.value?.timeline_days ? `${order.value.timeline_days} days` : ""))
	const createdOn = computed(() => formatDate(order.value?.created_on))
	const paidLine = computed(() =>
		order.value ? `You paid ${cost.value} on ${formatDate(order.value.paid_on)}.` : "",
	)

	// The buyer's opening message to the partner is posted by a background job just after
	// payment, so if the thread isn't on the order yet, look once more before opening Messaging.
	function openThread() {
		const go = (thread) => router.push({ path: "/messaging", query: thread ? { thread } : {} })
		if (order.value?.implementation_thread) return go(order.value.implementation_thread)
		fetchOrder()
			.then((data) => go(data.implementation_thread))
			.catch(() => go(null))
	}

	// ---- Steps accordion ----
	// Only "Pay upfront" can be done so far; it's done once the order is paid.
	function stepStatus(key) {
		return key === "pay-upfront" && order.value ? "completed" : "pending"
	}

	const openStep = ref("terms")

	function isStepOpen(key) {
		return openStep.value === key
	}

	// One step open at a time, like the Figma reference.
	function toggleStep(key) {
		openStep.value = openStep.value === key ? "" : key
	}

	// ---- Hosted site URL (last step's input) ----
	const hostedSiteUrl = ref("")

	function submitHostedSiteUrl() {
		const url = String(hostedSiteUrl.value || "").trim()
		if (!/^https?:\/\/.+/.test(url)) {
			toast.error("Enter a valid URL, starting with http:// or https://")
			return
		}
		toast.success("Thanks! We'll take it from here.")
	}

	// ---- Placeholder actions (no backend behind them yet) ----
	function viewTermsDetails() {
		toast.info("Terms & Conditions details are coming soon.")
	}

	function viewRequirements() {
		toast.info("Requirements are coming soon.")
	}

	function openFeedback() {
		toast.info("Feedback form is coming soon.")
	}


	return {
		order,
		loadError,
		projectTitle,
		breadcrumbItems,
		partnerName,
		partnerLogo,
		scopeOfWork,
		cost,
		paymentBadge,
		timeline,
		createdOn,
		paidLine,
		openThread,
		stepStatus,
		openStep,
		isStepOpen,
		toggleStep,
		hostedSiteUrl,
		submitHostedSiteUrl,
		viewTermsDetails,
		viewRequirements,
		openFeedback,
	}
}
