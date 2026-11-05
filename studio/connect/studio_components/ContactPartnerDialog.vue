<script setup>
// Contact on a partner, for a customer who already has projects: one of them goes to the
// partner as their brief. A complete brief shows read-only; one without a budget or a
// description asks for both here, and they are saved on the project for the next partner.
// With no project yet, the page opens the New project dialog instead (partnerConnect.ts).
import { computed, getCurrentInstance, reactive, ref, watch } from "vue"
import { Button, Dialog, FormControl, call } from "frappe-ui"
import { DialogDescription } from "reka-ui"
import { BUDGET_OPTIONS } from "@app/utils/recommendation"

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

const form = reactive({ project: null, budget: "", description: "" })
// Field errors stay quiet until the first Send, then follow the answers.
const tried = ref(false)
const sending = ref(false)
const sendError = ref("")

const partnerName = computed(() => props.partner?.partner_name || props.partner?.name || "")
// A picker only when there is a choice: one project is just its name.
const picking = computed(() => props.projects.length > 1)
const projectOptions = computed(() => props.projects.map((p) => ({ label: p.project_title, value: p.project })))
const project = computed(() => props.projects.find((p) => p.project === form.project) || null)
const asking = computed(() => Boolean(project.value) && !(project.value.budget && project.value.description))

const errors = computed(() => {
	if (!tried.value || !asking.value) return {}
	const found = {}
	if (!form.budget) found.budget = "Pick a range"
	if (!form.description.trim()) found.description = "Describe what you need built"
	return found
})

// Reset on open, not on close, so the answers don't vanish while the dialog fades out.
watch(
	() => props.modelValue,
	(open) => {
		if (!open) return
		tried.value = false
		sendError.value = ""
		form.project = props.projects[0]?.project || null
	},
	{ immediate: true },
)

// A half-written brief on the project is finished here, not started again.
watch(
	() => form.project,
	() => {
		form.budget = project.value?.budget || ""
		form.description = project.value?.description || ""
	},
)

function close() {
	emit("update:modelValue", false)
}

function manage() {
	close()
	router?.push(PROJECTS_ROUTE)
}

function send() {
	if (!props.partner || !project.value || sending.value) return
	tried.value = true
	if (Object.keys(errors.value).length) return

	sending.value = true
	sendError.value = ""
	const brief = asking.value ? { budget: form.budget, description: form.description.trim() } : {}
	call("connect.api.projects.start_project_with_partner", {
		partner: props.partner.name,
		project: project.value.project,
		...brief,
	})
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

		<template v-if="partner && project" #default>
			<form novalidate @submit.prevent="send">
				<div v-if="picking" class="flex items-center justify-between gap-3">
					<FormControl
						v-model="form.project"
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
							<span class="min-w-0">{{ project.project_title }}</span>
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

					<template v-if="!asking">
						<div class="flex gap-6 text-p-base">
							<dt class="w-32 shrink-0 text-ink-gray-5">What you need</dt>
							<dd class="line-clamp-3 min-w-0 whitespace-pre-line text-ink-gray-8">
								{{ project.description }}
							</dd>
						</div>
						<div class="flex gap-6 text-p-base">
							<dt class="w-32 shrink-0 text-ink-gray-5">Budget</dt>
							<dd class="font-medium text-ink-gray-8">{{ project.budget }}</dd>
						</div>
					</template>
				</dl>

				<!-- The same two questions as the custom implementation page, so a brief written
				     here and one written there are the same brief. -->
				<div v-if="asking" class="mt-5 space-y-4">
					<FormControl
						v-model="form.budget"
						type="select"
						label="Your budget"
						placeholder="Select a range"
						required
						:options="BUDGET_OPTIONS"
						:error="errors.budget"
					/>
					<div>
						<FormControl
							v-model="form.description"
							type="textarea"
							label="What do you want built?"
							placeholder="What do you make or sell, who are your customers, how does it run today, what keeps going wrong, and what must it connect to or prove?"
							:rows="5"
							required
							:error="errors.description"
						/>
						<p class="mt-1.5 text-p-sm leading-relaxed text-ink-gray-5">
							Partners quote from this, so the detail you add here comes back as accuracy.
						</p>
					</div>
				</div>

				<p v-if="sendError" class="mt-4 text-p-sm text-ink-red-6">{{ sendError }}</p>

				<div class="mt-8">
					<Button
						class="w-full"
						variant="solid"
						size="sm"
						label="Send requirements"
						type="submit"
						:loading="sending"
					>
						<template #prefix><span class="lucide-send size-4" /></template>
					</Button>
				</div>
			</form>
		</template>
	</Dialog>
</template>
