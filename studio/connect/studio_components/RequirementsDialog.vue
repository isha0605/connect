<script setup>
// "Your requirements" on a sent project: what partners got, read back, and Edit to change it.
// Editing happens in place (Pragati's BriefDetailsDialog); Send goes to every partner who has
// the requirements, and a quote made before then waits for its partner to confirm or redo it.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { Alert, Button, Dialog, ErrorMessage, FormControl, MultiSelect, ScrollArea, call, dialog, toast } from "frappe-ui"
import {
	EMPLOYEE_OPTIONS,
	OPERATION_OPTIONS,
	PROBLEM_OPTIONS,
	SYSTEM_OPTIONS,
} from "@app/utils/recommendation"
import { blankCriteria } from "@app/utils/partnerCriteria"
import {
	MISSING_ANSWERS,
	OTHER_SYSTEM,
	missingAnswers,
	usesOtherSystems,
} from "@app/utils/projectDialog"
import AppsSelect from "./AppsSelect.vue"
import BudgetSelect from "./BudgetSelect.vue"

const props = defineProps({
	// Whether the dialog is open (v-model).
	modelValue: { type: Boolean, default: false },
	// The project, as get_project returns it: the latest version, which its owner can edit.
	project: { type: Object, default: null },
	// Or a Requirement card from a chat: the version that message carried, to read only.
	card: { type: Object, default: null },
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
const cityOptions = ref([])
const tierOptions = ref([])
const descriptionField = ref(null)
const scroller = ref(null)
// The reading view's height, which editing keeps: the form scrolls inside the same dialog.
let readingHeight = 0
// Rounding at display scaling, and the line gap under the inline dialog, take a few pixels.
const SAFETY_GAP = 16

const criteria = computed(() => ({ ...blankCriteria(), ...(props.project?.criteria || {}) }))
const canEdit = computed(() => !props.card && props.project?.status === "Shared")
const lockNote = computed(() => {
	if (props.card) return ""
	const partner = props.project?.hired?.company_name || "your partner"
	if (props.project?.status === "Hiring") return `Waiting on ${partner} to answer your hire request`
	if (["Hired", "Completed"].includes(props.project?.status)) return `Hired. Changes go through ${partner} now`
	return ""
})
const editActions = computed(() =>
	canEdit.value ? [{ label: "Edit", iconLeft: "lucide-pencil", onClick: startEditing }] : [],
)
// Compared the way the server compares versions: list order and outer spaces don't count.
const dirty = computed(() => editing.value && comparable(form.value) !== initial)
const recipients = computed(() => props.project?.update_recipients || 0)
const sendLabel = computed(() => `Send to ${recipients.value} ${recipients.value === 1 ? "partner" : "partners"}`)
const errors = computed(() => (tried.value ? missingAnswers(form.value, EDITED) : {}))

// The rows come from the server (brief.requirement_rows), the same for the project and each
// card. A card sent before the rows were kept falls back to the fields it carried.
const rows = computed(() => {
	if (!props.card) return props.project?.requirement_rows || []
	if (props.card.rows) return props.card.rows
	const c = props.card
	// "Spreadsheets…. Wants to solve: payroll…" (or "Wants fixed:") holds both Today and To fix.
	const [today, toFix = ""] = String(c.current_situation || "").split(/\.\s*Wants (?:to solve|fixed):\s*/)
	const size = labelIn(EMPLOYEE_OPTIONS, c.company_size) || c.company_size
	return [
		{ label: "Budget", text: c.budget },
		{ label: "Apps", text: andList(Array.isArray(c.apps) ? c.apps : []) },
		{ label: "Today", text: today },
		{ label: "To fix", text: toFix ? toFix.charAt(0).toUpperCase() + toFix.slice(1) : "" },
		{ label: "Looking for", text: c.partner_brief },
		{ label: "Company", text: [c.industry, size && `${size} employees`].filter(Boolean).join(" · ") },
	].filter((row) => row.text)
})
const description = computed(() => (props.card ? props.card.description : props.project?.description) || "")

// Sentence-long options, so two don't fit the field: one reads in full, more as a count.
const fixedSummary = computed(() => {
	const picked = form.value.problems || []
	return picked.length > 1 ? `${picked.length} picked` : namesOf(picked, PROBLEM_OPTIONS, "Nothing picked")
})


// Back to reading each time it opens.
watch(
	() => props.modelValue,
	(open) => {
		if (open) editing.value = false
		if (open) scheduleFit()
	},
)
watch(editing, scheduleFit)
onMounted(() => window.addEventListener("resize", fitHeight))
onBeforeUnmount(() => window.removeEventListener("resize", fitHeight))
watch(() => form.value.description, () => nextTick(fitDescription))

function startEditing() {
	readingHeight = scrollViewport()?.offsetHeight || 0
	const current = props.project || {}
	form.value = {
		budget: current.budget || "",
		apps: [...(current.apps || [])],
		operations: current.operations || "",
		systems: [...(current.systems || [])],
		other_system: current.other_system || "",
		problems: [...(current.problems || [])],
		cities: [...criteria.value.cities],
		tiers: [...criteria.value.tiers],
		description: current.description || "",
	}
	initial = comparable(form.value)
	tried.value = false
	sendError.value = ""
	editing.value = true
	loadOptions()
	nextTick(fitDescription)
}

// City and tier carry no counts here: an edit goes to the same partners whatever is picked.
function loadOptions() {
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
			const sent = project.update_sent_to || 0
			if (sent) toast.success(`Sent to ${sent} ${sent === 1 ? "partner" : "partners"}`)
			else toast.info("Nothing changed, so nothing was sent")
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

// The body scrolls inside the dialog, never the page: it gets the window's height less the
// dialog's own title, buttons and margins, measured, since fonts and zoom change them.
// After the dialog is on the page: it opens with a transition.
function scheduleFit() {
	nextTick(() => requestAnimationFrame(fitHeight))
}

function scrollViewport() {
	return scroller.value?.$el?.querySelector?.("[data-slot=scroll-area-viewport]")
}

function fitHeight() {
	const viewport = scrollViewport()
	const content = viewport?.closest(".dialog-content")
	const overlay = content?.closest(".dialog-scroll-container")
	if (!overlay) return
	const style = getComputedStyle(content)
	const margins = parseFloat(style.marginTop) + parseFloat(style.marginBottom)
	const chrome = content.offsetHeight - viewport.offsetHeight
	// The overlay's own height, not the window's: the same units as the dialog at any zoom.
	const room = overlay.clientHeight - chrome - margins - SAFETY_GAP
	const height = editing.value && readingHeight ? Math.min(room, readingHeight) : room
	viewport.style.maxHeight = `${Math.max(height, 160)}px`
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

function comparable(values) {
	const entries = Object.entries(values).map(([key, value]) => [
		key,
		Array.isArray(value) ? [...value].sort() : String(value ?? "").trim(),
	])
	return JSON.stringify(Object.fromEntries(entries))
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
			<ScrollArea v-if="project || card" ref="scroller" class="-mr-4 sm:-mr-6" viewport-class="pr-4 sm:pr-6">
				<div v-if="editing" class="space-y-6">
					<Alert theme="blue" title="Partners who quoted will confirm or re-quote" />
					<form novalidate class="space-y-4" @submit.prevent="send">
						<BudgetSelect v-model="form.budget" required :error="errors.budget" />
						<AppsSelect v-model="form.apps" required :error="errors.apps" />
						<FormControl
							v-model="form.operations"
							type="select"
							label="How you handle this today"
							placeholder="Select one"
							:options="OPERATION_OPTIONS"
						/>
						<MultiSelect
							v-if="usesOtherSystems(form.operations)"
							v-model="form.systems"
							label="Which systems do you use?"
							:options="SYSTEM_OPTIONS"
							placeholder="Select"
						/>
						<FormControl
							v-if="usesOtherSystems(form.operations) && form.systems.includes(OTHER_SYSTEM)"
							v-model="form.other_system"
							type="text"
							label="What else do you use?"
							placeholder="e.g. a custom system built in-house"
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
					<section v-if="description" class="flex flex-col gap-2">
						<h4 class="text-base font-medium text-ink-gray-8">Description</h4>
						<p class="whitespace-pre-line text-p-base leading-relaxed text-ink-gray-6">{{ description }}</p>
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
