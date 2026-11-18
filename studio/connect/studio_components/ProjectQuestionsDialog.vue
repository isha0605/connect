<script setup>
// The project questions every entry point asks, in four steps. Without a partner the project is
// shared with every partner it matches; with one (Connect) it goes to that partner, as a new
// project or, given `project`, one of theirs with any answers it lacks filled in here. The
// number of employees and industries are the company's: filled in from it, and once set only
// its Owner or an Admin can change them. A guest answers first: Share keeps the answers in
// this tab and signs them up, and Home reopens this on the last step (?contact=1).
import { computed, getCurrentInstance, ref, watch } from "vue"
import { Button, Dialog, ErrorMessage, FormControl, FormLabel, MultiSelect, Radio, RadioGroup, call, toast } from "frappe-ui"
import {
	BUDGET_OPTIONS,
	EMPLOYEE_OPTIONS,
	GO_LIVE_OPTIONS,
	INDUSTRY_OPTIONS,
	OPERATION_OPTIONS,
	PROBLEM_OPTIONS,
	SYSTEM_OPTIONS,
} from "@app/utils/recommendation"
import {
	MISSING_ANSWERS,
	PROJECT_QUESTION_STEPS,
	WORK_CHOICES,
	missingAnswers,
	usesOtherSystems as needsSystems,
	workChoiceOf,
	workModesOf,
} from "@app/utils/projectDialog"
import { goToSignIn } from "@app/utils/signIn"
import AppsSelect from "./AppsSelect.vue"

const props = defineProps({
	// Whether the dialog is open (v-model).
	modelValue: { type: Boolean, default: false },
	// { name, partner_name } to send the project to that partner; null to share it with all.
	partner: { type: Object, default: null },
	// An existing project (get_project's shape) to send to `partner` once it has every answer.
	project: { type: Object, default: null },
})
const emit = defineEmits(["update:modelValue"])

const router = getCurrentInstance()?.appContext.config.globalProperties.$router

const STEPS = PROJECT_QUESTION_STEPS
const LIST_ANSWERS = ["regions", "industries", "apps", "work_modes", "systems", "problems"]
// A guest's answers, kept in this tab across signing up: the sign-up page reloads the app.
const KEPT_ANSWERS = "connect.projectQuestions.answers"
const AFTER_SIGN_UP = "/connect/home?contact=1"

const step = ref(1)
const answers = ref(blankAnswers())
const errors = ref({})
const sendError = ref("")
const sending = ref(false)
const canChangeFacts = ref(true)
const isGuest = ref(false)
const regionOptions = ref([])

const partnerName = computed(() => props.partner?.partner_name || props.partner?.name || "")
const title = computed(() => (partnerName.value ? `New project for ${partnerName.value}` : "New project"))
const sendLabel = computed(() => (partnerName.value ? `Send to ${partnerName.value}` : "Share requirements"))
const usesOtherSystems = computed(() => needsSystems(answers.value.operations))
const workChoice = computed({
	get: () => workChoiceOf(answers.value.work_modes),
	set: (choice) => (answers.value.work_modes = workModesOf(choice)),
})
const descriptionNote = computed(() =>
	partnerName.value
		? `${partnerName.value} quotes from this, and sees your company details.`
		: "Partners who match quote from this, without seeing your company name.",
)
const factsNote = computed(() =>
	canChangeFacts.value ? "" : "Only your company's Owner or an Admin can change this.",
)

// Reset on open, not on close, so the answers don't vanish while the dialog fades out.
watch(
	() => props.modelValue,
	(open) => {
		if (!open) return
		step.value = 1
		errors.value = {}
		sendError.value = ""
		answers.value = { ...blankAnswers(), ...projectAnswers(props.project) }
		if (!props.project && restoreKept()) step.value = STEPS.length
		loadOptions()
		loadCompany()
	},
	{ immediate: true },
)

function blankAnswers() {
	return {
		regions: [], company_size: "", industries: [], apps: [], go_live: "", work_modes: [],
		operations: "", systems: [], problems: [], budget: "", description: "",
	}
}

function projectAnswers(project) {
	if (!project) return {}
	const given = Object.keys(MISSING_ANSWERS).filter((field) => project[field] !== undefined)
	return Object.fromEntries(given.map((field) => [field, project[field] ?? (LIST_ANSWERS.includes(field) ? [] : "")]))
}

function loadOptions() {
	if (regionOptions.value.length) return
	call("connect.api.partner.list_partner_countries")
		.then((countries) => (regionOptions.value = (countries || []).map((c) => ({ label: c, value: c }))))
		.catch(() => {})
}

// Who is answering: a guest, or a customer whose company facts fill the first step.
function loadCompany() {
	call("connect.api.account.get_my_context")
		.then((me) => {
			isGuest.value = !me?.user || me.user === "Guest"
			const company = me?.customer
			if (!company) return
			const factsSet = !!(company.company_size && company.industries?.length)
			canChangeFacts.value = company.is_admin || !factsSet
			answers.value.company_size = answers.value.company_size || company.company_size || ""
			if (!answers.value.industries.length) answers.value.industries = company.industries || []
		})
		.catch(() => {})
}

function keepAnswers() {
	try {
		window.sessionStorage.setItem(KEPT_ANSWERS, JSON.stringify(answers.value))
	} catch {
		// Without storage they answer again after signing up.
	}
}

function restoreKept() {
	let kept = null
	try {
		kept = JSON.parse(window.sessionStorage.getItem(KEPT_ANSWERS) || "null")
	} catch {
		kept = null
	}
	if (kept) answers.value = { ...blankAnswers(), ...kept }
	return !!kept
}

function forgetKept() {
	try {
		window.sessionStorage.removeItem(KEPT_ANSWERS)
	} catch {
		// Nothing kept, nothing to clear.
	}
}

function missingIn(fields) {
	return missingAnswers(answers.value, fields)
}

function next() {
	errors.value = missingIn(STEPS[step.value - 1])
	if (Object.keys(errors.value).length) return
	step.value = Math.min(step.value + 1, STEPS.length)
}

function back() {
	errors.value = {}
	step.value = Math.max(step.value - 1, 1)
}

function payload() {
	const given = { ...answers.value, description: answers.value.description.trim() }
	// a spreadsheet shop's earlier pick isn't a system they use
	if (!usesOtherSystems.value) given.systems = []
	return JSON.stringify(given)
}

function send() {
	if (sending.value) return
	errors.value = missingIn(STEPS[step.value - 1])
	if (Object.keys(errors.value).length) return
	if (isGuest.value) {
		keepAnswers()
		goToSignIn({ screen: "signup", next: AFTER_SIGN_UP })
		return
	}

	sending.value = true
	sendError.value = ""
	const request = props.partner
		? call("connect.api.projects.start_project_with_partner", {
				partner: props.partner.name,
				project: props.project?.name,
				answers: payload(),
			})
		: call("connect.api.projects.share_requirements", { answers: payload() })
	request
		.then((result) => {
			forgetKept()
			emit("update:modelValue", false)
			if (props.partner) {
				router?.push({ path: "/messaging", query: { thread: result.thread } })
				return
			}
			const count = result.shared_count || 0
			toast.success(`Sent to ${count} partner${count === 1 ? "" : "s"}. Their quotes arrive here and in Messages.`)
			router?.push({ path: "/custom-implementation", query: { project: result.name } })
		})
		.catch((error) => {
			sendError.value = error?.messages?.[0] || "Couldn't send your requirements. Try again."
		})
		.finally(() => {
			sending.value = false
		})
}
</script>

<template>
	<Dialog :open="modelValue" size="md" :title="title" @update:open="!$event && emit('update:modelValue', false)">
		<template #default>
			<form class="-mt-3 flex w-full flex-col" novalidate @submit.prevent="step < STEPS.length ? next() : send()">
				<div class="flex w-full gap-1" aria-hidden="true">
					<div
						v-for="n in STEPS.length"
						:key="n"
						class="h-1 flex-1 rounded-sm"
						:style="{ backgroundColor: n <= step ? 'var(--ink-gray-8)' : 'var(--surface-gray-2)' }"
					/>
				</div>

				<div v-if="step === 1" class="mt-6 flex flex-col gap-4">
					<MultiSelect
						v-model="answers.regions"
						label="Which regions should your partners be from?"
						:options="regionOptions"
						placeholder="Select"
						required
						:error="errors.regions"
					/>
					<FormControl
						v-model="answers.company_size"
						type="select"
						label="Number of employees"
						:options="EMPLOYEE_OPTIONS"
						placeholder="Select"
						required
						:disabled="!canChangeFacts"
						:description="factsNote"
						:error="errors.company_size"
					/>
					<MultiSelect
						v-model="answers.industries"
						label="Relevant industry"
						:options="INDUSTRY_OPTIONS"
						placeholder="Select"
						required
						:disabled="!canChangeFacts"
						:description="factsNote"
						:error="errors.industries"
					/>
				</div>

				<div v-else-if="step === 2" class="mt-6 flex flex-col gap-4">
					<AppsSelect v-model="answers.apps" required :error="errors.apps" />
					<FormControl
						v-model="answers.go_live"
						type="select"
						label="When do you need it live?"
						:options="GO_LIVE_OPTIONS"
						placeholder="Select"
						required
						:error="errors.go_live"
					/>
					<FormControl
						v-model="workChoice"
						type="select"
						label="How do you want to work?"
						:options="WORK_CHOICES"
						placeholder="Select"
						required
						:error="errors.work_modes"
					/>
				</div>

				<div v-else-if="step === 3" class="mt-[21px] flex flex-col">
					<div id="operations-question">
						<FormLabel label="How would you describe your operations today?" required />
					</div>
					<RadioGroup v-model="answers.operations" class="mt-1 w-full" size="md" padded aria-labelledby="operations-question">
						<Radio
							v-for="option in OPERATION_OPTIONS"
							:key="option.value"
							class="-ml-3 min-h-8 px-3 py-[5.5px]"
							:label="option.label"
							:value="option.value"
						/>
					</RadioGroup>
					<ErrorMessage v-if="errors.operations" class="mt-1" :message="errors.operations" />
					<MultiSelect
						v-if="usesOtherSystems"
						v-model="answers.systems"
						class="mt-5"
						label="Which systems do you use?"
						:options="SYSTEM_OPTIONS"
						placeholder="Select"
						required
						:error="errors.systems"
					/>
					<MultiSelect
						v-model="answers.problems"
						class="mt-5"
						label="What are you trying to solve?"
						:options="PROBLEM_OPTIONS"
						placeholder="Select"
						required
						:error="errors.problems"
					/>
				</div>

				<div v-else class="mt-6 flex flex-col gap-4">
					<FormControl
						v-model="answers.budget"
						type="select"
						label="Your budget"
						:options="BUDGET_OPTIONS"
						placeholder="Select a range"
						required
						:error="errors.budget"
					/>
					<FormControl
						v-model="answers.description"
						type="textarea"
						label="What do you need?"
						placeholder="What do you make or sell, who are your customers, how does it run today, what keeps going wrong, and what must it connect to or prove?"
						:rows="6"
						required
						:description="descriptionNote"
						:error="errors.description"
					/>
					<ErrorMessage v-if="sendError" :message="sendError" />
				</div>

				<div class="mt-8 flex w-full justify-end gap-2">
					<Button v-if="step > 1" variant="subtle" size="sm" label="Back" icon-left="lucide-chevron-left" @click="back" />
					<Button v-if="step < STEPS.length" variant="solid" size="sm" label="Continue" type="submit" />
					<Button v-else variant="solid" size="sm" :label="sendLabel" icon-left="lucide-send" type="submit" :loading="sending" />
				</div>
			</form>
		</template>
	</Dialog>
</template>
