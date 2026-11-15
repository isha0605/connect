<script setup>
// Give feedback, from the sidebar's company menu: what the person writes is saved as a Connect
// Feedback record, with the page they were on, for Frappe staff to read.
import { onBeforeUnmount, onMounted, ref } from "vue"
import { Button, Dialog, ErrorMessage, Textarea, call, toast } from "frappe-ui"

const MAX_LENGTH = 2000

const open = ref(false)
const message = ref("")
const error = ref("")
const sending = ref(false)

function show() {
	message.value = ""
	error.value = ""
	open.value = true
}

function send() {
	if (!message.value.trim()) {
		error.value = "Write your feedback first."
		return
	}
	sending.value = true
	call("connect.api.account.send_feedback", { message: message.value, page: window.location.pathname })
		.then(() => {
			open.value = false
			toast.success("Thanks. Your feedback reached the Connect team.")
		})
		.catch((failure) => (error.value = failure?.messages?.[0] || "Couldn't send your feedback. Try again."))
		.finally(() => (sending.value = false))
}

onMounted(() => window.addEventListener("connect:open-feedback", show))
onBeforeUnmount(() => window.removeEventListener("connect:open-feedback", show))
</script>

<template>
	<Dialog v-model:open="open" title="Give feedback" size="md">
		<template #default>
			<div class="flex flex-col gap-2">
				<p class="text-p-base text-ink-gray-6">What works, what doesn't, or what you'd like to see. The Connect team reads every note.</p>
				<Textarea
					v-model="message"
					:rows="5"
					:maxlength="MAX_LENGTH"
					aria-label="Your feedback"
					placeholder="Your feedback"
					@update:model-value="error = ''"
				/>
				<ErrorMessage :message="error" />
			</div>
		</template>
		<template #actions>
			<div class="flex justify-end gap-2">
				<Button variant="subtle" @click="open = false">Cancel</Button>
				<Button variant="solid" :loading="sending" @click="send">Send</Button>
			</div>
		</template>
	</Dialog>
</template>
