<script setup>
// The page a review request's email link opens. It says which partner is asking about which
// project, and acts only when the customer answers (mail scanners open links on their own):
// "I worked with them" signs them in and opens the review form on the partner's profile; "I didn't"
// tells the partner and Frappe's partner reviewers. The link itself is what authorises them.
import { computed, reactive, ref } from "vue"
import { Button, FormControl, call } from "frappe-ui"

const props = defineProps({
	token: { type: String, default: "" },
})

const API = "connect.api.review_requests"
const SIGN_IN = "/connect/login-signup-redesign?screen=login"

// "loading" | "ready" | "declining" | "declined" | "invalid"
const state = ref("loading")
const request = ref(null)
const form = reactive({ full_name: "", company_name: "", reason: "" })
const tried = ref(false)
const busy = ref(false)
const error = ref("")

const partnerName = computed(() => request.value?.partner_name || "the partner")
const errors = computed(() => {
	if (!tried.value) return {}
	const found = {}
	if (!form.full_name.trim()) found.full_name = "Enter your name"
	if (!request.value?.has_account && !form.company_name.trim()) found.company_name = "Enter your company"
	return found
})

if (props.token) {
	call(`${API}.open_review_request`, { token: props.token })
		.then((data) => {
			request.value = data
			form.full_name = data.contact_name || ""
			form.company_name = data.company_name || ""
			state.value = "ready"
		})
		.catch(() => (state.value = "invalid"))
} else {
	state.value = "invalid"
}

async function accept() {
	tried.value = true
	if (Object.keys(errors.value).length || busy.value) return
	busy.value = true
	error.value = ""
	try {
		const result = await call(`${API}.accept_review_request`, {
			token: props.token,
			full_name: form.full_name.trim(),
			company_name: form.company_name.trim(),
		})
		// A full load: the person is signed in now.
		window.location.href = result.redirect
	} catch (failure) {
		error.value = failure?.messages?.[0] || "Couldn't confirm it. Try again."
		busy.value = false
	}
}

function signIn() {
	window.location.href = SIGN_IN
}

async function decline() {
	if (busy.value) return
	busy.value = true
	error.value = ""
	try {
		await call(`${API}.decline_review_request`, { token: props.token, reason: form.reason.trim() })
		state.value = "declined"
	} catch (failure) {
		error.value = failure?.messages?.[0] || "Couldn't send that. Try again."
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<div class="mx-auto flex w-full max-w-[460px] flex-col gap-4 rounded-xl border border-outline-gray-2 p-7">
		<p class="text-sm text-ink-gray-5">Frappe Connect</p>

		<p v-if="state === 'loading'" class="text-p-base text-ink-gray-5">Loading…</p>

		<template v-else-if="state === 'invalid'">
			<h1 class="text-xl font-semibold text-ink-gray-9">This link doesn't work any more</h1>
			<p class="text-p-base text-ink-gray-7">
				It expired, was withdrawn, or was already used. If you've already confirmed, sign in to write your review from the partner's profile.
			</p>
			<Button class="self-start" label="Sign in" @click="signIn" />
		</template>

		<template v-else-if="state === 'declined'">
			<h1 class="text-xl font-semibold text-ink-gray-9">Thanks for telling us</h1>
			<p class="text-p-base text-ink-gray-7">
				We've let {{ partnerName }} and Frappe's partner team know. You don't need to do anything else.
			</p>
		</template>

		<template v-else>
			<h1 class="text-xl font-semibold text-ink-gray-9">How was working with {{ partnerName }}?</h1>
			<p class="text-p-base text-ink-gray-7">
				{{ partnerName }} asked for your review of <span class="font-medium text-ink-gray-9">{{ request.project_title }}</span>.
				Your review helps other businesses choose a partner.
			</p>
			<blockquote v-if="request.project_summary" class="whitespace-pre-line border-l-2 border-outline-gray-2 pl-3 text-p-base text-ink-gray-6">
				{{ request.project_summary }}
			</blockquote>

			<form v-if="state === 'ready'" novalidate class="flex flex-col gap-4" @submit.prevent="accept">
				<FormControl v-model="form.full_name" label="Your name" required :error="errors.full_name" />
				<FormControl
					v-if="!request.has_account"
					v-model="form.company_name"
					label="Your company"
					required
					:error="errors.company_name"
				/>
				<p class="text-p-sm text-ink-gray-5">You'll be signed in as {{ request.contact_email }}.</p>
				<p v-if="error" class="text-p-sm text-ink-red-6">{{ error }}</p>
				<Button variant="solid" type="submit" :label="`Yes, I worked with ${partnerName}`" :loading="busy" />
				<Button variant="ghost" label="I didn't work with them" :disabled="busy" @click="state = 'declining'" />
			</form>

			<form v-else novalidate class="flex flex-col gap-4" @submit.prevent="decline">
				<FormControl
					v-model="form.reason"
					type="textarea"
					label="What happened? (optional)"
					placeholder="For example: we never worked with them, or this isn't my project."
					:rows="3"
				/>
				<p v-if="error" class="text-p-sm text-ink-red-6">{{ error }}</p>
				<div class="flex gap-2">
					<Button variant="solid" theme="red" type="submit" label="Tell Frappe" :loading="busy" />
					<Button label="Back" :disabled="busy" @click="state = 'ready'" />
				</div>
			</form>
		</template>
	</div>
</template>
