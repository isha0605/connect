<script setup>
// The partner's past projects on the Customers page: work done before Connect, each with the
// customer asked for a review (Review Request). Add one, send the request, remind once, or withdraw
// it. The rules (who may ask, whom, how often) are the server's; this mirrors them only to hide
// actions that would be refused.
import { computed, reactive, ref } from "vue"
import { Badge, Button, Dialog, Dropdown, FormControl, call, toast } from "frappe-ui"

const API = "connect.api.review_requests"
const REMIND_AFTER_DAYS = 3
const DAY_MS = 24 * 60 * 60 * 1000

// What each status means to the partner: a badge and a line under it.
const STATUSES = {
	Draft: { label: "Not sent", theme: "gray", note: () => "Saved, not sent yet" },
	Sent: { label: "Sent", theme: "blue", note: (r) => `Sent ${day(r.sent_on)} · link expires ${day(r.expires_on)}` },
	Opened: { label: "Opened", theme: "blue", note: (r) => `Opened · link expires ${day(r.expires_on)}` },
	Accepted: { label: "Confirmed", theme: "blue", note: () => "Confirmed working with you, review not written yet" },
	Reviewed: {
		label: "Reviewed",
		theme: "green",
		note: (r) => (r.is_review_hidden ? "Frappe hid this review from your profile" : "Review is on your profile"),
	},
	Declined: { label: "Declined", theme: "red", note: () => "Said they didn't work with you" },
	Expired: { label: "Expired", theme: "gray", note: () => "No answer before the link expired" },
	Withdrawn: { label: "Withdrawn", theme: "gray", note: () => "You withdrew the request" },
}
const WAITING = ["Sent", "Opened"]

const requests = ref([])
const loading = ref(true)
const loadError = ref("")

function day(value) {
	return value ? new Date(String(value).replace(" ", "T")).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : ""
}

async function load() {
	try {
		requests.value = await call(`${API}.list_review_requests`)
		loadError.value = ""
	} catch (error) {
		loadError.value =
			error?.exc_type === "PermissionError"
				? "Only your firm's owners and sales can ask customers for reviews."
				: "Couldn't load your past projects."
	} finally {
		loading.value = false
	}
}
load()

function canRemind(request) {
	if (!WAITING.includes(request.status) || request.reminded_on || !request.sent_on) return false
	return Date.now() - new Date(String(request.sent_on).replace(" ", "T")).getTime() >= REMIND_AFTER_DAYS * DAY_MS
}

function actionsFor(request) {
	return [
		{ label: "Send request", icon: "lucide-send", condition: () => request.status === "Draft", onClick: () => act("send", request, "Request sent") },
		{ label: "Send reminder", icon: "lucide-bell", condition: () => canRemind(request), onClick: () => act("remind", request, "Reminder sent") },
		{
			label: "View review",
			icon: "lucide-star",
			condition: () => request.status === "Reviewed" && !request.is_review_hidden,
			onClick: () => window.open(`/connect/partner-profile-redesign/${encodeURIComponent(request.partner)}`, "_blank"),
		},
		{
			label: "Withdraw",
			icon: "lucide-x",
			theme: "red",
			condition: () => request.status === "Draft" || WAITING.includes(request.status),
			onClick: () => (withdrawing.value = request),
		},
	]
}

const rows = computed(() =>
	requests.value.map((request) => {
		const status = STATUSES[request.status] || STATUSES.Draft
		return { ...request, statusLabel: status.label, statusTheme: status.theme, statusNote: status.note(request), actions: actionsFor(request) }
	}),
)
const hasActions = (row) => row.actions.some((action) => action.condition())

async function act(action, request, done) {
	try {
		await call(`${API}.${action}_review_request`, { name: request.name })
		toast.success(done)
		await load()
	} catch (error) {
		toast.error(error?.messages?.[0] || "That didn't work. Try again.")
	}
}

// ---- Withdraw, confirmed first: the customer's link stops working ----
const withdrawing = ref(null)
const withdrawBusy = ref(false)
async function withdraw() {
	withdrawBusy.value = true
	await act("withdraw", withdrawing.value, "Request withdrawn")
	withdrawBusy.value = false
	withdrawing.value = null
}

// ---- Add a past project ----
const adding = ref(false)
const saving = ref("")
const tried = ref(false)
const saveError = ref("")
const form = reactive({ project_title: "", project_summary: "", company_name: "", contact_name: "", contact_email: "" })
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const errors = computed(() => {
	if (!tried.value) return {}
	const found = {}
	if (!form.project_title.trim()) found.project_title = "Name the project"
	if (!form.company_name.trim()) found.company_name = "Enter the customer's company"
	if (!form.contact_name.trim()) found.contact_name = "Enter who to ask"
	if (!EMAIL.test(form.contact_email.trim())) found.contact_email = "Enter a valid email, like name@company.com"
	return found
})

function openAdd() {
	Object.keys(form).forEach((key) => (form[key] = ""))
	tried.value = false
	saveError.value = ""
	adding.value = true
}

async function save(send) {
	tried.value = true
	if (Object.keys(errors.value).length || saving.value) return
	saving.value = send ? "send" : "save"
	saveError.value = ""
	try {
		await call(`${API}.create_review_request`, { values: { ...form }, send: send ? 1 : 0 })
		adding.value = false
		toast.success(send ? `Review request sent to ${form.contact_email.trim()}` : "Past project saved")
		await load()
	} catch (error) {
		saveError.value = error?.messages?.[0] || "Couldn't save the project. Try again."
	} finally {
		saving.value = ""
	}
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col">
		<div class="flex shrink-0 flex-wrap items-center justify-between gap-2 px-5 py-3">
			<p class="text-p-base text-ink-gray-5">Projects you did before Connect, and the customers you asked for a review.</p>
			<Button v-if="!loadError" variant="solid" label="Add past project" @click="openAdd">
				<template #prefix><span class="lucide-plus size-4" /></template>
			</Button>
		</div>

		<div class="min-h-0 flex-1 overflow-y-auto px-5 pb-5">
			<p v-if="loading" class="py-16 text-center text-p-base text-ink-gray-5">Loading…</p>

			<div v-else-if="loadError || !rows.length" class="flex flex-col items-center gap-2 py-16 text-center">
				<div class="rounded-full bg-surface-gray-2 p-3"><span class="lucide-folder-clock block size-6 text-ink-gray-5" /></div>
				<p class="text-base font-medium text-ink-gray-7">{{ loadError || "No past projects yet" }}</p>
				<p v-if="!loadError" class="max-w-sm text-p-sm text-ink-gray-5">
					Add a project you did before Connect and ask the customer for a review. It shows on your profile as confirmed by the customer.
				</p>
				<Button v-if="!loadError" class="mt-2" label="Add past project" @click="openAdd" />
			</div>

			<div v-else role="table" aria-label="Past projects">
				<div role="row" class="mb-2 hidden grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1.2fr)_2rem] gap-4 rounded-4 bg-surface-gray-2 px-3 py-2 text-sm text-ink-gray-5 md:grid">
					<span role="columnheader">Project</span>
					<span role="columnheader">Contact</span>
					<span role="columnheader">Feedback</span>
					<span role="columnheader" class="sr-only">Actions</span>
				</div>
				<div
					v-for="row in rows"
					:key="row.name"
					role="row"
					class="grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-x-4 gap-y-1 border-b border-outline-gray-1 px-3 py-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1.2fr)_2rem]"
				>
					<div role="cell" class="min-w-0">
						<p class="truncate text-base font-medium text-ink-gray-8">{{ row.project_title }}</p>
						<p class="truncate text-sm text-ink-gray-5">{{ row.company_name }}</p>
					</div>
					<div role="cell" class="col-start-1 min-w-0 md:col-start-auto">
						<p class="truncate text-base text-ink-gray-7">{{ row.contact_name }}</p>
						<p class="truncate text-sm text-ink-gray-5">{{ row.contact_email }}</p>
					</div>
					<div role="cell" class="col-start-1 min-w-0 md:col-start-auto">
						<Badge :label="row.statusLabel" :theme="row.statusTheme" variant="subtle" />
						<p class="mt-1 truncate text-sm text-ink-gray-5">{{ row.statusNote }}</p>
					</div>
					<div role="cell" class="col-start-2 row-start-1 flex justify-end md:col-start-auto md:row-start-auto">
						<Dropdown v-if="hasActions(row)" :options="row.actions" placement="right">
							<Button variant="ghost" :aria-label="`Actions for ${row.project_title}`">
								<template #icon><span class="lucide-ellipsis size-4" /></template>
							</Button>
						</Dropdown>
					</div>
				</div>
			</div>
		</div>

		<Dialog v-model:open="adding" title="Add a past project" size="lg">
			<template #default>
				<form novalidate class="space-y-4" @submit.prevent="save(true)">
					<p class="text-p-base text-ink-gray-5">
						We email the contact a one-time link to confirm they worked with you and review you. Nothing shows on your profile until they do.
					</p>
					<FormControl v-model="form.project_title" label="Project" placeholder="ERPNext rollout for manufacturing" required :error="errors.project_title" />
					<FormControl
						v-model="form.project_summary"
						type="textarea"
						label="What you delivered"
						placeholder="Optional. The customer sees this when they open the link."
						:rows="3"
					/>
					<FormControl v-model="form.company_name" label="Customer's company" required :error="errors.company_name" />
					<div class="grid gap-4 sm:grid-cols-2">
						<FormControl v-model="form.contact_name" label="Contact name" required :error="errors.contact_name" />
						<FormControl
							v-model="form.contact_email"
							type="email"
							label="Contact email"
							placeholder="name@company.com"
							required
							:error="errors.contact_email"
						/>
					</div>
					<p v-if="saveError" class="text-p-sm text-ink-red-6">{{ saveError }}</p>
				</form>
			</template>
			<template #actions>
				<div class="flex flex-wrap justify-end gap-2">
					<Button label="Save" :loading="saving === 'save'" :disabled="Boolean(saving)" @click="save(false)" />
					<Button variant="solid" label="Save and request feedback" :loading="saving === 'send'" :disabled="Boolean(saving)" @click="save(true)">
						<template #prefix><span class="lucide-send size-4" /></template>
					</Button>
				</div>
			</template>
		</Dialog>

		<Dialog :open="Boolean(withdrawing)" title="Withdraw this request?" size="sm" @update:open="!$event && (withdrawing = null)">
			<template #default>
				<p class="text-p-base text-ink-gray-7">
					The link sent to {{ withdrawing?.contact_email }} stops working. You can ask them again later.
				</p>
			</template>
			<template #actions>
				<div class="flex justify-end gap-2">
					<Button label="Cancel" @click="withdrawing = null" />
					<Button variant="solid" theme="red" label="Withdraw" :loading="withdrawBusy" @click="withdraw" />
				</div>
			</template>
		</Dialog>
	</div>
</template>
