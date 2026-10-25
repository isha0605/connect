import { computed, onScopeDispose, ref, watch } from "vue"
import { toast, call } from "frappe-ui"
import { orderKey } from "@app/utils/checkoutSession"
import { EMPLOYEE_OPTIONS, INDUSTRY_OPTIONS, MODULE_ICONS, SYSTEM_OPTIONS } from "@app/utils/recommendation"
import { CART_PACKS, clearCart } from "@app/utils/starterPackCart"
import { startTracking } from "@app/utils/tracking"

// "Set up your Starter Pack": where checkout sends the buyer once their order is paid
// (/starter-pack-implementation?order=SPO-…). The right panel and "Pay upfront" come from
// the order; the other steps are still copy only, with no backend behind them yet.

const PAYMENT_BADGES = {
	Paid: { label: "Paid", theme: "gray" },
	"Partially Refunded": { label: "Partially refunded", theme: "orange" },
	Refunded: { label: "Refunded", theme: "gray" },
}

export default function setup(context) {
	startTracking(context)
	const { route, router, companyOpen, companyEmployees, companyIndustry, companySystem, companyFocus } = context

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

	// ---- "Tell us about your company" ----
	// Saved to the buyer's company Requirement, so it comes with the order (company_details).
	const savedCompany = computed(() => order.value?.company_details || null)
	const companySummary = computed(() => {
		const saved = savedCompany.value
		if (!saved) return ""
		const employees = EMPLOYEE_OPTIONS.find((o) => o.value === saved.employees)?.label || saved.employees
		return `${employees} employees, ${saved.industry}.`
	})

	function openCompany() {
		const saved = savedCompany.value || {}
		companyEmployees.value = saved.employees || ""
		companyIndustry.value = saved.industry || ""
		companySystem.value = saved.system || ""
		companyFocus.value = saved.focus || ""
		companyOpen.value = true
	}

	let savingCompany = false
	function saveCompany() {
		if (!order.value || !companyEmployees.value || !companyIndustry.value || !companySystem.value) return
		if (savingCompany) return
		savingCompany = true
		call("connect.api.starter_pack.save_company_details", {
			order: order.value.order,
			key: orderKey(order.value.order),
			employees: companyEmployees.value,
			industry: companyIndustry.value,
			system: companySystem.value,
			focus: String(companyFocus.value || "").trim(),
		})
			.then((details) => {
				order.value = { ...order.value, company_details: details }
				companyOpen.value = false
			})
			.catch((err) => {
				toast.error((err && err.messages && err.messages.join(", ")) || "Couldn't save your company's details")
			})
			.finally(() => {
				savingCompany = false
			})
	}

	// ---- Kickoff call ----
	// The consultant shares it from Messaging; the step is done once the call's time has passed.
	const now = ref(Date.now())
	const clock = setInterval(() => {
		now.value = Date.now()
	}, 60 * 1000)
	onScopeDispose(() => clearInterval(clock))

	const kickoffAt = computed(() => (order.value?.kickoff_at ? new Date(order.value.kickoff_at) : null))
	const meetingLink = computed(() => order.value?.meeting_link || "")
	const kickoffHappened = computed(() => !!kickoffAt.value && kickoffAt.value.getTime() <= now.value)
	const kickoffDescription = computed(() => {
		if (!kickoffAt.value) {
			return `Agree a kickoff date with ${partnerName.value}. They will go through your requirements with you and plan the implementation.`
		}
		const when = kickoffAt.value.toLocaleString("en-US", {
			weekday: "short",
			month: "short",
			day: "numeric",
			hour: "numeric",
			minute: "2-digit",
		})
		return kickoffHappened.value
			? `Your kickoff call with ${partnerName.value} was on ${when}.`
			: `Your kickoff call with ${partnerName.value} is on ${when}.`
	})

	function joinCall() {
		if (meetingLink.value) window.open(meetingLink.value, "_blank", "noopener")
	}

	// ---- Steps accordion ----
	// "Pay upfront" is done once the order is paid; "Tell us about your company" once answered.
	function stepStatus(key) {
		if (key === "pay-upfront") return order.value ? "completed" : "pending"
		if (key === "company") return savedCompany.value ? "completed" : "pending"
		if (key === "kickoff") return kickoffHappened.value ? "completed" : "pending"
		return "pending"
	}

	// Opens on the first step still to do; after saving, the company step stays open on its summary.
	const openStep = ref("company")
	watch(
		order,
		() => {
			if (savedCompany.value) openStep.value = "kickoff"
		},
		{ once: true },
	)

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
	function viewRequirements() {
		toast.info("Requirements are coming soon.")
	}

	function openFeedback() {
		toast.info("Feedback form is coming soon.")
	}

	// ---- "Welcome to your project!" ----
	// Checkout redirects here with ?booked=1 the moment the gateway confirms payment.
	// The flag is dropped from the URL on arrival so a reload doesn't greet them twice.
	const bookedOpen = ref(Boolean(route.query.booked))
	if (bookedOpen.value) {
		// the order is paid, so what was in the cart has been bought
		clearCart()
		const query = { ...route.query }
		delete query.booked
		// Setup runs while the navigation here is still resolving, and replacing the URL then
		// cancels it and loads the page afresh without ?booked. So tidy the URL once it lands.
		const stop = router.afterEach(() => {
			stop()
			router.replace({ path: route.path, query })
		})
	}

	// What was bought, as the cart names it, with hours as sold. Orders from before the cart's
	// packs were the catalog's hold the older packs (Manufacturing, HR…); those show under
	// their own names.
	const OLD_HR_PACKS = ["hr", "payroll"]
	const bookedPacks = computed(() =>
		(order.value?.packs || []).map((row) => {
			const pack = CART_PACKS[row.starter_pack]
			if (pack) return { key: row.starter_pack, ...pack, hours: `${row.total_hours} hrs within 5 sessions` }
			return {
				key: row.starter_pack,
				title: row.pack_name,
				hours: row.total_hours ? `${row.total_hours} hrs` : "",
				logo: OLD_HR_PACKS.includes(row.starter_pack) ? CART_PACKS["hr-payroll"].logo : CART_PACKS.core.logo,
			}
		}),
	)

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
		employeeOptions: EMPLOYEE_OPTIONS,
		industryOptions: INDUSTRY_OPTIONS,
		systemOptions: SYSTEM_OPTIONS,
		kickoffDescription,
		meetingLink,
		joinCall,
		companySummary,
		openCompany,
		saveCompany,
		viewRequirements,
		openFeedback,
		accountMenuOptions,
		bookedOpen,
		bookedPacks,
		dismissBooked,
		downloadInvoice,
	}
}
