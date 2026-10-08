<script setup>
// Settings (Profile, Users, Working hours, a customer's Requirements and a partner admin's CRM
// connection) for every page with the shared sidebar. The
// sidebar's logo menu opens it with a "connect:open-settings" window event, so pages need no
// script of their own for it. Same server calls as Messaging's own settings.
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import {
	Avatar,
	Badge,
	Button,
	Checkbox,
	Dialog,
	Dropdown,
	FormControl,
	Spinner,
	call,
	toast,
	useFileUpload,
} from "frappe-ui"

const open = ref(false)
const tab = ref("profile")

const errorText = (e, fallback) => (e && e.messages && e.messages[0]) || (e && e.message) || fallback

// ---- Profile ----
const profile = ref(null)
const fullName = ref("")
const role = ref("")
const phone = ref("")
const savingProfile = ref(false)
const uploadingPhoto = ref(false)

async function loadProfile() {
	try {
		profile.value = await call("connect.api.account.get_my_profile")
	} catch (e) {
		profile.value = null
	}
	fullName.value = profile.value?.full_name || ""
	role.value = profile.value?.role || ""
	phone.value = profile.value?.phone || ""
}

const profileChanged = computed(
	() =>
		!!profile.value &&
		(fullName.value.trim() !== (profile.value.full_name || "") ||
			role.value.trim() !== (profile.value.role || "") ||
			phone.value.trim() !== (profile.value.phone || "")),
)

async function saveProfile() {
	if (!fullName.value.trim() || savingProfile.value || !profileChanged.value) return
	savingProfile.value = true
	try {
		await call("connect.api.account.update_my_profile", {
			full_name: fullName.value.trim(),
			phone: phone.value.trim(),
			role: role.value.trim(),
		})
		await loadProfile()
		toast.success("Profile saved")
	} catch (e) {
		toast.error(errorText(e, "Could not save your profile"))
	} finally {
		savingProfile.value = false
	}
}

function pickPhoto() {
	if (uploadingPhoto.value) return
	const input = document.createElement("input")
	input.type = "file"
	input.accept = "image/*"
	input.style.display = "none"
	input.addEventListener("change", () => {
		const file = input.files && input.files[0]
		if (file) uploadPhoto(file)
		input.remove()
	})
	document.body.appendChild(input)
	input.click()
}

function uploadPhoto(file) {
	uploadingPhoto.value = true
	const { upload } = useFileUpload()
	upload(file, { upload_endpoint: "/api/method/connect.api.account.upload_profile_image" })
		.then(() => loadProfile())
		.then(() => toast.success("Photo updated"))
		.catch((e) => toast.error(errorText(e, "Could not upload photo")))
		.finally(() => {
			uploadingPhoto.value = false
		})
}

// ---- Users: the caller's company ----
const team = ref([])
const me = ref("")
const teamError = ref("")
const amAdmin = computed(() => team.value.some((m) => m.user === me.value && m.is_admin))
const showAdd = ref(false)
const newEmail = ref("")
const newRole = ref("")
const adding = ref(false)

async function loadTeam() {
	teamError.value = ""
	try {
		const [rows, context] = await Promise.all([
			call("connect.api.account.get_my_team"),
			call("connect.api.account.get_my_context"),
		])
		team.value = (rows || []).filter((m) => !m.is_removed)
		me.value = context?.user || ""
		isCustomer.value = !!context?.customer && !context?.partner
		isPartnerAdmin.value = !!(context?.partner && context.partner.is_admin)
		if (isPartnerAdmin.value) loadCrm()
	} catch (e) {
		team.value = []
		teamError.value = errorText(e, "You are not a member of any company")
	}
}

async function addMember() {
	if (!newEmail.value.trim() || adding.value) return
	adding.value = true
	try {
		const data = await call("connect.api.account.add_team_member", {
			email: newEmail.value.trim(),
			role: newRole.value.trim() || null,
		})
		showAdd.value = false
		newEmail.value = ""
		newRole.value = ""
		await loadTeam()
		toast.success(data && data.created_user ? "New account created and added" : "Team member added")
	} catch (e) {
		toast.error(errorText(e, "Could not add team member"))
	} finally {
		adding.value = false
	}
}

function memberOptions(member) {
	return [
		{
			label: "Disable",
			icon: "lucide-user-minus",
			theme: "red",
			disabled: !amAdmin.value || member.user === me.value,
			onClick: () => disableMember(member),
		},
	]
}

async function disableMember(member) {
	try {
		await call("connect.api.account.remove_team_member", { member: member.name })
		await loadTeam()
		toast.success("Team member disabled")
	} catch (e) {
		toast.error(errorText(e, "Could not disable team member"))
	}
}

// ---- Working hours ----
const WEEKDAYS = [
	{ key: "monday", label: "Mon" },
	{ key: "tuesday", label: "Tue" },
	{ key: "wednesday", label: "Wed" },
	{ key: "thursday", label: "Thu" },
	{ key: "friday", label: "Fri" },
	{ key: "saturday", label: "Sat" },
	{ key: "sunday", label: "Sun" },
]
const AFTER_HOURS = ["Do nothing", "Suggest sending silently", "Always send silently"]
// Half-hour steps, as HH:mm.
const TIMES = Array.from({ length: 48 }, (_, i) => {
	const h = String(Math.floor(i / 2)).padStart(2, "0")
	return `${h}:${i % 2 ? "30" : "00"}`
})
const saved = ref(null)
const workDays = ref([])
const workStart = ref("09:00")
const workEnd = ref("18:00")
const afterHours = ref("Suggest sending silently")
const savingHours = ref(false)

async function loadHours() {
	try {
		saved.value = await call("connect.api.account.get_my_work_settings")
	} catch (e) {
		saved.value = null
	}
	const s = saved.value || {}
	workDays.value = [...(s.work_days || [])]
	workStart.value = s.work_start || "09:00"
	workEnd.value = s.work_end || "18:00"
	afterHours.value = s.after_hours_behavior || "Suggest sending silently"
}

function toggleDay(key) {
	workDays.value = workDays.value.includes(key)
		? workDays.value.filter((k) => k !== key)
		: [...workDays.value, key]
}

const minutes = (hhmm) => {
	const [h, m] = (hhmm || "00:00").split(":")
	return Number(h) * 60 + Number(m || 0)
}
const hoursError = computed(() => {
	if (!workDays.value.length) return "Pick at least one working day."
	if (minutes(workStart.value) >= minutes(workEnd.value)) return "Your work day must end after it starts."
	return ""
})
const hoursChanged = computed(() => {
	const s = saved.value
	if (!s) return false
	return (
		workStart.value !== s.work_start ||
		workEnd.value !== s.work_end ||
		afterHours.value !== s.after_hours_behavior ||
		WEEKDAYS.some((d) => workDays.value.includes(d.key) !== (s.work_days || []).includes(d.key))
	)
})

async function saveHours() {
	if (savingHours.value || !hoursChanged.value || hoursError.value) return
	savingHours.value = true
	try {
		saved.value = await call("connect.api.account.update_my_work_settings", {
			work_start: workStart.value,
			work_end: workEnd.value,
			work_days: workDays.value,
			after_hours_behavior: afterHours.value,
		})
		toast.success("Working hours saved")
	} catch (e) {
		toast.error(errorText(e, "Could not save working hours"))
	} finally {
		savingHours.value = false
	}
}

// ---- Requirements: the customer's saved Requirement (same fields as Messaging's form) ----
const isCustomer = ref(false)
const INDUSTRIES = ["Manufacturing", "Retail & Distribution", "Healthcare", "Education", "Services", "Construction", "Logistics", "Technology", "Other"]
const APPS = ["ERPNext", "Frappe Books", "Frappe Builder", "Frappe CRM", "Frappe Drive", "Frappe HR", "Frappe Insights", "Frappe LMS", "Helpdesk", "Wiki"]
const LOOKING_FOR = ["New ERP Implementation", "Replace Existing ERP", "Manufacturing Setup", "HR & Payroll", "CRM", "Custom App Development", "Consultation / Discovery", "Not sure yet"]
const COMPANY_SIZES = ["1–10", "11–50", "51–200", "201–1000", "1000+"]
const SITUATIONS = ["Excel / Spreadsheets", "Tally", "SAP", "Oracle", "Odoo", "Existing ERPNext", "Multiple Systems", "No System Yet"]
const TIMELINES = ["Immediately", "Within 1 month", "Within 3 months", "Within 6 months", "Just exploring"]
const DELIVERY = ["Remote", "Hybrid", "On-site", "No preference"]
const BUDGETS = ["Under ₹2L", "₹2L–₹10L", "₹10L–₹25L", "₹25L–₹50L", "₹50L+", "Not decided"]
const SPECIAL = ["ETO (Engineer-to-Order)", "Manufacturing Planning", "Multi-site Operations", "HR & Payroll", "Inventory Management", "CRM", "Custom Development", "SAP Migration", "Data Migration", "Training Required", "On-site Support"]
const req = ref(blankRequirement())
const savingReq = ref(false)

function blankRequirement() {
	return {
		company_name: "",
		country: "",
		industry: "",
		apps: [],
		looking_for: "",
		company_size: "",
		current_situation: "",
		timeline: "",
		delivery_preference: "",
		budget: "",
		special_requirements: [],
	}
}

function parseList(value) {
	if (Array.isArray(value)) return value.map((v) => (typeof v === "string" ? v : v.app || v.name || "")).filter(Boolean)
	try {
		return JSON.parse(value || "[]")
	} catch (e) {
		return []
	}
}

async function loadRequirement() {
	let saved = null
	let context = null
	try {
		;[saved, context] = await Promise.all([
			call("connect.api.customer.get_my_requirement"),
			call("connect.api.account.get_my_context"),
		])
	} catch (e) {
		// An empty form still works.
	}
	req.value = {
		...blankRequirement(),
		...(saved || {}),
		company_name: (saved && saved.company_name) || context?.customer?.customer_name || "",
		apps: parseList(saved && saved.apps),
		special_requirements: parseList(saved && saved.special_requirements),
	}
}

function toggleReq(list, value) {
	const current = req.value[list]
	req.value[list] = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
}

async function saveRequirement() {
	if (savingReq.value) return
	savingReq.value = true
	try {
		const r = req.value
		await call("connect.api.customer.save_customer_requirement", {
			country: r.country,
			industry: r.industry,
			apps: r.apps,
			looking_for: r.looking_for,
			company_size: r.company_size,
			current_situation: r.current_situation,
			timeline: r.timeline,
			delivery_preference: r.delivery_preference,
			budget: r.budget,
			special_requirements: JSON.stringify(r.special_requirements || []),
		})
		toast.success("Your requirements have been saved.")
	} catch (e) {
		toast.error(errorText(e, "Could not save. Please try again."))
	} finally {
		savingReq.value = false
	}
}

// ---- CRM: a partner admin's Frappe CRM connection (Partner CRM Settings) ----
// The first message in a thread opens a Lead on the partner's CRM and later ones attach to it.
const isPartnerAdmin = ref(false)
const crm = ref({ site_url: "", api_key: "", api_secret: "", default_lead_status: "", enabled: false })
const crmSaved = ref(null)
const crmSaving = ref(false)
const crmError = ref("")

function applyCrm(s) {
	crmSaved.value = s || {}
	crm.value = {
		site_url: crmSaved.value.site_url || "",
		api_key: crmSaved.value.api_key || "",
		api_secret: "",
		default_lead_status: crmSaved.value.default_lead_status || "",
		enabled: !!crmSaved.value.enabled,
	}
}

async function loadCrm() {
	crmError.value = ""
	try {
		applyCrm(await call("connect.api.partner.get_my_crm_settings"))
	} catch (e) {
		applyCrm({})
	}
}

const crmStatus = computed(() => {
	const s = crmSaved.value || {}
	if (!s.api_secret_set) return { label: "Not connected", theme: "gray" }
	if (!s.enabled) return { label: "Connected, sync paused", theme: "orange" }
	return s.reply_webhook_connected
		? { label: "Connected, replies syncing", theme: "green" }
		: { label: "Connected", theme: "orange" }
})

const crmChanged = computed(() => {
	const s = crmSaved.value || {}
	const c = crm.value
	return (
		c.site_url !== (s.site_url || "") ||
		c.api_key !== (s.api_key || "") ||
		c.default_lead_status !== (s.default_lead_status || "") ||
		c.enabled !== !!s.enabled ||
		!!c.api_secret
	)
})

async function saveCrm() {
	crmError.value = ""
	const c = crm.value
	if (!c.site_url || !c.api_key || !c.default_lead_status) {
		crmError.value = "Site URL, API key and default lead status are all required."
		return
	}
	if (!crmSaved.value?.api_secret_set && !c.api_secret) {
		crmError.value = "An API secret is required to connect a CRM."
		return
	}
	crmSaving.value = true
	try {
		applyCrm(
			await call("connect.api.partner.save_my_crm_settings", {
				site_url: c.site_url,
				api_key: c.api_key,
				api_secret: c.api_secret,
				default_lead_status: c.default_lead_status,
				enabled: c.enabled ? 1 : 0,
			}),
		)
		toast.success("CRM settings saved")
	} catch (e) {
		crmError.value = errorText(e, "Could not save CRM settings.")
	} finally {
		crmSaving.value = false
	}
}

// ---- Layout: Messaging's settings dialog, section by section ----
const sections = computed(() =>
	[
		{ value: "profile", label: "Profile", icon: "lucide-user" },
		{ value: "users", label: "Users", icon: "lucide-users" },
		{ value: "hours", label: "Working hours", icon: "lucide-clock" },
		isCustomer.value && { value: "requirements", label: "Requirements", icon: "lucide-clipboard-list" },
		isPartnerAdmin.value && { value: "crm", label: "CRM", icon: "lucide-link" },
	].filter(Boolean),
)

const HEADINGS = {
	profile: { title: "Profile", description: "Manage your profile" },
	users: { title: "Users", description: "People at your company" },
	hours: {
		title: "Working hours",
		description: "Set when you're at work. Outside these hours, Connect can suggest sending your messages silently.",
	},
	requirements: {
		title: "Requirements",
		description: "Tell partners what you need so we can show you accurate pricing and matches.",
	},
	crm: { title: "CRM", description: "Connect your Frappe CRM account" },
}
const heading = computed(() => HEADINGS[tab.value] || HEADINGS.profile)

// ---- Opening ----
function openSettings(event) {
	tab.value = (event && event.detail && event.detail.tab) || "profile"
	loadProfile()
	loadTeam()
	loadHours()
	loadRequirement()
	open.value = true
}

onMounted(() => window.addEventListener("connect:open-settings", openSettings))
onBeforeUnmount(() => window.removeEventListener("connect:open-settings", openSettings))
</script>

<template>
	<Dialog v-model="open" size="4xl" bare>
		<div class="relative flex flex-row" style="height: min(620px, 80vh)">
			<!-- left nav -->
			<div
				class="flex w-[220px] shrink-0 flex-col gap-[2px] border-r border-outline-gray-2 p-2"
				style="background-color: var(--surface-sidebar)"
			>
				<div class="my-[3px] flex h-[30px] items-center px-2 py-[7px] text-xs font-medium text-ink-gray-5">Settings</div>
				<button
					v-for="item in sections"
					:key="item.value"
					type="button"
					class="flex h-7 items-center gap-2 rounded-[6px] px-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
					:style="
						tab === item.value
							? 'background-color: var(--surface-elevation-3); box-shadow: 0 1px 2px 0 rgb(0 0 0 / 0.05)'
							: 'background-color: transparent'
					"
					@click="tab = item.value"
				>
					<span :class="[item.icon, 'size-[15px] shrink-0 text-ink-gray-7']" />
					<span class="truncate text-base text-ink-gray-7">{{ item.label }}</span>
				</button>
			</div>

			<!-- right pane -->
			<div class="flex min-h-0 flex-1 flex-col">
				<div class="flex shrink-0 items-start justify-between gap-4 px-10 pt-10">
					<div class="flex min-w-0 flex-col gap-1">
						<h2 class="text-lg font-semibold text-ink-gray-8">{{ heading.title }}</h2>
						<p class="text-base text-ink-gray-6">{{ heading.description }}</p>
					</div>
					<Badge
						v-if="tab === 'crm'"
						class="mt-[2px] shrink-0"
						:label="crmStatus.label"
						:theme="crmStatus.theme"
						variant="subtle"
						size="md"
					/>
				</div>

				<div class="min-h-0 flex-1 overflow-y-auto px-10 pb-10 pt-5" style="scrollbar-width: thin; scrollbar-color: var(--outline-gray-3) transparent">
					<!-- Profile -->
					<template v-if="tab === 'profile'">
						<div class="mb-5 flex items-center justify-center rounded-lg bg-surface-gray-1 py-5">
							<button type="button" class="relative size-[88px] cursor-pointer rounded-full" :disabled="uploadingPhoto" @click="pickPhoto">
								<Avatar
									shape="circle"
									size="3xl"
									:image="profile?.user_image"
									:label="profile?.full_name || profile?.email || ''"
									class="!size-[88px]"
								/>
								<span
									v-if="uploadingPhoto"
									class="absolute inset-0 flex items-center justify-center rounded-full"
									style="background-color: var(--surface-alpha-gray-6)"
								>
									<Spinner class="size-5" />
								</span>
							</button>
						</div>
						<div class="mb-[14px] flex gap-3">
							<FormControl v-model="fullName" class="min-w-0 flex-1" label="Full name" placeholder="Your name" size="md" variant="outline" />
							<FormControl v-model="role" class="min-w-0 flex-1" label="Role" placeholder="e.g. Sales, Support" size="md" variant="outline" />
						</div>
						<div class="flex gap-3">
							<FormControl :model-value="profile?.email || ''" class="min-w-0 flex-1" label="Email" size="md" variant="outline" disabled />
							<FormControl v-model="phone" class="min-w-0 flex-1" label="Phone number" placeholder="Your phone number" size="md" variant="outline" />
						</div>
						<div class="mt-5 flex justify-end">
							<Button
								label="Save"
								icon-left="lucide-check"
								:disabled="!profileChanged || !fullName.trim()"
								:loading="savingProfile"
								@click="saveProfile"
							/>
						</div>
					</template>

					<!-- Users -->
					<template v-else-if="tab === 'users'">
						<p v-if="teamError" class="text-base text-ink-gray-5">{{ teamError }}</p>
						<template v-else>
							<div
								class="grid w-full gap-[10px] border-b border-outline-gray-2 pb-2 text-xs font-medium text-ink-gray-5"
								style="grid-template-columns: minmax(120px, 1fr) minmax(140px, 1.4fr) 90px 40px"
							>
								<span>Name</span><span>Email</span><span>Role</span><span />
							</div>
							<div
								v-for="m in team"
								:key="m.name"
								class="grid items-center gap-[10px] border-b border-outline-gray-1 py-[10px]"
								style="grid-template-columns: minmax(120px, 1fr) minmax(140px, 1.4fr) 90px 40px"
							>
								<span class="flex min-w-0 items-center gap-1.5">
									<span class="truncate text-sm font-medium text-ink-gray-9">{{ m.full_name || m.user }}</span>
									<Badge v-if="m.is_admin" label="Admin" size="sm" theme="gray" variant="subtle" />
								</span>
								<span class="truncate text-sm text-ink-gray-5">{{ m.user }}</span>
								<span class="flex flex-wrap items-center gap-1.5">
									<Badge v-if="m.role" :label="m.role" size="sm" theme="gray" variant="subtle" />
								</span>
								<span class="flex items-center justify-end">
									<Dropdown v-if="amAdmin && m.user !== me" :options="memberOptions(m)" align="end">
										<Button icon="lucide-more-horizontal" size="sm" variant="ghost" />
									</Dropdown>
								</span>
							</div>
							<div class="mt-4 flex justify-end">
								<Button label="Add" icon-left="lucide-user-plus" variant="outline" :disabled="!amAdmin" @click="showAdd = true" />
							</div>
						</template>
					</template>

					<!-- Working hours -->
					<template v-else-if="tab === 'hours'">
						<span class="mb-1.5 block text-base text-ink-gray-7">Work days</span>
						<div class="mb-4 flex flex-wrap gap-1.5">
							<button
								v-for="d in WEEKDAYS"
								:key="d.key"
								type="button"
								class="h-8 rounded-lg px-3.5 text-base text-ink-gray-8 transition-colors"
								:class="workDays.includes(d.key) ? 'bg-surface-gray-2' : 'hover:bg-surface-gray-1'"
								@click="toggleDay(d.key)"
							>
								{{ d.label }}
							</button>
						</div>
						<div class="mb-4 flex gap-3">
							<FormControl v-model="workStart" class="min-w-0 flex-1" label="Starts" type="select" :options="TIMES" size="md" variant="outline" />
							<FormControl v-model="workEnd" class="min-w-0 flex-1" label="Ends" type="select" :options="TIMES" size="md" variant="outline" />
						</div>
						<FormControl v-model="afterHours" class="mb-1.5" label="Messaging after hours" type="select" :options="AFTER_HOURS" size="md" />
						<span class="block text-p-sm text-ink-gray-5">
							Choose what happens when you message outside your working hours. Silent messages are delivered but
							don't notify anyone; they'll see them when they're back.
						</span>
						<span v-if="hoursChanged && hoursError" class="mt-3 block text-p-sm text-ink-red-4">{{ hoursError }}</span>
						<div class="mt-5 flex justify-end">
							<Button
								label="Save"
								icon-left="lucide-check"
								:disabled="!hoursChanged || !!hoursError"
								:loading="savingHours"
								@click="saveHours"
							/>
						</div>
					</template>

					<!-- Requirements (customers) -->
					<template v-else-if="tab === 'requirements'">
						<div class="mb-[14px] flex gap-3">
							<FormControl :model-value="req.company_name" class="min-w-0 flex-1" label="Company Name" size="md" variant="outline" disabled />
							<FormControl v-model="req.country" class="min-w-0 flex-1" label="Country" size="md" variant="outline" />
						</div>
						<FormControl v-model="req.industry" class="mb-[14px]" label="Industry" type="select" :options="['', ...INDUSTRIES]" size="md" variant="outline" />
						<span class="mb-1.5 block text-base text-ink-gray-7">Apps of Interest</span>
						<div class="flex flex-wrap gap-x-5 gap-y-2">
							<Checkbox
								v-for="app in APPS"
								:key="app"
								:label="app"
								:model-value="req.apps.includes(app)"
								@update:model-value="toggleReq('apps', app)"
							/>
						</div>
						<div class="my-5 border-t border-outline-gray-1" />
						<div class="mb-[14px] flex gap-3">
							<FormControl v-model="req.looking_for" class="min-w-0 flex-1" label="What are you looking for?" type="select" :options="['', ...LOOKING_FOR]" size="md" variant="outline" />
							<FormControl v-model="req.company_size" class="min-w-0 flex-1" label="Company Size" type="select" :options="['', ...COMPANY_SIZES]" size="md" variant="outline" />
						</div>
						<div class="mb-[14px] flex gap-3">
							<FormControl v-model="req.current_situation" class="min-w-0 flex-1" label="Current Situation" type="select" :options="['', ...SITUATIONS]" size="md" variant="outline" />
							<FormControl v-model="req.timeline" class="min-w-0 flex-1" label="Timeline" type="select" :options="['', ...TIMELINES]" size="md" variant="outline" />
						</div>
						<div class="mb-[14px] flex gap-3">
							<FormControl v-model="req.delivery_preference" class="min-w-0 flex-1" label="Delivery Preference" type="select" :options="['', ...DELIVERY]" size="md" variant="outline" />
							<FormControl v-model="req.budget" class="min-w-0 flex-1" label="Budget" type="select" :options="['', ...BUDGETS]" size="md" variant="outline" />
						</div>
						<span class="mb-1.5 block text-base text-ink-gray-7">Special Requirements</span>
						<div class="flex flex-wrap gap-x-5 gap-y-2">
							<Checkbox
								v-for="item in SPECIAL"
								:key="item"
								:label="item"
								:model-value="req.special_requirements.includes(item)"
								@update:model-value="toggleReq('special_requirements', item)"
							/>
						</div>
						<div class="mt-5 flex justify-end">
							<Button label="Save" icon-left="lucide-check" :loading="savingReq" @click="saveRequirement" />
						</div>
					</template>

					<!-- CRM (partner admins) -->
					<template v-else-if="tab === 'crm'">
						<FormControl v-model="crm.site_url" class="mb-[14px]" label="Site URL" placeholder="https://crm.example.com" size="md" variant="outline" />
						<div class="mb-[14px] flex gap-3">
							<FormControl v-model="crm.api_key" class="min-w-0 flex-1" label="API Key" type="password" placeholder="API key" size="md" />
							<FormControl
								v-model="crm.api_secret"
								class="min-w-0 flex-1"
								label="API Secret"
								type="password"
								:placeholder="crmSaved?.api_secret_set ? '••••••••••••••••' : 'API secret'"
								size="md"
							/>
						</div>
						<FormControl v-model="crm.default_lead_status" class="mb-[14px]" label="Default lead status" placeholder="New" size="md" variant="outline" />
						<Checkbox v-model="crm.enabled" label="Create leads from new conversations" />
						<p v-if="crmError" class="mt-3 text-p-sm text-ink-red-6">{{ crmError }}</p>
						<div class="mt-5 flex justify-end">
							<Button label="Save" icon-left="lucide-check" :disabled="!crmChanged" :loading="crmSaving" @click="saveCrm" />
						</div>
					</template>
				</div>
			</div>

			<button
				type="button"
				class="absolute right-4 top-4 z-20 flex size-7 items-center justify-center rounded-[6px] hover:bg-surface-gray-2"
				aria-label="Close"
				@click="open = false"
			>
				<span class="lucide-x size-4 text-ink-gray-7" />
			</button>
		</div>
	</Dialog>

	<Dialog v-model="showAdd" title="Add a team member" size="sm">
		<template #default>
			<div class="flex flex-col gap-4">
				<FormControl v-model="newEmail" label="Email" type="email" placeholder="name@company.com" />
				<FormControl v-model="newRole" label="Role" type="text" placeholder="e.g. Sales, Support" />
			</div>
		</template>
		<template #actions>
			<div class="flex justify-end gap-2">
				<Button label="Cancel" @click="showAdd = false" />
				<Button label="Add" variant="solid" :loading="adding" :disabled="!newEmail.trim()" @click="addMember" />
			</div>
		</template>
	</Dialog>
</template>
