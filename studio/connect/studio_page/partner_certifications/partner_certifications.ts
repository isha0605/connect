// The partner's Certifications: their team's Frappe School certificates, the link requests still
// waiting on the holder, and the two ways to add one. Link Certificate brings in a certificate
// someone already has (the holder approves by email). Apply for Certification asks Frappe for one
// of the partner's free certifications, once Frappe has approved the partnership; until then it
// sends the team member to the paid exam on Frappe School. The admin can remove a certificate,
// for example when its holder leaves; an expired one stays listed but no longer counts.

import { computed, onScopeDispose, ref } from "vue"
import { startTracking } from "@app/utils/tracking"

const API = "connect.api.partner"
const COURSES = [
	{ label: "ERPNext", value: "erpnext" },
	{ label: "Framework", value: "frappe" },
]
const SCHOOL_URL = "https://school.frappe.io"
// The Certificate Application doctype stores the type by these labels.
const TYPE_LABELS = { erpnext: "ERPNext", frappe: "Framework" }
const APPLICATION_THEMES = { Applied: "amber", Approved: "blue", Certified: "green", Rejected: "red" }
const APPLICATION_HINTS = {
	Applied: "Waiting for Frappe to approve",
	Approved: "Approved. They can take the exam on Frappe School",
	Certified: "Certified. We emailed them to confirm it",
}
// A certificate gets a warning icon this many days before it expires.
const EXPIRY_WARNING_DAYS = 60
const DAY_MS = 24 * 60 * 60 * 1000

// What the editor shows when its user is on no partner's team, such as Administrator.
const SAMPLE_STATUS = {
	linked_certificates: [
		{ name: "sample-1", partner_member_name: "Ashish Shah", partner_member_email: "ashish@example.com", issue_date: "2022-11-04",
			course_label: "Framework", certificate_url: SCHOOL_URL },
		{ name: "sample-2", partner_member_name: "Reeta Naryal", partner_member_email: "reeta@example.com", issue_date: "2023-11-06",
			expiry_date: "2026-01-31", is_expired: true, course_label: "ERPNext", certificate_url: SCHOOL_URL },
	],
	pending_requests: [{ name: "sample-request", user_email: "jignesh@example.com", course_label: "ERPNext", creation: "2026-10-30" }],
	can_edit: true,
	applications: [
		{ name: "sample-application", member_email: "nikhil@example.com", certificate_type: "Framework", status: "Approved", creation: "2026-10-28" },
	],
	free_certifications: { is_registered: true, allowance: 2, used: 1, left: 1, can_apply: true },
	course_pages: {
		erpnext: `${SCHOOL_URL}/lms/courses/erpnext-training`,
		frappe: `${SCHOOL_URL}/lms/courses/frappe-developer-certification`,
	},
}

const longDate = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "long", day: "numeric" })

function formatDate(value) {
	return value ? longDate.format(new Date(value)) : ""
}

// The icon beside a certificate's issue date: "expired", "soon" (within EXPIRY_WARNING_DAYS) or "".
function expiryState(row) {
	if (!row.expiry_date) return ""
	if (row.is_expired) return "expired"
	return new Date(row.expiry_date).getTime() - Date.now() <= EXPIRY_WARNING_DAYS * DAY_MS ? "soon" : ""
}

function expiryTip(row, state) {
	if (state === "expired") return `Expired on ${formatDate(row.expiry_date)}. It no longer counts for your partnership.`
	if (state === "soon") return `Expires on ${formatDate(row.expiry_date)}. Renew it on Frappe School to keep it counting.`
	return ""
}

function openInNewTab(url) {
	if (url) window.open(url, "_blank", "noopener")
}

export default function setup(context) {
	startTracking(context)
	const { call, toast, socket } = context

	const status = ref(null)
	const loadError = ref(false)
	const loading = ref(false)

	const inEditor = window.location.pathname.startsWith("/studio/")
	function load() {
		loading.value = true
		return call(`${API}.get_certificate_link_status`)
			.then((data) => {
				status.value = data
				loadError.value = false
			})
			.catch(() => {
				if (inEditor) status.value = SAMPLE_STATUS
				else loadError.value = true
			})
			.finally(() => {
				loading.value = false
			})
	}
	load()

	// The holder approving from their email updates this list without a refresh.
	const onCertificatesUpdated = () => load()
	socket?.on("partner_application_certificates_updated", onCertificatesUpdated)
	onScopeDispose(() => socket?.off("partner_application_certificates_updated", onCertificatesUpdated))

	// ---- The list ----
	const courseFilter = ref("")
	const certificates = computed(() =>
		(status.value?.linked_certificates || [])
			.filter((row) => !courseFilter.value || row.course_label === courseFilter.value)
			.map((row) => {
				const expiry = expiryState(row)
				return { ...row, issued: formatDate(row.issue_date), expiry, expiryTip: expiryTip(row, expiry) }
			}),
	)
	const pendingRequests = computed(() =>
		(status.value?.pending_requests || []).map((row) => ({ ...row, sent: `Sent ${formatDate(row.creation)}` })),
	)
	const resending = ref("")

	function resend(request) {
		resending.value = request.name
		call(`${API}.resend_certificate_link_request`, { request_name: request.name })
			.then(() => toast.success(`Sent again to ${request.user_email}`))
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't send it again. Try again."))
			.finally(() => {
				resending.value = ""
			})
	}

	// ---- Remove: the admin unlinks a certificate, after confirming ----
	const removeOpen = ref(false)
	const removing = ref(false)
	const toRemove = ref(null)

	function askRemove(row) {
		toRemove.value = row
		removeOpen.value = true
	}

	function confirmRemove() {
		if (removing.value || !toRemove.value) return
		removing.value = true
		call(`${API}.remove_certificate`, { certificate: toRemove.value.name })
			.then(() => {
				removeOpen.value = false
				toast.success("Certificate removed")
				return load()
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't remove the certificate. Try again."))
			.finally(() => {
				removing.value = false
			})
	}

	// ---- Link Certificate: for someone who already has one ----
	const linkOpen = ref(false)
	const linkForm = ref({ email: "", type: "erpnext" })
	const linkError = ref("")
	const linking = ref(false)

	function openLink() {
		linkForm.value = { email: "", type: "erpnext" }
		linkError.value = ""
		linkOpen.value = true
	}

	function sendLink() {
		const email = String(linkForm.value.email || "").trim()
		if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
			linkError.value = "Enter the email they use on Frappe School."
			return
		}
		linking.value = true
		linkError.value = ""
		call(`${API}.send_certificate_link_request`, { user_email: email, certificate_type: linkForm.value.type })
			.then((result) => {
				linkOpen.value = false
				if (result?.status === "Linked") toast.success("That certificate is already on your list.")
				else toast.success(`We emailed ${email}. The certificate shows here once they approve.`)
				return load()
			})
			.catch((error) => {
				linkError.value = error?.messages?.[0] || "Couldn't send the request. Try again."
			})
			.finally(() => {
				linking.value = false
			})
	}

	// ---- Apply for Certification: a free one from Frappe, or the paid exam on Frappe School ----
	const applyOpen = ref(false)
	const applyCourse = ref("erpnext")
	const applyEmail = ref("")
	const applyError = ref("")
	const applying = ref(false)
	const free = computed(() => status.value?.free_certifications || {})
	const canApplyFree = computed(() => !!free.value.can_apply)
	const freeText = computed(() => {
		const f = free.value
		if (!f.is_registered) {
			return `Frappe gives ${f.allowance} free certifications once it approves your partnership. Until then, your team member can take the paid exam on Frappe School.`
		}
		if (!f.left) return `You've used all ${f.allowance} of your free certifications. Your team member can take the paid exam on Frappe School.`
		return `${f.left} of ${f.allowance} free certifications left. Frappe approves the application and gives them free access to the exam.`
	})

	function openApply() {
		applyCourse.value = "erpnext"
		applyEmail.value = ""
		applyError.value = ""
		applyOpen.value = true
	}

	function submitApply() {
		if (!canApplyFree.value) {
			openInNewTab(status.value?.course_pages?.[applyCourse.value])
			applyOpen.value = false
			return
		}
		const email = String(applyEmail.value || "").trim()
		if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
			applyError.value = "Enter the email they use on Frappe School."
			return
		}
		applying.value = true
		applyError.value = ""
		call(`${API}.apply_for_certificate`, { member_email: email, certificate_type: TYPE_LABELS[applyCourse.value] })
			.then(() => {
				applyOpen.value = false
				toast.success("Applied. We'll email you once Frappe reviews it.")
				return load()
			})
			.catch((error) => {
				applyError.value = error?.messages?.[0] || "Couldn't apply. Try again."
			})
			.finally(() => {
				applying.value = false
			})
	}

	// ---- Free certification applications ----
	const applications = computed(() =>
		(status.value?.applications || []).map((row) => ({
			...row,
			theme: APPLICATION_THEMES[row.status] || "gray",
			meta: `${row.certificate_type} · ${row.status === "Rejected" ? `Not approved: ${row.rejection_reason}` : APPLICATION_HINTS[row.status]}`,
			canCancel: row.status === "Applied",
		})),
	)
	const cancelling = ref("")
	const checking = ref(false)

	function cancelApplication(row) {
		cancelling.value = row.name
		call(`${API}.cancel_certificate_application`, { application: row.name })
			.then(() => {
				toast.success("Application cancelled")
				return load()
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't cancel it. Try again."))
			.finally(() => {
				cancelling.value = ""
			})
	}

	// The daily check runs anyway; this asks Frappe School now.
	function checkApplications() {
		checking.value = true
		call(`${API}.check_certificate_applications`)
			.then((result) => {
				const count = result?.certified?.length || 0
				toast.success(count ? `${count} certified. We emailed them to confirm.` : "No new certificates on Frappe School yet.")
				return load()
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't reach Frappe School. Try again."))
			.finally(() => {
				checking.value = false
			})
	}

	return {
		status,
		loadError,
		loading,
		load,
		courseFilter,
		courseFilterOptions: [{ label: "All courses", value: "" }, ...COURSES.map((course) => ({ label: course.label, value: course.label }))],
		certificates,
		hasCertificates: computed(() => (status.value?.linked_certificates || []).length > 0),
		pendingRequests,
		resending,
		resend,
		openCertificate: (row) => openInNewTab(row.certificate_url),
		canEdit: computed(() => !!status.value?.can_edit),
		removeOpen,
		removing,
		askRemove,
		confirmRemove,
		removeText: computed(() =>
			toRemove.value
				? `${toRemove.value.partner_member_name}'s ${toRemove.value.course_label} certificate will no longer count for your partnership.`
				: "",
		),
		openSchool: () => openInNewTab(SCHOOL_URL),
		courseOptions: COURSES,
		linkOpen,
		linkForm,
		linkError,
		linking,
		openLink,
		sendLink,
		applyOpen,
		applyCourse,
		applyEmail,
		applyError,
		applying,
		canApplyFree,
		freeText,
		openApply,
		submitApply,
		applications,
		hasApprovedApplications: computed(() => applications.value.some((row) => row.status === "Approved")),
		cancelling,
		cancelApplication,
		checking,
		checkApplications,
	}
}
