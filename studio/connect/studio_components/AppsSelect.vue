<script setup>
// The apps a project needs, each with its logo (App.logo), picked from every app on Connect.
// Used by the project questions and by editing sent requirements.
import { onMounted, ref } from "vue"
import { MultiSelect, call } from "frappe-ui"

defineProps({
	modelValue: { type: Array, default: () => [] },
	label: { type: String, default: "Apps" },
	required: { type: Boolean, default: false },
	error: { type: String, default: "" },
})
const emit = defineEmits(["update:modelValue"])

const options = ref([])
const logos = ref({})

onMounted(() => {
	call("connect.api.partner.list_partner_filter_options")
		.then((found) => {
			options.value = (found?.apps || []).map((app) => ({ label: app, value: app }))
			logos.value = found?.app_logos || {}
		})
		.catch(() => {})
})
</script>

<template>
	<MultiSelect
		:model-value="modelValue"
		:label="label"
		:options="options"
		placeholder="Select"
		:required="required"
		:error="error"
		@update:model-value="emit('update:modelValue', $event || [])"
	>
		<template #item-prefix="{ item }">
			<img v-if="logos[item.value]" :src="logos[item.value]" alt="" class="size-4 shrink-0 rounded-sm" />
		</template>
	</MultiSelect>
</template>
