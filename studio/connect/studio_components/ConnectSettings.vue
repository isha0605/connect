<script setup>
// Settings (Profile, Users, Working hours, a customer's Company details and a partner admin's CRM
// connection) for every page with the shared sidebar. The
// sidebar's logo menu opens it with a "connect:open-settings" window event, so pages need no
// script of their own for it. Same server calls as Messaging's own settings.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import {
	Avatar,
	Badge,
	Button,
	Checkbox,
	Dialog,
	Dropdown,
	FormControl,
	Spinner,
	TextInput,
	Tooltip,
	call,
	dialog,
	toast,
	useFileUpload,
} from "frappe-ui"
import { List, ListCell, ListRow, ListRows } from "frappe-ui/list"
import { COUNTRY_OPTIONS, EMPLOYEE_OPTIONS, INDUSTRY_OPTIONS, SYSTEM_OPTIONS } from "@app/utils/recommendation"

const open = ref(false)
const tab = ref("profile")

// On phones the tabs scroll sideways, so bring the active one into view
const tabButtons = {}
watch([tab, open], () => {
	nextTick(() => tabButtons[tab.value]?.scrollIntoView({ block: "nearest", inline: "nearest" }))
})

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
		isPartner.value = !!context?.partner
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

// ---- Users on a partner firm: Pragati's panel, after Frappe CRM's Settings → Users ----
// One access level each, as a menu that saves on pick; the last owner's is locked, and Remove
// sits in the ⋯ menu. Only owners change anything.
const isPartner = ref(false)
const ACCESS_LEVELS = [
	{ key: "Owner", icon: "lucide-shield", description: "Everything, including the team, audits, link requests and settings" },
	{ key: "Sales", icon: "lucide-briefcase", description: "Leads, quotes and customers" },
	{ key: "Finance", icon: "lucide-receipt", description: "Billing, Contributions and customer invoices" },
	{ key: "Member", icon: "lucide-user", description: "View-only: standing, team, profile and resources" },
]
const ACCESS_OPTIONS = ACCESS_LEVELS.map((level) => ({ label: level.key, value: level.key }))
const levelOf = (member) => ACCESS_LEVELS.find((level) => level.key === member.access_level) || ACCESS_LEVELS[3]
const memberName = (member) => member.full_name || member.user
const ownerCount = computed(() => team.value.filter((m) => m.access_level === "Owner").length)
const isLastOwner = (member) => member.access_level === "Owner" && ownerCount.value === 1

// Frappe CRM shows search only once the list is long enough to need it.
const teamQuery = ref("")
const shownTeam = computed(() => {
	const query = teamQuery.value.trim().toLowerCase()
	return team.value.filter((m) => !query || memberName(m).toLowerCase().includes(query) || m.user.toLowerCase().includes(query))
})

function accessOptions(member) {
	return ACCESS_LEVELS.map((level) => ({
		label: level.key,
		icon: level.icon,
		description: level.description,
		selected: member.access_level === level.key,
		onClick: () => setAccess(member, level.key),
	}))
}

async function setAccess(member, level) {
	if (member.access_level === level) return
	try {
		await call("connect.api.account.set_team_member_access", { member: member.name, access_level: level })
		await loadTeam()
		toast.success(`${memberName(member)} has been granted ${level} access`)
	} catch (e) {
		toast.error(errorText(e, "Could not change their access"))
	}
}

// With CRM sync on, someone without a CRM user can be looked up again once they're added there.
const partnerMemberOptions = (member) => [
	member.in_crm === false && { label: "Match with CRM", icon: "lucide-refresh-cw", onClick: () => matchWithCrm(member) },
	{ label: "Remove", icon: "lucide-trash-2", theme: "red", onClick: () => confirmRemove(member) },
].filter(Boolean)

async function matchWithCrm(member) {
	try {
		const found = await call("connect.api.partner.match_my_member_with_crm", { member: member.name })
		await loadTeam()
		if (found) toast.success(`${memberName(member)} is matched with your CRM`)
		else toast.error(`${memberName(member)} isn't on your CRM. Add them there with ${member.user}, then try again.`)
	} catch (e) {
		toast.error(errorText(e, "Couldn't match them with your CRM"))
	}
}

function confirmRemove(member) {
	if (isLastOwner(member)) return toast.error("Make someone else owner first")
	dialog.danger({
		title: `Remove ${memberName(member)}?`,
		message: "They lose access to your firm in Connect. You can invite them again any time.",
		confirmLabel: "Remove",
		onConfirm: async ({ close }) => {
			await call("connect.api.account.remove_team_member", { member: member.name })
			close()
			await loadTeam()
			toast.success(`Removed ${memberName(member)} from the team`)
		},
	})
}

const inviteOpen = ref(false)
const invite = ref({ name: "", email: "", access: "Member" })
const inviteErrors = ref({})
const inviting = ref(false)

function startInvite() {
	invite.value = { name: "", email: "", access: "Member" }
	inviteErrors.value = {}
	inviteOpen.value = true
}

async function sendInvite() {
	const errors = {}
	if (!invite.value.name.trim()) errors.name = "Enter their name"
	if (!/^\S+@\S+\.\S+$/.test(invite.value.email.trim())) errors.email = "Enter a valid email, like name@company.com"
	inviteErrors.value = errors
	if (Object.keys(errors).length || inviting.value) return

	inviting.value = true
	try {
		await call("connect.api.account.add_team_member", {
			email: invite.value.email.trim(),
			full_name: invite.value.name.trim(),
			access_level: invite.value.access,
		})
		inviteOpen.value = false
		await loadTeam()
		toast.success(`Invite sent to ${invite.value.email.trim()}`)
	} catch (e) {
		inviteErrors.value = { email: errorText(e, "Could not send the invite") }
	} finally {
		inviting.value = false
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

// ---- Company details: the customer's saved Requirement, asked with the same questions and options
// as the new project and Starter Pack forms. What one project needs is asked on that project.
const isCustomer = ref(false)
const company = ref(blankCompany())
const savingCompany = ref(false)

function blankCompany() {
	return { company_name: "", country: "", employees: "", industry: "", system: "", notes: "" }
}

// A value saved before these lists (e.g. industry "Manufacturing") stays selected until it's changed.
function withSaved(options, value) {
	const grouped = !!options[0]?.group
	const known = (grouped ? options.flatMap((group) => group.options) : options).some((o) => o.value === value)
	if (!value || known) return options
	const saved = { label: value, value }
	return grouped ? [{ key: "saved", group: "Saved", options: [saved] }, ...options] : [saved, ...options]
}
const countryOptions = computed(() => withSaved(COUNTRY_OPTIONS, company.value.country))
const employeeOptions = computed(() => withSaved(EMPLOYEE_OPTIONS, company.value.employees))
const industryOptions = computed(() => withSaved(INDUSTRY_OPTIONS, company.value.industry))
const systemOptions = computed(() => withSaved(SYSTEM_OPTIONS, company.value.system))

async function loadCompany() {
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
	company.value = {
		company_name: (saved && saved.company_name) || context?.customer?.customer_name || "",
		country: saved?.country || "",
		employees: saved?.employees || "",
		industry: saved?.industry || "",
		system: saved?.current_situation || "",
		notes: saved?.additional_notes || "",
	}
}

async function saveCompany() {
	if (savingCompany.value) return
	savingCompany.value = true
	try {
		const c = company.value
		// Only these fields: the rest of the Requirement (budget, timeline...) stays as it was.
		await call("connect.api.customer.save_customer_requirement", {
			country: c.country,
			industry: c.industry,
			company_size: c.employees,
			current_situation: c.system,
			additional_notes: c.notes.trim(),
		})
		toast.success("Your company details have been saved.")
	} catch (e) {
		toast.error(errorText(e, "Could not save. Please try again."))
	} finally {
		savingCompany.value = false
	}
}

// ---- CRM: a partner admin's Frappe CRM connection (Partner CRM Settings) ----
// The first message in a thread opens a Lead on the partner's CRM and later ones attach to it.
const isPartnerAdmin = ref(false)
const crm = ref({ site_url: "", api_key: "", api_secret: "", default_lead_status: "", enabled: false })
const crmSaved = ref(null)
const crmSaving = ref(false)
const crmError = ref("")
// Each status on the partner's CRM and the Connect stage it becomes, read from their CRM on save.
const crmMap = ref([])

function applyCrm(s) {
	crmSaved.value = s || {}
	crm.value = {
		site_url: crmSaved.value.site_url || "",
		api_key: crmSaved.value.api_key || "",
		api_secret: "",
		default_lead_status: crmSaved.value.default_lead_status || "",
		enabled: !!crmSaved.value.enabled,
	}
	crmMap.value = (crmSaved.value.status_map || []).map((row) => ({ ...row }))
}

// An empty stage leaves that status out of the sync, both ways.
const crmStageOptions = computed(() => [
	{ label: "Don't sync", value: "" },
	...(crmSaved.value?.stages || []).map((stage) => ({ label: stage, value: stage })),
])
const crmStatusGroups = computed(() =>
	[
		{ key: "CRM Lead", title: "Lead statuses" },
		{ key: "CRM Deal", title: "Deal statuses" },
	]
		.map((group) => ({ ...group, rows: crmMap.value.filter((row) => row.crm_doctype === group.key) }))
		.filter((group) => group.rows.length),
)
const crmMapChanged = computed(() => {
	const saved = crmSaved.value?.status_map || []
	return crmMap.value.some((row, index) => row.stage !== (saved[index]?.stage || ""))
})

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
		!!c.api_secret ||
		crmMapChanged.value ||
		// Connected before stage sync: saving reads the CRM's statuses for the first time.
		(!!s.api_secret_set && !(s.status_map || []).length)
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
				status_map: JSON.stringify(crmMap.value),
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
		isCustomer.value && { value: "company", label: "Company details", icon: "lucide-building-2" },
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
	company: {
		title: "Company details",
		description: "Tell partners about your company. Each project asks what that project needs.",
	},
	crm: { title: "CRM", description: "Connect your Frappe CRM account" },
}
// A partner's Users header is Pragati's: the title alone, with Invite beside it.
const heading = computed(() =>
	tab.value === "users" && isPartner.value ? { title: "Users", description: "" } : HEADINGS[tab.value] || HEADINGS.profile,
)

// ---- Opening ----
function openSettings(event) {
	tab.value = (event && event.detail && event.detail.tab) || "profile"
	loadProfile()
	loadTeam()
	loadHours()
	loadCompany()
	open.value = true
}

onMounted(() => window.addEventListener("connect:open-settings", openSettings))
onBeforeUnmount(() => window.removeEventListener("connect:open-settings", openSettings))
</script>

<template>
	<Dialog v-model="open" size="4xl" bare>
		<!-- Opening focuses the panel itself, so no menu item looks selected; Tab moves into the menu -->
		<div class="relative flex flex-col outline-none sm:flex-row" style="height: min(620px, 80vh)" tabindex="0" autofocus>
			<!-- left nav; on phones a tab strip that scrolls sideways -->
			<div
				class="flex shrink-0 border-b border-outline-gray-2 sm:w-[220px] sm:border-b-0 sm:border-r"
				style="background-color: var(--surface-sidebar)"
			>
				<div
					class="flex min-w-0 flex-1 flex-row gap-[2px] overflow-x-auto p-2 sm:flex-col sm:overflow-x-visible"
					style="scrollbar-width: none"
				>
					<div class="my-[3px] hidden h-[30px] items-center px-2 py-[7px] text-xs font-medium text-ink-gray-5 sm:flex">Settings</div>
					<button
						v-for="item in sections"
						:key="item.value"
						:ref="(element) => (tabButtons[item.value] = element)"
						type="button"
						class="flex h-7 shrink-0 items-center gap-2 rounded-[6px] px-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
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
			</div>

			<!-- right pane -->
			<div class="flex min-h-0 flex-1 flex-col">
				<div class="flex shrink-0 items-start justify-between gap-4 px-4 pt-5 sm:px-10 sm:pt-10">
					<div class="flex min-w-0 flex-col gap-1">
						<h2 class="text-lg font-semibold text-ink-gray-8">{{ heading.title }}</h2>
						<p v-if="heading.description" class="text-base text-ink-gray-6">{{ heading.description }}</p>
					</div>
					<Button
						v-if="tab === 'users' && isPartner && amAdmin"
						class="shrink-0"
						variant="solid"
						label="Invite"
						icon-left="lucide-plus"
						@click="startInvite"
					/>
					<Badge
						v-if="tab === 'crm'"
						class="mt-[2px] shrink-0"
						:label="crmStatus.label"
						:theme="crmStatus.theme"
						variant="subtle"
						size="md"
					/>
				</div>

				<div class="min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-5 sm:px-10 sm:pb-10" style="scrollbar-width: thin; scrollbar-color: var(--outline-gray-3) transparent">
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
						<div class="mb-[14px] flex flex-col gap-3 sm:flex-row">
							<FormControl v-model="fullName" class="min-w-0 flex-1" label="Full name" placeholder="Your name" size="md" variant="outline" />
							<FormControl v-model="role" class="min-w-0 flex-1" label="Role" placeholder="e.g. Sales, Support" size="md" variant="outline" />
						</div>
						<div class="flex flex-col gap-3 sm:flex-row">
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
						<!-- A partner firm: Pragati's rows, one access level each -->
						<template v-else-if="isPartner">
							<TextInput v-if="team.length > 10" v-model="teamQuery" type="search" placeholder="Search users" class="mb-3">
								<template #prefix><span class="lucide-search size-4 text-ink-gray-5" aria-hidden="true" /></template>
							</TextInput>
							<List :columns="['minmax(0,1fr)', 'auto', 'auto']" :row-height="56">
								<ListRows :items="shownTeam" row-key="name" v-slot="{ item }">
									<ListRow>
										<ListCell>
											<div class="flex min-w-0 items-center gap-3">
												<Avatar :label="memberName(item)" :image="item.user_image" size="xl" class="shrink-0" />
												<div class="min-w-0">
													<div class="flex items-center gap-2">
														<span class="truncate text-p-base text-ink-gray-8">{{ memberName(item) }}</span>
														<Badge v-if="item.is_invited" theme="amber" variant="subtle" label="Invited" />
														<Badge v-if="item.in_crm === false" theme="gray" variant="subtle" label="Not in CRM" />
													</div>
													<div class="truncate text-p-sm text-ink-gray-5">{{ item.user }}</div>
												</div>
											</div>
										</ListCell>

										<!-- Access: a menu for owners, locked for the last owner, text for everyone else -->
										<ListCell class="justify-end">
											<template v-if="amAdmin">
												<Tooltip v-if="isLastOwner(item)" text="A firm needs at least one owner">
													<Button :label="levelOf(item).key" :icon-left="levelOf(item).icon" />
												</Tooltip>
												<Dropdown
													v-else
													:options="accessOptions(item)"
													:button="{ label: levelOf(item).key, iconLeft: levelOf(item).icon, iconRight: 'lucide-chevron-down' }"
													align="end"
												/>
											</template>
											<span v-else class="inline-flex items-center gap-1.5 text-base text-ink-gray-7">
												<span :class="[levelOf(item).icon, 'size-4 text-ink-gray-5']" aria-hidden="true" />
												{{ levelOf(item).key }}
											</span>
										</ListCell>

										<ListCell class="justify-end">
											<Dropdown
												v-if="amAdmin"
												:options="partnerMemberOptions(item)"
												:button="{ icon: 'lucide-more-horizontal', variant: 'ghost', 'aria-label': `More for ${memberName(item)}` }"
												align="end"
											/>
										</ListCell>
									</ListRow>
								</ListRows>
							</List>
						</template>
						<template v-else>
							<div
								class="hidden w-full gap-[10px] border-b border-outline-gray-2 pb-2 text-xs font-medium text-ink-gray-5 sm:grid sm:grid-cols-[minmax(120px,1fr)_minmax(140px,1.4fr)_90px_40px]"
							>
								<span>Name</span><span>Email</span><span>Role</span><span />
							</div>
							<!-- Phones: name, email and role stack on the left with the menu on the right -->
							<div
								v-for="m in team"
								:key="m.name"
								class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-[10px] gap-y-1 border-b border-outline-gray-1 py-[10px] sm:grid-cols-[minmax(120px,1fr)_minmax(140px,1.4fr)_90px_40px] sm:gap-y-[10px]"
							>
								<span class="col-start-1 row-start-1 flex min-w-0 items-center gap-1.5 sm:col-auto sm:row-auto">
									<span class="truncate text-sm font-medium text-ink-gray-9">{{ m.full_name || m.user }}</span>
									<Badge v-if="m.is_admin" label="Admin" size="sm" theme="gray" variant="subtle" />
								</span>
								<span class="col-start-1 row-start-2 truncate text-sm text-ink-gray-5 sm:col-auto sm:row-auto">{{ m.user }}</span>
								<span class="col-start-1 row-start-3 flex flex-wrap items-center gap-1.5 empty:hidden sm:col-auto sm:row-auto sm:empty:flex">
									<Badge v-if="m.role" :label="m.role" size="sm" theme="gray" variant="subtle" />
								</span>
								<span class="col-start-2 row-start-1 row-end-3 flex items-center justify-end sm:col-auto sm:row-auto">
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

					<!-- Company details (customers) -->
					<template v-else-if="tab === 'company'">
						<div class="mb-[14px] flex flex-col gap-3 sm:flex-row">
							<FormControl :model-value="company.company_name" class="min-w-0 flex-1" label="Company name" size="md" variant="outline" disabled />
							<FormControl v-model="company.country" class="min-w-0 flex-1" label="Country" type="combobox" :options="countryOptions" placeholder="Select" size="md" variant="outline" />
						</div>
						<div class="mb-[14px] flex flex-col gap-3 sm:flex-row">
							<FormControl v-model="company.employees" class="min-w-0 flex-1" label="Number of employees" type="select" :options="employeeOptions" placeholder="Select" size="md" variant="outline" />
							<FormControl v-model="company.industry" class="min-w-0 flex-1" label="Industry" type="combobox" :options="industryOptions" placeholder="Select" size="md" variant="outline" />
						</div>
						<FormControl v-model="company.system" class="mb-[14px]" label="What do you use today?" type="select" :options="systemOptions" placeholder="Select" size="md" variant="outline" />
						<FormControl v-model="company.notes" label="Anything partners should know?" type="textarea" :rows="3" placeholder="For example, GST invoicing or tracking stock across two shops" size="md" variant="outline" />
						<div class="mt-5 flex justify-end">
							<Button label="Save" icon-left="lucide-check" :loading="savingCompany" @click="saveCompany" />
						</div>
					</template>

					<!-- CRM (partner admins) -->
					<template v-else-if="tab === 'crm'">
						<FormControl v-model="crm.site_url" class="mb-[14px]" label="Site URL" placeholder="https://crm.example.com" size="md" variant="outline" />
						<div class="mb-[14px] flex flex-col gap-3 sm:flex-row">
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
						<!-- Stage sync: Pragati's CRM sync panel, one list per CRM record -->
						<section class="mt-6 border-t border-outline-gray-1 pt-5" aria-labelledby="crm-stages-title">
							<h3 id="crm-stages-title" class="text-base font-medium text-ink-gray-8">Stages</h3>
							<p class="mt-1 text-p-sm text-ink-gray-5">
								Your CRM's statuses, and the Connect stage each one becomes. A lead becomes a deal on your CRM when its
								stage matches only a deal status.
							</p>
							<p v-if="!crmStatusGroups.length" class="mt-3 text-p-sm text-ink-gray-5">
								Save to load your CRM's statuses here.
							</p>
							<div v-for="group in crmStatusGroups" :key="group.key" class="mt-4">
								<p class="mb-1 text-sm font-medium text-ink-gray-5">{{ group.title }}</p>
								<div
									v-for="row in group.rows"
									:key="row.crm_status"
									class="flex flex-col gap-1.5 py-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
								>
									<label :for="`crm-stage-${group.key}-${row.crm_status}`" class="text-base text-ink-gray-8">{{ row.crm_status }}</label>
									<FormControl
										:id="`crm-stage-${group.key}-${row.crm_status}`"
										v-model="row.stage"
										class="w-full sm:w-56"
										type="select"
										:options="crmStageOptions"
										:aria-label="`Connect stage for ${row.crm_status}`"
									/>
								</div>
							</div>
						</section>
						<p v-if="crmError" class="mt-3 text-p-sm text-ink-red-6">{{ crmError }}</p>
						<div class="mt-5 flex justify-end">
							<Button label="Save" icon-left="lucide-check" :disabled="!crmChanged" :loading="crmSaving" @click="saveCrm" />
						</div>
					</template>
				</div>
			</div>
		</div>
	</Dialog>

	<Dialog v-model="inviteOpen" title="Invite">
		<template #default>
			<form class="space-y-4" novalidate @submit.prevent="sendInvite">
				<FormControl v-model="invite.name" label="Name" required :error="inviteErrors.name" />
				<FormControl v-model="invite.email" type="email" label="Email" placeholder="name@company.com" required :error="inviteErrors.email" />
				<FormControl v-model="invite.access" type="select" label="Role" :options="ACCESS_OPTIONS" />
				<div class="flex justify-end gap-2 pt-2">
					<Button label="Cancel" @click="inviteOpen = false" />
					<Button variant="solid" type="submit" label="Send invite" :loading="inviting" />
				</div>
			</form>
		</template>
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
