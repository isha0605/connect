import { computed, ref } from "vue"
import { toast, call } from "frappe-ui"
import { orderKey } from "@app/utils/checkoutSession"
import { MODULE_ICONS } from "@app/utils/recommendation"

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
	// Same test Studio's own isEditor() uses. The editor opens pages with no query string,
	// so there the page shows the newest paid order instead (the editor's Desk session
	// can read any order), rather than the "couldn't load" state.
	const inEditor = window.location.pathname.startsWith("/studio/")
	let orderName = String(route.query.order || "")
	const order = ref(null)
	const loadError = ref(false)

	function fetchOrder() {
		// POST: an unpaid order is re-read from the gateway here (see get_order).
		return call("connect.api.starter_pack.get_order", { order: orderName, key: orderKey(orderName) })
	}

	function load() {
		if (!orderName && inEditor) {
			call("frappe.client.get_list", {
				doctype: "Starter Pack Order",
				filters: { payment_status: ["in", Object.keys(PAYMENT_BADGES)] },
				fields: ["name"],
				order_by: "creation desc",
				limit_page_length: 1,
			})
				.then((rows) => {
					if (!rows?.length) {
						loadError.value = true
						return
					}
					orderName = rows[0].name
					load()
				})
				.catch(() => {
					loadError.value = true
				})
			return
		}
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
	// The consultant's photo (their initial without one), else the partner's logo; before
	// either is assigned, Frappe's own.
	const partnerLogo = computed(() => {
		if (consultant.value) return consultant.value.photo || ""
		if (partner.value) return partner.value.logo || ""
		return order.value?.frappe_logo || ""
	})
	// ---- Scope of work: what each bought pack covers, from the Starter Pack catalog ----
	const catalog = ref(null)
	call("connect.api.starter_pack.get_catalog")
		.then((data) => {
			catalog.value = data
		})
		.catch(() => {
			// Without the catalog the button still names the packs; the dialog just has no detail.
		})

	// The bought packs in the order's own order, each with its catalog scope.
	const scopePacks = computed(() =>
		(order.value?.packs || []).map((row) => {
			const pack = (catalog.value?.packs || []).find((p) => p.pack_key === row.starter_pack)
			return { pack_key: row.starter_pack, pack_name: row.pack_name, ...(pack || {}) }
		}),
	)
	const scopeOfWork = computed(() => {
		const n = scopePacks.value.length
		return n === 1 ? scopePacks.value[0].pack_name : `${n} Starter Packs`
	})
	const scopeOpen = ref(false)
	const scopeTab = ref("")
	const scopeTabs = computed(() => scopePacks.value.map((p) => ({ label: p.pack_name, value: p.pack_key })))
	const scopePack = computed(
		() => scopePacks.value.find((p) => p.pack_key === scopeTab.value) || scopePacks.value[0] || null,
	)
	const scopeSubtitle = computed(() => {
		const pack = scopePack.value
		return pack?.total_hours ? `${pack.total_hours} hours · ${pack.delivery_days} days to deliver` : ""
	})

	function viewScope() {
		scopeTab.value = scopePacks.value[0]?.pack_key || ""
		scopeOpen.value = true
	}

	function moduleIcon(name) {
		return MODULE_ICONS[name] || "lucide-box"
	}
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

	// ---- "Your Starter Packs are booked" ----
	// Checkout redirects here with ?booked=1 the moment the gateway confirms payment.
	// The flag is dropped from the URL on arrival so a reload doesn't greet them twice.
	const bookedOpen = ref(Boolean(route.query.booked))
	if (bookedOpen.value) {
		const query = { ...route.query }
		delete query.booked
		router.replace({ path: route.path, query })
	}

	function dismissBooked() {
		bookedOpen.value = false
	}

	function downloadInvoice() {
		toast.info("Invoices are coming soon.")
	}

	// ---- Rail: logo account menu ----
	// Only the published page still has its own rail; the draft has the shared sidebar, which
	// brings its own menu. Kept until that draft is published.
	function accountMenuOptions() {
		return [
			{
				icon: "lucide-log-out",
				label: "Log out",
				onClick: () => {
					call("logout").then(() => {
						window.location.href = "/login"
					})
				},
			},
		]
	}

	return {
		order,
		loadError,
		projectTitle,
		breadcrumbItems,
		partnerName,
		partnerLogo,
		scopeOfWork,
		scopePacks,
		scopeOpen,
		scopeTab,
		scopeTabs,
		scopePack,
		scopeSubtitle,
		viewScope,
		moduleIcon,
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
		accountMenuOptions,
		bookedOpen,
		dismissBooked,
		downloadInvoice,
	}
}
