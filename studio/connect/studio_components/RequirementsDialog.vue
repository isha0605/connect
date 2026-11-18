<script setup>
// "Your requirements" on a sent project: what partners got, read back, and Edit to change it.
// Editing happens in place (Pragati's BriefDetailsDialog); Send goes to every partner who has
// the requirements, and a quote made before then waits for its partner to confirm or redo it.
import { computed, nextTick, ref, watch } from "vue"
import { Alert, Button, Dialog, ErrorMessage, FormControl, MultiSelect, ScrollArea, call, dialog, toast } from "frappe-ui"
import {
	BUDGET_OPTIONS,
	EMPLOYEE_OPTIONS,
	GO_LIVE_OPTIONS,
	OPERATION_OPTIONS,
	PROBLEM_OPTIONS,
	SYSTEM_OPTIONS,
	goLiveCriterion,
} from "@app/utils/recommendation"
import { blankCriteria, orList, workCriterion } from "@app/utils/partnerCriteria"
import {
	MISSING_ANSWERS,
	WORK_CHOICES,
	missingAnswers,
	usesOtherSystems,
	workChoiceOf,
	workModesOf,
} from "@app/utils/projectDialog"
import AppsSelect from "./AppsSelect.vue"

const props = defineProps({
	// Whether the dialog is open (v-model).
	modelValue: { type: Boolean, default: false },
	// The project, as get_project returns it.
	project: { type: Object, default: null },
})
const emit = defineEmits(["update:modelValue", "updated"])

// The company's size and industries change in Settings, not here.
const EDITED = Object.keys(MISSING_ANSWERS).filter((field) => !["company_size", "industries"].includes(field))

const editing = ref(false)
const form = ref({})
let initial = ""
const tried = ref(false)
const sending = ref(false)
const sendError = ref("")
const regionOptions = ref([])
const cityOptions = ref([])
const tierOptions = ref([])
const descriptionField = ref(null)

const criteria = computed(() => ({ ...blankCriteria(), ...(props.project?.criteria || {}) }))
const canEdit = computed(() => props.project?.status === "Shared")
const lockNote = computed(() => {
	const partner = props.project?.hired?.partner_name || "your partner"
	if (props.project?.status === "Hiring") return `Waiting on ${partner} to answer your hire request`
	if (["Hired", "Completed"].includes(props.project?.status)) return `Hired. Changes go through ${partner} now`
	return ""
})
const editActions = computed(() =>
	canEdit.value ? [{ label: "Edit", iconLeft: "lucide-pencil", onClick: startEditing }] : [],
)
const dirty = computed(() => editing.value && JSON.stringify(form.value) !== initial)
const recipients = computed(() => props.project?.update_recipients || 0)
const sendLabel = computed(() => `Send to ${recipients.value} ${recipients.value === 1 ? "partner" : "partners"}`)
const errors = computed(() => (tried.value ? missingAnswers(form.value, EDITED) : {}))

// The requirements as partners got them: one row per answer, blank ones left out.
const rows = computed(() => {
	const current = props.project || {}
	const c = criteria.value
	const place = c.cities.length ? c.cities : c.countries
	const tier = c.tiers.length ? `${orList(c.tiers)} tier` : "Any tier"
	const operations = labelIn(OPERATION_OPTIONS, current.operations)
	const systems = (current.systems || []).length ? `You use ${andList(current.systems)}` : ""
	const size = labelIn(EMPLOYEE_OPTIONS, current.company_size)
	return [
		{ label: "Budget", text: current.budget || "" },
		{ label: "Timeline", text: current.go_live ? goLiveCriterion(current.go_live) : "" },
		{ label: "Apps", text: andList(current.apps || []) },
		{ label: "Today", text: [operations, systems].filter(Boolean).join(". ") },
		{ label: "To fix", text: (current.problems || []).map((v) => labelIn(PROBLEM_OPTIONS, v)).filter(Boolean).join(", ") },
		{
			label: "Looking for",
			text: [tier, place.length ? `in ${orList(place)}` : "anywhere", workCriterion(c.work).toLowerCase()].join(", "),
		},
		{ label: "Company", text: [andList(current.industries || []), size && `${size} employees`].filter(Boolean).join(" · ") },
	].filter((row) => row.text)
})

// Sentence-long options, so two don't fit the field: one reads in full, more as a count.
const fixedSummary = computed(() => {
	const picked = form.value.problems || []
	return picked.length > 1 ? `${picked.length} picked` : namesOf(picked, PROBLEM_OPTIONS, "Nothing picked")
})
const workChoice = computed({
	get: () => workChoiceOf(form.value.work_modes),
	set: (choice) => (form.value.work_modes = workModesOf(choice)),
})

// Back to reading each time it opens.
watch(
	() => props.modelValue,
	(open) => {
		if (open) editing.value = false
	},
)
watch(() => form.value.description, () => nextTick(fitDescription))

function startEditing() {
	const current = props.project || {}
	form.value = {
		budget: current.budget || "",
		go_live: current.go_live || "",
		apps: [...(current.apps || [])],
		regions: [...(current.regions || [])],
		work_modes: [...(current.work_modes || [])],
		operations: current.operations || "",
		systems: [...(current.systems || [])],
		problems: [...(current.problems || [])],
		cities: [...criteria.value.cities],
		tiers: [...criteria.value.tiers],
		description: current.description || "",
	}
	initial = JSON.stringify(form.value)
	tried.value = false
	sendError.value = ""
	editing.value = true
	loadOptions()
	nextTick(fitDescription)
}

// City and tier carry no counts here: an edit goes to the same partners whatever is picked.
function loadOptions() {
	call("connect.api.partner.list_partner_countries")
		.then((countries) => (regionOptions.value = (countries || []).map((c) => ({ label: c, value: c }))))
		.catch(() => {})
	call("connect.api.projects.partner_criteria", { criteria: JSON.stringify(criteria.value) })
		.then((facets) => {
			cityOptions.value = (facets?.cities || []).map((c) => ({ label: c.value, value: c.value }))
			tierOptions.value = (facets?.tiers || []).map((t) => ({ label: t.value, value: t.value }))
		})
		.catch(() => {})
}

function payload() {
	const { cities, tiers, ...answers } = form.value
	if (!usesOtherSystems(answers.operations)) answers.systems = []
	return JSON.stringify({ ...answers, description: answers.description.trim(), criteria: { cities, tiers } })
}

function send() {
	if (sending.value) return
	tried.value = true
	if (Object.keys(errors.value).length) return
	sending.value = true
	sendError.value = ""
	call("connect.api.projects.update_requirements", { name: props.project.name, answers: payload() })
		.then((project) => {
			emit("updated", project)
			editing.value = false
			toast.success(`Sent to ${recipients.value} ${recipients.value === 1 ? "partner" : "partners"}`)
		})
		.catch((error) => {
			sendError.value = error?.messages?.[0] || "Couldn't send your requirements. Try again."
		})
		.finally(() => {
			sending.value = false
		})
}

// Cancel, × or Esc with unsaved changes ask first; Cancel goes back to reading.
function leaveEditing(then) {
	if (!dirty.value) return then()
	dialog.confirm({
		title: "Discard changes?",
		message: "Your edits to the requirements won't be sent.",
		confirmLabel: "Discard",
		theme: "red",
		onConfirm: ({ close }) => {
			close()
			then()
		},
	})
}

function cancel() {
	leaveEditing(() => (editing.value = false))
}

function onOpen(open) {
	if (open) return
	leaveEditing(() => emit("update:modelValue", false))
}

// The description grows with its text, so the dialog keeps a single scroll.
function fitDescription() {
	const area = descriptionField.value?.$el?.querySelector?.("textarea")
	if (!area) return
	area.style.overflow = "hidden"
	area.style.resize = "none"
	area.style.height = "auto"
	area.style.height = `${area.scrollHeight}px`
}

function labelIn(options, value) {
	return options.find((o) => o.value === value)?.label || ""
}

function namesOf(values, options, none) {
	return values.length ? values.map((v) => labelIn(options, v) || v).join(", ") : none
}

function andList(values) {
	if (values.length <= 1) return values.join("")
	return `${values.slice(0, -1).join(", ")} and ${values[values.length - 1]}`
}
</script>

<template>
	<Dialog
		:open="modelValue"
		title="Your requirements"
		size="md"
		:actions="!editing && !lockNote ? editActions : []"
		@update:open="onOpen"
	>
		<template #default>
			<!-- frappe-ui's ScrollArea: a thin scrollbar, shown while scrolling, in place of the browser's. -->
			<ScrollArea v-if="project" class="-mr-4 sm:-mr-6" viewport-class="max-h-[calc(100vh-16rem)] pr-4 sm:pr-6">
				<div v-if="editing" class="space-y-6">
					<Alert theme="blue" title="Partners who quoted will confirm or re-quote" />
					<form novalidate class="space-y-4" @submit.prevent="send">
						<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
							<FormControl
								v-model="form.budget"
								type="select"
								label="Your budget"
								placeholder="Select a range"
								required
								:options="BUDGET_OPTIONS"
								:error="errors.budget"
							/>
							<FormControl
								v-model="form.go_live"
								type="select"
								label="When do you need it live?"
								placeholder="Select"
								required
								:options="GO_LIVE_OPTIONS"
								:error="errors.go_live"
							/>
						</div>
						<AppsSelect v-model="form.apps" required :error="errors.apps" />
						<MultiSelect
							v-model="form.regions"
							label="Which regions should your partners be from?"
							:options="regionOptions"
							placeholder="Select"
							required
							:error="errors.regions"
						/>
						<FormControl
							v-model="workChoice"
							type="select"
							label="How do you want to work?"
							placeholder="Select"
							required
							:options="WORK_CHOICES"
							:error="errors.work_modes"
						/>
						<FormControl
							v-model="form.operations"
							type="select"
							label="How you handle this today"
							placeholder="Select one"
							required
							:options="OPERATION_OPTIONS"
							:error="errors.operations"
						/>
						<MultiSelect
							v-if="usesOtherSystems(form.operations)"
							v-model="form.systems"
							label="Which systems do you use?"
							:options="SYSTEM_OPTIONS"
							placeholder="Select"
							required
							:error="errors.systems"
						/>
						<MultiSelect
							v-model="form.problems"
							label="What you want fixed"
							:options="PROBLEM_OPTIONS"
							required
							hide-search
							:error="errors.problems"
						>
							<template #footer />
							<template #summary>
								<span class="text-ink-gray-8">{{ fixedSummary }}</span>
							</template>
						</MultiSelect>
						<!-- "Partner" in both labels: on their own, City and Tier read as yours. -->
						<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
							<MultiSelect v-model="form.cities" label="Partner city" :options="cityOptions" hide-search>
								<template #footer />
								<template #summary>
									<span class="text-ink-gray-8">{{ namesOf(form.cities, cityOptions, "Any city") }}</span>
								</template>
							</MultiSelect>
							<MultiSelect v-model="form.tiers" label="Partner tier" :options="tierOptions" hide-search>
								<template #footer />
								<template #summary>
									<span class="text-ink-gray-8">{{ namesOf(form.tiers, tierOptions, "Any tier") }}</span>
								</template>
							</MultiSelect>
						</div>
						<FormControl
							ref="descriptionField"
							v-model="form.description"
							type="textarea"
							label="Description"
							:rows="4"
							required
							:error="errors.description"
						/>
						<ErrorMessage v-if="sendError" :message="sendError" />
					</form>
				</div>

				<div v-else class="flex flex-col gap-6">
					<dl class="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-4 text-base">
						<template v-for="row in rows" :key="row.label">
							<dt class="text-ink-gray-6">{{ row.label }}</dt>
							<dd class="whitespace-pre-line text-ink-gray-8">{{ row.text }}</dd>
						</template>
					</dl>
					<section v-if="project.description" class="flex flex-col gap-2">
						<h4 class="text-base font-medium text-ink-gray-8">Description</h4>
						<p class="whitespace-pre-line text-p-base leading-relaxed text-ink-gray-6">{{ project.description }}</p>
					</section>
				</div>
			</ScrollArea>
		</template>

		<template v-if="lockNote" #actions>
			<p class="text-p-sm text-ink-gray-6">{{ lockNote }}</p>
		</template>
		<template v-else-if="editing" #actions>
			<div class="flex justify-end gap-2">
				<Button label="Cancel" @click="cancel" />
				<Button variant="solid" :label="sendLabel" :disabled="!dirty" :loading="sending" @click="send" />
			</div>
		</template>
	</Dialog>
</template>
