<script setup>
// Hire a partner from their quote: agree to the terms, then say what made you choose them.
// The project page and a Quote card in Messages both open it, so a hire reads the same from
// either. `quote` is a quote row as list_quotes or quote_card_statuses gives it.
import { computed, ref, watch } from "vue"
import { Avatar, Badge, Button, Checkbox, Dialog, ErrorMessage, Textarea, Tooltip, call, toast } from "frappe-ui"
import { formatMoney } from "@app/utils/money"
import { tierSeal } from "@app/utils/tierSeal"

const props = defineProps({
	// Whether the dialog is open (v-model).
	modelValue: { type: Boolean, default: false },
	// { name, company_name, logo, tier, city, country, amount, currency, timeline_weeks, status }
	quote: { type: Object, default: null },
})
// `hired` carries the project as hire_partner returns it.
const emit = defineEmits(["update:modelValue", "hired"])

const OTHER_REASON = "Other"

const step = ref("terms")
const agreed = ref(false)
const needsAgreement = ref(false)
const hiring = ref(false)
const project = ref(null)
const pickedReasons = ref([])
const note = ref("")
const savingReasons = ref(false)
const reasonError = ref("")

const name = computed(() => props.quote?.company_name || "this partner")
const amount = computed(() => formatMoney(props.quote?.amount, props.quote?.currency))
const timeline = computed(() => {
	const weeks = props.quote?.timeline_weeks || 0
	return `${weeks} week${weeks === 1 ? "" : "s"}`
})
// The reasons come from the server, which checks them; Other opens a note of its own.
const reasons = computed(() => [...(project.value?.hire_reasons || []), OTHER_REASON])
const noteLimit = computed(() => project.value?.hire_note_limit || 500)
const hasOtherReason = computed(() => pickedReasons.value.includes(OTHER_REASON))
// Frappe not being a party comes first: it is the one a customer would otherwise assume the opposite of.
const terms = computed(() =>
	[
		{ icon: "lucide-wallet", text: `Pay ${name.value} directly, Frappe isn’t a party` },
		{ icon: "lucide-file-check", text: "Scope, price and timeline are as quoted" },
		{ icon: "lucide-cloud", text: `Host with ${name.value}, Frappe Cloud or elsewhere` },
		{ icon: "lucide-lock", text: "Frappe sees this implementation, not your site" },
		// Hire is on every quote, so it can be the first time this partner learns who you are.
		props.quote?.status !== "Interested" && {
			icon: "lucide-building-2",
			text: `${name.value} gets your company name and contact details`,
		},
	].filter(Boolean),
)

watch(
	() => props.modelValue,
	(open) => {
		if (!open) return
		step.value = "terms"
		agreed.value = false
		needsAgreement.value = false
		project.value = null
		pickedReasons.value = []
		note.value = ""
		reasonError.value = ""
	},
)

const close = () => emit("update:modelValue", false)

// Hire stays enabled, since a disabled button can't say why; pressing it unticked says so instead.
async function confirmHire() {
	if (!agreed.value) {
		needsAgreement.value = true
		return
	}
	if (hiring.value || !props.quote) return
	hiring.value = true
	try {
		project.value = await call("connect.api.projects.hire_partner", { quote: props.quote.name })
		step.value = "why"
		toast.success(`Hire request sent to ${name.value}`)
		emit("hired", project.value)
	} catch (error) {
		toast.error(error?.messages?.[0] || "Couldn't hire this partner. Try again.")
	} finally {
		hiring.value = false
	}
}

function toggleReason(reason) {
	const picked = pickedReasons.value
	pickedReasons.value = picked.includes(reason) ? picked.filter((item) => item !== reason) : [...picked, reason]
}

// Done is the one action: with nothing picked it just closes. A failed save keeps the dialog
// open with the reason, so the answer isn't lost.
async function sendReasons() {
	if (savingReasons.value) return
	const picked = pickedReasons.value.filter((reason) => reason !== OTHER_REASON)
	const otherNote = hasOtherReason.value ? note.value.trim() : ""
	if (!project.value || (!picked.length && !otherNote)) return close()

	savingReasons.value = true
	reasonError.value = ""
	try {
		const args = { name: project.value.name, reasons: JSON.stringify(picked), note: otherNote }
		await call("connect.api.projects.set_hire_reason", args)
		close()
	} catch (error) {
		reasonError.value = error?.messages?.[0] || "Couldn't save that. Try again."
	} finally {
		savingReasons.value = false
	}
}
</script>

<template>
	<Dialog
		:open="modelValue"
		:title="step === 'terms' ? 'Confirm the hire' : ''"
		size="lg"
		@update:open="(open) => emit('update:modelValue', open)"
	>
		<template #default>
			<div v-if="step === 'terms'" class="flex w-full flex-col">
				<div class="-mx-2 -mt-1 flex items-center gap-3 rounded-6 bg-surface-gray-1 px-4 py-3">
					<Avatar :image="quote?.logo" :label="name" size="2xl" shape="square" class="shrink-0 [&_img]:object-contain" />
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span class="line-clamp-2 min-w-0 text-base font-medium text-ink-gray-8">{{ name }}</span>
							<Badge v-if="quote?.tier === 'Gold'" label="Gold" theme="amber" variant="subtle" size="sm" class="shrink-0">
								<template #prefix><span v-html="tierSeal('Gold', 12)" /></template>
							</Badge>
							<Tooltip v-else-if="quote?.tier === 'Silver' || quote?.tier === 'Bronze'" :text="`${quote.tier} Partner`">
								<span v-html="tierSeal(quote.tier, 14)" />
							</Tooltip>
						</div>
						<span class="mt-1 block truncate text-sm text-ink-gray-6">{{ quote?.city || quote?.country || "" }}</span>
					</div>
					<div class="shrink-0 text-right">
						<span class="block text-base font-medium tabular-nums text-ink-gray-8">{{ amount }}</span>
						<span class="mt-1 block text-sm tabular-nums text-ink-gray-6">{{ timeline }}</span>
					</div>
				</div>

				<ul class="mt-5 flex flex-col gap-3 px-2">
					<li v-for="term in terms" :key="term.text" class="flex items-start gap-2 text-pretty text-base text-ink-gray-7">
						<span :class="term.icon" class="mt-0.5 size-4 shrink-0 text-ink-gray-6" aria-hidden="true" />
						<span>{{ term.text }}</span>
					</li>
				</ul>

				<div class="mt-8 flex items-center gap-2 px-2">
					<Checkbox v-model="agreed" size="md" :label="needsAgreement && !agreed ? 'Agree to the terms to hire' : 'I agree to these terms'" />
				</div>
			</div>

			<div v-else class="flex flex-col">
				<div class="flex flex-1 flex-col items-center justify-center pb-6 pt-2 text-center">
					<Avatar :image="quote?.logo" :label="name" size="3xl" shape="square" class="shrink-0 [&_img]:object-contain" />
					<h3 class="mt-3 text-xl font-semibold text-ink-gray-8">Hire request sent to {{ name }}</h3>
					<p class="mt-2 text-base text-ink-gray-6">You’ll get a notification when they reply</p>
				</div>
				<p class="text-base font-medium text-ink-gray-8">What made you choose them?</p>
				<div class="mt-3 flex flex-wrap gap-2">
					<Button v-for="reason in reasons" :key="reason" :label="reason" @click="toggleReason(reason)">
						<template #prefix>
							<span :class="pickedReasons.includes(reason) ? 'lucide-check' : 'lucide-plus'" class="size-4" aria-hidden="true" />
						</template>
					</Button>
				</div>
				<Textarea
					v-if="hasOtherReason"
					v-model="note"
					class="mt-3"
					:rows="3"
					:maxlength="noteLimit"
					placeholder="What else helped you decide?"
					aria-label="What else helped you decide?"
				/>
				<ErrorMessage class="mt-2" :message="reasonError" />
			</div>
		</template>

		<template #actions>
			<div class="flex flex-col gap-2">
				<template v-if="step === 'terms'">
					<Button class="w-full" variant="solid" label="Hire" :loading="hiring" @click="confirmHire" />
					<Button class="w-full" label="Cancel" @click="close" />
				</template>
				<Button v-else class="w-full" variant="solid" label="Done" :loading="savingReasons" @click="sendReasons" />
			</div>
		</template>
	</Dialog>
</template>
