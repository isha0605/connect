import { ref, watch } from "vue"
import { toast, call, useFileUpload } from "frappe-ui"

// Port of Press's dashboard/src/onboarding (PartnerOnboarding.vue + usePartnerOnboarding.ts and
// its dialogs) onto connect's Partner Application API: Press's Team is connect's Partner, so every
// call resolves the caller's partner server-side (_my_partner) instead of taking a team.

// Written by the login/signup page's "Become a partner?" wizard when a logged-out visitor clicks
// Proceed: they're sent through /login and land here, where the stashed details are registered.
const REGISTRATION_STASH_KEY = "connect_partner_registration"

const API = "connect.api.partner"

const STEP_ORDER = ["step-register", "step-profile", "step-certificates", "step-mrr"]

const COURSE_LABELS = {
	"frappe-developer-certification": "Framework certification",
	"app-development-with-frappe-framework": "Framework certification",
	"erpnext-distribution": "ERPNext certification",
	"erpnext-training": "ERPNext certification",
}

const EMPTY_CERTIFICATE_STATUS = {
	linked_certificates: [],
	link_requests: [],
	pending_requests: [],
	linked_count: 0,
	requirement_complete: false,
}

function rangeOptions(...values) {
	return values.map((value) => ({ label: value, value }))
}

// Press's CompanyInformationForm{First,Second,Third}Step option lists, verbatim.
const SELECT_OPTIONS = {
	revenue_currency: [
		{ label: "INR (Indian Rupees)", value: "INR" },
		{ label: "USD (US Dollar)", value: "USD" },
		{ label: "EUR (Euro)", value: "EUR" },
	],
	// These four match Partner Application's own Select field options exactly (partner_application.json)
	// -- connect's doctype diverged from Press's Team.employee_range etc. free-text ranges, and the
	// server rejects a value that isn't one of the doctype's declared options.
	employee_range: rangeOptions("1-10", "11-50", "51-200", "201-500", "500+"),
	certified_employees_range: rangeOptions("0", "1-2", "3-5", "6-10", "10+"),
	customer_count_range: rangeOptions("0-5", "6-20", "21-50", "51+"),
	erpnext_customer_count_range: rangeOptions("0-5", "6-20", "21-50", "51+"),
	erp_implementations_range: rangeOptions("0-5", "6-20", "21-50", "51+"),
	verticals_served: rangeOptions(
		"Manufacturing",
		"Retail",
		"Services",
		"Banking and Finance",
		"Distribution and Trading",
		"Hospitality",
		"Real Estate",
		"Automotive",
		"Government",
		"Education",
		"Healthcare",
		"Non-profit",
		"Other",
	),
	existing_partnerships: rangeOptions("SAP", "Odoo", "Oracle", "Microsoft"),
}

const COMPANY_INFO_FIELDS = [
	"company_name",
	"address",
	"headquarter_city",
	"annual_revenue",
	"revenue_currency",
	"employee_range",
	"certified_employees_range",
	"verticals_served",
	"customer_count_range",
	"erpnext_customer_count_range",
	"existing_partnerships",
	"erp_implementations_range",
	"incorporation_certificate",
	"company_logo",
	"agreed_to_due_diligence",
	"agreed_to_partnership_agreement",
]

function errorMessage(e, fallback) {
	const message = (e && e.messages && e.messages[0]) || (e && e.message) || fallback
	return String(message).replace(/<[^>]*>/g, "")
}

function formatCurrency(amount, currency) {
	return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(amount || 0)
}

function readStash() {
	try {
		const raw = window.sessionStorage.getItem(REGISTRATION_STASH_KEY)
		return raw ? JSON.parse(raw) : null
	} catch {
		return null
	}
}

function clearStash() {
	try {
		window.sessionStorage.removeItem(REGISTRATION_STASH_KEY)
	} catch {
		// storage blocked (private mode etc.) -- nothing was stashed then either
	}
}

// Opens the OS file picker; a file input needn't be in the DOM to be clicked.
function pickFile(accept, onFile) {
	const input = document.createElement("input")
	input.type = "file"
	input.accept = accept
	input.onchange = () => input.files && input.files[0] && onFile(input.files[0])
	input.click()
}

export default function setup(context) {
	// ---- Application + status ----
	const certificateStatus = ref({ ...EMPTY_CERTIFICATE_STATUS })
	const mrrStatus = ref({ current_amount: 0, target_amount: 100, currency: "USD", progress: 0, requirement_complete: false })

	function app() {
		return context.partnerApplication.data || null
	}

	function amPartner() {
		return !!(context.myContext.data && context.myContext.data.partner)
	}

	// Logged in, but not on any partner's roster -- get_partner_application can't resolve a
	// partner for them, so the page shows a notice instead of a checklist that can't save.
	function notPartner() {
		return !!context.myContext.fetched && !amPartner()
	}

	function isRegistered() {
		return !!(app() && app().name)
	}

	function isDecided() {
		const doc = app()
		return !!doc && (doc.docstatus === 1 || ["Approved", "Pending Review", "Rejected"].includes(doc.status))
	}

	function canEditDraft() {
		const doc = app()
		return !!doc && doc.docstatus === 0 && doc.status === "Draft"
	}

	function isRegistrationComplete() {
		const doc = app()
		if (!doc) return false
		if (isDecided()) return true
		if (doc.registered_country === "India" && !doc.registered_state) return false
		return !!(doc.company_name && doc.registered_country && doc.company_email && doc.contact)
	}

	function isProfileComplete() {
		const doc = app()
		if (!doc) return false
		if (isDecided()) return true
		const hasState = doc.registered_country !== "India" || !!doc.registered_state
		return !!(
			doc.company_name &&
			doc.registered_country &&
			hasState &&
			doc.company_email &&
			doc.contact &&
			doc.address &&
			doc.headquarter_city &&
			doc.incorporation_certificate &&
			doc.company_logo &&
			doc.agreed_to_due_diligence &&
			doc.agreed_to_partnership_agreement
		)
	}

	function loadCertificateStatus() {
		if (!isRegistered()) {
			certificateStatus.value = { ...EMPTY_CERTIFICATE_STATUS }
			return Promise.resolve()
		}
		return call(`${API}.get_certificate_link_status`).then((status) => {
			certificateStatus.value = status
		})
	}

	function loadMRRStatus() {
		return call(`${API}.get_mrr_status`).then((status) => {
			mrrStatus.value = status
		})
	}

	// get_partner_application throws for anyone not on a partner's roster, so it isn't an auto
	// resource: it loads once myContext confirms a partner, and never fires for customers.
	watch(
		() => amPartner(),
		(isPartner) => {
			if (isPartner) context.partnerApplication.reload()
		},
		{ immediate: true },
	)

	// Press's load(): certificate + MRR status are independent, so fetch them concurrently.
	watch(
		() => context.partnerApplication.data,
		(doc) => {
			if (doc && doc.name) Promise.all([loadCertificateStatus(), loadMRRStatus()])
			else certificateStatus.value = { ...EMPTY_CERTIFICATE_STATUS }
		},
		{ immediate: true },
	)

	function reloadApplication() {
		return context.partnerApplication.reload()
	}

	// ---- Steps accordion ----
	function stepStatus(key) {
		const done = {
			"step-register": isRegistrationComplete(),
			"step-profile": isProfileComplete(),
			"step-certificates": !!certificateStatus.value.requirement_complete,
			"step-mrr": !!mrrStatus.value.requirement_complete,
		}
		return done[key] ? "completed" : "pending"
	}

	const openStep = ref("step-profile")

	// Like Press, the next unfinished step opens by itself as the checklist progresses.
	watch(
		() => STEP_ORDER.find((key) => stepStatus(key) !== "completed") || "",
		(next) => {
			openStep.value = next
		},
		{ immediate: true },
	)

	function isStepOpen(key) {
		return openStep.value === key
	}

	function toggleStep(key) {
		openStep.value = openStep.value === key ? "" : key
	}

	function registerActionLabel() {
		if (!isRegistered()) return "Register as a partner"
		return canEditDraft() ? "Edit registration" : "Registered"
	}

	function linkedCertificateCount() {
		return certificateStatus.value.linked_count || 0
	}

	function hasCertificateActivity() {
		return isRegistered() && (linkedCertificateCount() > 0 || (certificateStatus.value.link_requests || []).length > 0)
	}

	function certificatesSummary() {
		return certificateStatus.value.requirement_complete ? "" : `${linkedCertificateCount()} / 2 linked`
	}

	function mrrCurrentLabel() {
		return formatCurrency(mrrStatus.value.current_amount, mrrStatus.value.currency)
	}

	function mrrTargetLabel() {
		return formatCurrency(mrrStatus.value.target_amount, mrrStatus.value.currency)
	}

	function mrrSummary() {
		return mrrStatus.value.requirement_complete ? "" : `${mrrCurrentLabel()} / ${mrrTargetLabel()}`
	}

	function mrrProgressWidth() {
		return `${Math.min(100, Math.max(0, mrrStatus.value.progress || 0))}%`
	}

	// ---- Submit for approval / primary action ----
	const submitting = ref(false)

	function isApproved() {
		return !!app() && app().status === "Approved"
	}

	function isRejected() {
		return !!app() && app().status === "Rejected"
	}

	function reviewerComments() {
		return (app() && app().reviewer_comments) || ""
	}

	function canSubmit() {
		return (
			canEditDraft() &&
			isProfileComplete() &&
			!!certificateStatus.value.requirement_complete &&
			!!mrrStatus.value.requirement_complete
		)
	}

	function canClickPrimary() {
		return canSubmit() || isApproved() || isRejected()
	}

	function submitLabel() {
		if (isApproved()) return "Become an active partner"
		if (isRejected()) return "Start new application"
		const doc = app()
		if (doc && (doc.docstatus === 1 || doc.status === "Pending Review")) return "Submitted for approval"
		return "Submit for approval"
	}

	function submitIcon() {
		return isApproved() || isRejected() ? "lucide-circle-check" : "lucide-lock"
	}

	function primaryAction() {
		if (isApproved()) {
			context.router.push("/messaging")
			return
		}
		if (isRejected()) {
			unregister(false).then((ok) => ok && toast.success("You can start a new application"))
			return
		}
		submitting.value = true
		call(`${API}.submit_partner_application_for_approval`)
			.then(() => reloadApplication())
			.then(() => toast.success("Details submitted for approval"))
			.catch((e) => toast.error(errorMessage(e, "Could not submit for approval")))
			.finally(() => {
				submitting.value = false
			})
	}

	// ---- Right sidebar card ----
	function companyName() {
		return (app() && app().company_name) || partnershipCompanyName.value || "Company Name"
	}

	function companyInitial() {
		return companyName().trim().charAt(0)
	}

	function applicationStatus() {
		return (app() && app().status) || "Inactive"
	}

	function statusLabel() {
		return applicationStatus() === "Pending Review" ? "In review" : applicationStatus()
	}

	function statusTheme() {
		const status = applicationStatus()
		if (status === "Approved") return "green"
		if (status === "Pending Review") return "gray"
		if (status === "Rejected") return "red"
		return "amber"
	}

	// ---- Unregister ----
	const unregisterOpen = ref(false)
	const unregistering = ref(false)

	function unregisterMessage() {
		return isApproved()
			? "This removes your partner registration and partner privileges."
			: "This deletes your current application. You can reapply later, but the company will need to go through review again."
	}

	function unregister(leavePage) {
		unregistering.value = true
		return call(`${API}.unregister_partner_application`)
			.then(() => {
				certificateStatus.value = { ...EMPTY_CERTIFICATE_STATUS }
				unregisterOpen.value = false
				return reloadApplication()
			})
			.then(() => {
				if (leavePage) {
					toast.success("Partner registration removed")
					context.router.push("/messaging")
				}
				return true
			})
			.catch((e) => {
				toast.error(errorMessage(e, "Could not unregister"))
				return false
			})
			.finally(() => {
				unregistering.value = false
			})
	}

	// ---- Registration wizard (same blocks as the messaging page's "Frappe partnerships") ----
	const partnershipWizardOpen = ref(false)
	const partnershipWizardStep = ref("partnerships")
	const partnershipEditMode = ref(false)
	const partnershipRegistered = ref(false)
	const partnershipSubmitted = ref(false)
	const partnershipSubmitError = ref("")
	const partnershipSaving = ref(false)
	const partnershipCompanyName = ref("")
	const partnershipCountry = ref("")
	const partnershipState = ref("")
	const partnershipEmail = ref("")
	const partnershipContact = ref("")
	const partnershipIsdCountry = ref("")
	const partnershipIsdSearch = ref("")

	function countries() {
		return context.partnershipCountries.data || []
	}

	// Stored contact is "<isd>-<number>", same as the messaging page's wizard writes it.
	function fillRegistration(details) {
		partnershipCompanyName.value = details.company_name || ""
		partnershipCountry.value = details.registered_country || ""
		partnershipState.value = details.registered_state || ""
		partnershipEmail.value = details.company_email || ""
		partnershipIsdCountry.value = ""
		partnershipIsdSearch.value = ""
		const contact = String(details.contact || "")
		if (contact.includes("-")) {
			const [isd, ...rest] = contact.split("-")
			const match = countries().find((c) => c.isd === isd)
			if (match) partnershipIsdCountry.value = match.name
			partnershipContact.value = rest.join("-")
		} else {
			partnershipContact.value = contact
		}
	}

	function registrationDetails() {
		const match = countries().find((c) => c.name === (partnershipIsdCountry.value || partnershipCountry.value))
		const number = String(partnershipContact.value || "").trim()
		return {
			company_name: String(partnershipCompanyName.value || "").trim(),
			registered_country: partnershipCountry.value,
			registered_state: partnershipCountry.value === "India" ? partnershipState.value : "",
			company_email: String(partnershipEmail.value || "").trim(),
			contact: match && number ? `${match.isd}-${number}` : number,
		}
	}

	function openRegistration() {
		if (!context.partnershipCountries.data) context.partnershipCountries.reload()
		fillRegistration(app() || {})
		partnershipEditMode.value = canEditDraft()
		partnershipRegistered.value = false
		partnershipSubmitted.value = false
		partnershipSubmitError.value = ""
		partnershipWizardStep.value = isRegistered() ? "registration" : "partnerships"
		partnershipWizardOpen.value = true
	}

	// Called from the wizard's Proceed / Save buttons after their field validation passes.
	function saveRegistration(details) {
		const editing = partnershipEditMode.value
		partnershipSaving.value = true
		return call(`${API}.save_partner_application`, { details: details || registrationDetails() })
			.then(() => reloadApplication())
			.then(() => {
				if (editing) {
					partnershipWizardOpen.value = false
					toast.success("Registration details updated")
				} else {
					partnershipRegistered.value = true
				}
			})
			.catch((e) => {
				partnershipSubmitError.value = errorMessage(e, "Could not save your registration.")
			})
			.finally(() => {
				partnershipSaving.value = false
			})
	}

	// A visitor who registered from the login page arrives here after logging in: register the
	// details they already filled in, then show the same "thank you" screen Press shows.
	watch(
		() => !!context.myContext.fetched && !!context.partnerApplication.fetched && amPartner(),
		(ready) => {
			if (!ready || isRegistered()) return
			const stash = readStash()
			if (!stash) return
			clearStash()
			fillRegistration(stash)
			partnershipEditMode.value = false
			partnershipRegistered.value = false
			partnershipSubmitError.value = ""
			partnershipWizardStep.value = "registration"
			partnershipWizardOpen.value = true
			saveRegistration(stash)
		},
		{ immediate: true },
	)

	// ---- Company information (3 steps) ----
	const companyInfoOpen = ref(false)
	const companyInfoStep = ref(0)
	const companyInfoSubmitted = ref([false, false, false])
	const companyInfoSaving = ref(false)
	const uploadingLogo = ref(false)
	const uploadingCertificate = ref(false)
	// A ref, not reactive(): Studio writes nested v-model paths ("draft.address") only into refs.
	const draft = ref({})

	function openCompanyInfo() {
		const doc = app() || {}
		for (const field of COMPANY_INFO_FIELDS) draft.value[field] = doc[field] ?? ""
		draft.value.revenue_currency = doc.revenue_currency || (doc.registered_country === "India" ? "INR" : "USD")
		draft.value.verticals_served = String(doc.verticals_served || "")
			.split(",")
			.map((v) => v.trim())
			.filter(Boolean)
		draft.value.agreed_to_due_diligence = !!doc.agreed_to_due_diligence
		draft.value.agreed_to_partnership_agreement = !!doc.agreed_to_partnership_agreement
		companyInfoStep.value = 0
		companyInfoSubmitted.value = [false, false, false]
		companyInfoOpen.value = true
	}

	function companyInfoTitle() {
		const name = String(draft.value.company_name || (app() && app().company_name) || "").trim()
		return `Tell us more about ${name || "your company"}`
	}

	function companyInfoIndicator() {
		return `Step ${companyInfoStep.value + 1}/3`
	}

	function companyInfoProgress() {
		return `${((companyInfoStep.value + 1) / 3) * 100}%`
	}

	function lengthError(value, label, min, max) {
		const trimmed = String(value || "").trim()
		if (!trimmed) return `${label} is required.`
		if (trimmed.length < min) return `${label} must be at least ${min} characters.`
		if (trimmed.length > max) return `${label} must be ${max} characters or less.`
		return ""
	}

	function annualRevenueError(value) {
		const trimmed = String(value || "").trim()
		if (!trimmed) return ""
		if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return "Annual revenue must be a valid amount."
		if (trimmed.replace(/\D/g, "").length > 12) return "Annual revenue must be 12 digits or less."
		return ""
	}

	// Errors show only after the step's Continue was tried, like Press's `submitted` flag.
	function companyInfoError(field) {
		const step = { company_name: 0, address: 0, headquarter_city: 0, annual_revenue: 0 }[field] ?? 2
		if (!companyInfoSubmitted.value[step]) return ""
		const errors = {
			company_name: lengthError(draft.value.company_name, "Company name", 2, 140),
			address: lengthError(draft.value.address, "Address", 10, 300),
			headquarter_city: lengthError(draft.value.headquarter_city, "Headquarter city", 2, 80),
			annual_revenue: annualRevenueError(draft.value.annual_revenue),
			company_logo: draft.value.company_logo ? "" : "Company logo is required.",
			incorporation_certificate: draft.value.incorporation_certificate ? "" : "Incorporation certificate is required.",
			agreed_to_due_diligence: draft.value.agreed_to_due_diligence ? "" : "Due diligence confirmation is required.",
			agreed_to_partnership_agreement: draft.value.agreed_to_partnership_agreement
				? ""
				: "Partnership agreement acceptance is required.",
		}
		return errors[field] || ""
	}

	const STEP_FIELDS = [
		["company_name", "address", "headquarter_city", "annual_revenue"],
		[],
		["company_logo", "incorporation_certificate", "agreed_to_due_diligence", "agreed_to_partnership_agreement"],
	]

	function companyInfoPrimaryLabel() {
		return companyInfoStep.value === 2 ? "Save details" : "Continue"
	}

	function companyInfoContinue() {
		const step = companyInfoStep.value
		companyInfoSubmitted.value = companyInfoSubmitted.value.map((v, i) => (i === step ? true : v))
		if (STEP_FIELDS[step].some((field) => companyInfoError(field))) return
		if (step < 2) {
			companyInfoStep.value = step + 1
			return
		}
		companyInfoSaving.value = true
		call(`${API}.save_partner_application`, { details: { ...draft.value } })
			.then(() => Promise.all([reloadApplication(), loadMRRStatus()]))
			.then(() => {
				toast.success("Company details updated")
				companyInfoOpen.value = false
			})
			.catch((e) => toast.error(errorMessage(e, "Could not save company details")))
			.finally(() => {
				companyInfoSaving.value = false
			})
	}

	// ---- Press-style selects in the company information steps ----
	// Press renders these with frappe-ui 0.1.277's reka Select (verticals_served with `multiple`);
	// Studio's Select has no multiple mode, so the page draws the same control on a Popover and
	// keeps the options here. A field whose draft value is an array is multi-select.
	function selectOptions(field) {
		return SELECT_OPTIONS[field] || []
	}

	function isOptionSelected(field, value) {
		const current = draft.value[field]
		return Array.isArray(current) ? current.includes(value) : current === value
	}

	function selectOption(field, value) {
		const current = draft.value[field]
		if (!Array.isArray(current)) {
			draft.value[field] = value
			return
		}
		draft.value[field] = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
	}

	function selectDisplay(field) {
		return selectOptions(field)
			.filter((option) => isOptionSelected(field, option.value))
			.map((option) => option.label)
			.join(", ")
	}

	function companyInfoBack() {
		if (companyInfoStep.value > 0) companyInfoStep.value -= 1
	}

	function currencyPrefix() {
		return { USD: "$", EUR: "€" }[draft.value.revenue_currency] || "₹"
	}

	function mrrTargetForCountry() {
		return (app() && app().registered_country) === "India" ? "₹10,000" : "$100"
	}

	function uploadDraftFile(field, file, isPrivate, maxBytes, uploadingRef) {
		if (file.size > maxBytes) {
			toast.error(`File size must be under ${maxBytes / (1024 * 1024)} MB.`)
			return
		}
		uploadingRef.value = true
		useFileUpload()
			.upload(file, { private: isPrivate })
			.then((uploaded) => {
				draft.value[field] = uploaded.file_url || ""
			})
			.catch((e) => toast.error(errorMessage(e, "Upload failed")))
			.finally(() => {
				uploadingRef.value = false
			})
	}

	function uploadLogo() {
		pickFile("image/*", (file) => uploadDraftFile("company_logo", file, false, 5 * 1024 * 1024, uploadingLogo))
	}

	function uploadCertificate() {
		pickFile("application/pdf,image/*", (file) =>
			uploadDraftFile("incorporation_certificate", file, true, 10 * 1024 * 1024, uploadingCertificate),
		)
	}

	function logoButtonLabel() {
		if (uploadingLogo.value) return "Uploading..."
		return draft.value.company_logo ? "Replace logo" : "Upload logo"
	}

	function certificateButtonLabel() {
		if (uploadingCertificate.value) return "Uploading..."
		return draft.value.incorporation_certificate ? "Replace document" : "Attach document"
	}

	// ---- Link certificate ----
	const linkCertificateOpen = ref(false)
	const certificateType = ref("frappe")
	const certificateEmail = ref("")
	const certificateSubmitted = ref(false)
	const certificateError = ref("")
	const certificateSending = ref(false)

	function openLinkCertificate() {
		certificateType.value = "frappe"
		certificateEmail.value = ""
		certificateSubmitted.value = false
		certificateError.value = ""
		loadCertificateStatus()
		linkCertificateOpen.value = true
	}

	function selectCertificateType(type) {
		certificateType.value = type
		certificateError.value = ""
	}

	function certificateEmailError() {
		if (!certificateSubmitted.value) return ""
		const email = String(certificateEmail.value || "").trim()
		if (!email) return "User email is required."
		return /^\S+@\S+\.\S+$/.test(email) ? "" : "Enter a valid email address."
	}

	function hasPendingRequest(email, type) {
		const courses = {
			frappe: ["frappe-developer-certification", "app-development-with-frappe-framework"],
			erpnext: ["erpnext-distribution", "erpnext-training"],
		}[type]
		return (certificateStatus.value.pending_requests || []).some(
			(r) => r.user_email.toLowerCase() === email.toLowerCase() && courses.includes(r.course),
		)
	}

	function sendCertificateLink() {
		certificateSubmitted.value = true
		certificateError.value = ""
		if (certificateEmailError()) return
		const email = String(certificateEmail.value).trim()
		if (hasPendingRequest(email, certificateType.value)) {
			certificateError.value = "Verification email already sent to this email."
			return
		}
		certificateSending.value = true
		call(`${API}.send_certificate_link_request`, { user_email: email, certificate_type: certificateType.value })
			.then((result) => loadCertificateStatus().then(() => result))
			.then((result) => {
				toast.success(result && result.status === "Linked" ? "Certificate already linked" : "Validation email sent")
				linkCertificateOpen.value = false
			})
			.catch((e) => {
				certificateError.value = errorMessage(e, "Could not send verification email.")
			})
			.finally(() => {
				certificateSending.value = false
			})
	}

	// ---- Certificate link status ----
	const certificateStatusOpen = ref(false)
	const resendingRequest = ref("")

	function openCertificateStatus() {
		loadCertificateStatus()
		certificateStatusOpen.value = true
	}

	function courseLabel(course) {
		return COURSE_LABELS[course] || course
	}

	// One list for the dialog: linked certificates without a matching request, then requests.
	function certificateRows() {
		const requests = certificateStatus.value.link_requests || []
		const requestKeys = new Set(requests.map((r) => `${r.user_email.toLowerCase()}:${r.course}`))
		const linked = (certificateStatus.value.linked_certificates || [])
			.filter((c) => !requestKeys.has(`${String(c.partner_member_email).toLowerCase()}:${c.course}`))
			.map((c) => ({ key: c.name, email: c.partner_member_email, course: c.course, status: "Linked" }))
		const pending = requests.map((r) => ({ key: r.name, email: r.user_email, course: r.course, status: r.status }))
		return [...linked, ...pending]
	}

	function rowStatusLabel(row) {
		if (row.status === "Linked") return "Linked"
		return row.status === "Approved" ? "Approved" : "Approval pending"
	}

	function rowStatusTheme(row) {
		return row.status === "Pending" ? "amber" : "green"
	}

	function resendRequest(name) {
		resendingRequest.value = name
		call(`${API}.resend_certificate_link_request`, { request_name: name })
			.then(() => loadCertificateStatus())
			.then(() => toast.success("Verification email sent"))
			.catch((e) => toast.error(errorMessage(e, "Could not resend")))
			.finally(() => {
				resendingRequest.value = ""
			})
	}

	// ---- Rail: logo account menu (same as the messaging page) ----
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
		notPartner,
		isRegistered,
		canEditDraft,
		stepStatus,
		isStepOpen,
		toggleStep,
		registerActionLabel,
		hasCertificateActivity,
		certificatesSummary,
		mrrCurrentLabel,
		mrrTargetLabel,
		mrrSummary,
		mrrProgressWidth,
		submitting,
		isRejected,
		reviewerComments,
		canClickPrimary,
		submitLabel,
		submitIcon,
		primaryAction,
		companyName,
		companyInitial,
		statusLabel,
		statusTheme,
		unregisterOpen,
		unregistering,
		unregisterMessage,
		unregister,
		partnershipWizardOpen,
		partnershipWizardStep,
		partnershipEditMode,
		partnershipRegistered,
		partnershipSubmitted,
		partnershipSubmitError,
		partnershipSaving,
		partnershipCompanyName,
		partnershipCountry,
		partnershipState,
		partnershipEmail,
		partnershipContact,
		partnershipIsdCountry,
		partnershipIsdSearch,
		openRegistration,
		saveRegistration,
		companyInfoOpen,
		companyInfoStep,
		companyInfoSaving,
		draft,
		openCompanyInfo,
		companyInfoTitle,
		companyInfoIndicator,
		companyInfoProgress,
		companyInfoError,
		companyInfoPrimaryLabel,
		companyInfoContinue,
		companyInfoBack,
		selectOptions,
		isOptionSelected,
		selectOption,
		selectDisplay,
		currencyPrefix,
		mrrTargetForCountry,
		uploadingLogo,
		uploadingCertificate,
		uploadLogo,
		uploadCertificate,
		logoButtonLabel,
		certificateButtonLabel,
		linkCertificateOpen,
		certificateType,
		certificateEmail,
		certificateError,
		certificateSending,
		openLinkCertificate,
		selectCertificateType,
		certificateEmailError,
		sendCertificateLink,
		certificateStatusOpen,
		resendingRequest,
		openCertificateStatus,
		courseLabel,
		certificateRows,
		rowStatusLabel,
		rowStatusTheme,
		resendRequest,
		accountMenuOptions,
	}
}
