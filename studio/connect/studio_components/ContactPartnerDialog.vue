<script setup>
// Contact on a partner, for a customer who already has projects: one of them goes to the
// partner as their brief. A project with every answer shows what it says and is sent from
// here; one missing any opens the project questions, filled in, to answer the rest and send.
// Create new project, last in the list, opens the questions for a new one to this partner.
// With no project yet, the page opens the project questions instead (partnerConnect.ts).
import { computed, getCurrentInstance, ref, watch } from "vue"
import { Button, Dialog, ErrorMessage, FormControl, LoadingIndicator, call } from "frappe-ui"
import { DialogDescription } from "reka-ui"
import { missingAnswers } from "@app/utils/projectDialog"
import ProjectQuestionsDialog from "./ProjectQuestionsDialog.vue"

const props = defineProps({
	// Whether the dialog is open (v-model).
	modelValue: { type: Boolean, default: false },
	// { name, company_name }
	partner: { type: Object, default: null },
	// The customer's projects that can be sent, newest first: list_projects rows.
	projects: { type: Array, default: () => [] },
})
const emit = defineEmits(["update:modelValue"])

const router = getCurrentInstance()?.appContext.config.globalProperties.$router
const MESSAGES_ROUTE = "/messaging"
const NEW_PROJECT = "new"

const picked = ref(null)
// The picked project with every answer (get_project), to check and to fill the questions from.
const project = ref(null)
const loading = ref(false)
const sending = ref(false)
const sendError = ref("")
const answering = ref(false)
// The questions open for this project, or for a new one (null).
const answeringProject = ref(null)

const partnerName = computed(() => props.partner?.company_name || props.partner?.name || "")
const projectOptions = computed(() => [
	...props.projects.map((p) => ({ label: p.project_title, value: p.project })),
	{ label: "Create new project", value: NEW_PROJECT },
])
const isComplete = computed(() => !!project.value && !Object.keys(missingAnswers(project.value)).length)
// What the partner gets, as Pragati's design lists it.
const details = computed(() => {
	const current = project.value || {}
	return [
		{ label: "What you need", text: current.description, long: true },
		{ label: "Apps", text: (current.apps || []).join(", ") },
		{ label: "Budget", text: current.budget },
	].filter((row) => row.text)
})

// Reset on open, not on close, so the answers don't vanish while the dialog fades out.
watch(
	() => props.modelValue,
	(open) => {
		if (!open) return
		sendError.value = ""
		picked.value = props.projects[0]?.project || null
		loadProject()
	},
	{ immediate: true },
)
watch(picked, (value, previous) => {
	if (value !== NEW_PROJECT) return loadProject()
	// Not a project to show: the questions open for a new one, and the pick goes back.
	picked.value = previous
	answeringProject.value = null
	close()
	answering.value = true
})

function loadProject() {
	project.value = null
	if (!picked.value) return
	loading.value = true
	call("connect.api.projects.get_project", { name: picked.value })
		.then((data) => (project.value = data))
		.catch(() => (sendError.value = "Couldn't load this project. Try again."))
		.finally(() => (loading.value = false))
}

function close() {
	emit("update:modelValue", false)
}

function answerTheRest() {
	answeringProject.value = project.value
	close()
	answering.value = true
}

function send() {
	if (!props.partner || !isComplete.value || sending.value) return
	sending.value = true
	sendError.value = ""
	call("connect.api.projects.start_project_with_partner", { partner: props.partner.name, project: picked.value })
		.then((result) => {
			close()
			router?.push({ path: MESSAGES_ROUTE, query: { thread: result.thread } })
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
	<Dialog :open="modelValue" size="md" @update:open="!$event && close()">
		<template v-if="partner" #title>
			<div>
				<h3 class="text-2xl font-semibold text-ink-gray-9">Contact {{ partnerName }}</h3>
				<!-- What sending hands over, said before it is sent. pr-8 clears the close button. -->
				<DialogDescription class="mt-1 pr-8 text-p-base text-ink-gray-5">
					Your requirements and company details are shared with them.
				</DialogDescription>
			</div>
		</template>

		<template v-if="partner && picked" #default>
			<form novalidate @submit.prevent="isComplete ? send() : answerTheRest()">
				<FormControl v-model="picked" type="select" label="Project" :options="projectOptions" />

				<dl v-if="isComplete" class="mt-4 space-y-2">
					<div v-for="row in details" :key="row.label" class="flex gap-6 text-p-base">
						<dt class="w-32 shrink-0 text-ink-gray-5">{{ row.label }}</dt>
						<dd
							class="min-w-0 text-ink-gray-8"
							:class="row.long ? 'line-clamp-3 whitespace-pre-line' : 'font-medium'"
						>
							{{ row.text }}
						</dd>
					</div>
				</dl>

				<div v-if="loading" class="mt-5 flex justify-center"><LoadingIndicator class="size-4 text-ink-gray-5" /></div>
				<p v-else-if="project && !isComplete" class="mt-5 text-p-base text-ink-gray-7">
					This project is missing a few answers partners need to quote. Answer them, then it goes to {{ partnerName }}.
				</p>

				<ErrorMessage v-if="sendError" class="mt-4" :message="sendError" />

				<div class="mt-8">
					<Button
						class="w-full"
						variant="solid"
						size="sm"
						:label="isComplete ? 'Send requirements' : 'Answer the rest'"
						type="submit"
						:disabled="!project"
						:loading="sending"
					>
						<template #prefix><span :class="isComplete ? 'lucide-send' : 'lucide-pencil'" class="size-4" /></template>
					</Button>
				</div>
			</form>
		</template>
	</Dialog>

	<ProjectQuestionsDialog v-model="answering" :partner="partner" :project="answeringProject" />
</template>
