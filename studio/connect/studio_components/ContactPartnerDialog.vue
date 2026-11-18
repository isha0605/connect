<script setup>
// Contact on a partner, for a customer who already has projects: one of them goes to the
// partner as their brief. A project with every answer shows what it says and is sent from
// here; one missing any opens the project questions, filled in, to answer the rest and send.
// With no project yet, the page opens the project questions instead (partnerConnect.ts).
import { computed, getCurrentInstance, ref, watch } from "vue"
import { Button, Dialog, ErrorMessage, FormControl, LoadingIndicator, call } from "frappe-ui"
import { DialogDescription } from "reka-ui"
import { missingAnswers } from "@app/utils/projectDialog"
import ProjectQuestionsDialog from "./ProjectQuestionsDialog.vue"

const props = defineProps({
	// Whether the dialog is open (v-model).
	modelValue: { type: Boolean, default: false },
	// { name, partner_name }
	partner: { type: Object, default: null },
	// The customer's projects that can be sent, newest first: list_projects rows.
	projects: { type: Array, default: () => [] },
})
const emit = defineEmits(["update:modelValue"])

const router = getCurrentInstance()?.appContext.config.globalProperties.$router
const PROJECTS_ROUTE = "/projects"
const MESSAGES_ROUTE = "/messaging"

const picked = ref(null)
// The picked project with every answer (get_project), to check and to fill the questions from.
const project = ref(null)
const loading = ref(false)
const sending = ref(false)
const sendError = ref("")
const answering = ref(false)

const partnerName = computed(() => props.partner?.partner_name || props.partner?.name || "")
// A picker only when there is a choice: one project is just its name.
const picking = computed(() => props.projects.length > 1)
const projectOptions = computed(() => props.projects.map((p) => ({ label: p.project_title, value: p.project })))
const pickedTitle = computed(() => props.projects.find((p) => p.project === picked.value)?.project_title || "")
const isComplete = computed(() => !!project.value && !Object.keys(missingAnswers(project.value)).length)

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
watch(picked, loadProject)

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

function manage() {
	close()
	router?.push(PROJECTS_ROUTE)
}

function answerTheRest() {
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
				<div v-if="picking" class="flex items-center justify-between gap-3">
					<FormControl
						v-model="picked"
						class="min-w-0 flex-1"
						type="select"
						label="Project"
						:options="projectOptions"
					/>
					<Button class="shrink-0 self-end" variant="ghost" size="sm" label="Manage" @click="manage">
						<template #suffix><span class="lucide-arrow-up-right size-4" /></template>
					</Button>
				</div>

				<dl :class="picking ? 'mt-4 space-y-2' : 'space-y-2'">
					<!-- Manage fades in rather than appearing, so the name beside it never reflows. -->
					<div v-if="!picking" class="group flex gap-6 text-p-base">
						<dt class="w-32 shrink-0 text-ink-gray-5">Project</dt>
						<dd class="flex min-w-0 items-center gap-1 font-medium text-ink-gray-8">
							<span class="min-w-0">{{ pickedTitle }}</span>
							<Button
								class="-my-1 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
								variant="ghost"
								size="sm"
								label="Manage"
								@click="manage"
							>
								<template #suffix><span class="lucide-arrow-up-right size-4" /></template>
							</Button>
						</dd>
					</div>

					<template v-if="isComplete">
						<div class="flex gap-6 text-p-base">
							<dt class="w-32 shrink-0 text-ink-gray-5">What you need</dt>
							<dd class="line-clamp-3 min-w-0 whitespace-pre-line text-ink-gray-8">{{ project.description }}</dd>
						</div>
						<div class="flex gap-6 text-p-base">
							<dt class="w-32 shrink-0 text-ink-gray-5">Budget</dt>
							<dd class="font-medium text-ink-gray-8">{{ project.budget }}</dd>
						</div>
					</template>
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

	<ProjectQuestionsDialog v-model="answering" :partner="partner" :project="project" />
</template>
