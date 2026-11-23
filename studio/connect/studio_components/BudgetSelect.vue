<script setup>
// A project's budget range, in rupees for a customer in India and in dollars for everyone else. Without
// a country, a saved budget keeps its own currency, and otherwise the browser's time zone decides.
import { computed, watch } from "vue"
import { FormControl } from "frappe-ui"
import { budgetCurrency, budgetIn, budgetOptions, startingBudgetCurrency } from "@app/utils/recommendation"

const props = defineProps({
	modelValue: { type: String, default: "" },
	label: { type: String, default: "Your budget" },
	placeholder: { type: String, default: "Select a range" },
	required: { type: Boolean, default: false },
	error: { type: String, default: "" },
	// The customer's country, when they've given one.
	country: { type: String, default: "" },
})
const emit = defineEmits(["update:modelValue"])

const currency = computed(() =>
	props.country ? startingBudgetCurrency(props.country) : budgetCurrency(props.modelValue) || startingBudgetCurrency(""),
)
const options = computed(() => budgetOptions(currency.value))

// A range picked in the other currency, before the country was given or changed, moves to the same
// range in this one. The picker can be off screen while the country changes, so this also runs on open.
watch(
	currency,
	(next) => {
		const picked = budgetCurrency(props.modelValue)
		if (picked && picked !== next) emit("update:modelValue", budgetIn(props.modelValue, next))
	},
	{ immediate: true },
)
</script>

<template>
	<FormControl
		type="select"
		size="sm"
		:label="label"
		:required="required"
		:model-value="modelValue"
		:options="options"
		:placeholder="placeholder"
		:error="error"
		@update:model-value="emit('update:modelValue', $event || '')"
	/>
</template>
