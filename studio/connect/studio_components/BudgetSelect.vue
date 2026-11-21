<script setup>
// A project's budget range, in rupees or dollars. The ₹ / $ switch starts on the customer's country
// (or, without one, their browser's time zone) and keeps the same range when it changes.
import { computed, ref, useId, watch } from "vue"
import { FormControl, FormLabel, TabButtons } from "frappe-ui"
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

const CURRENCIES = [
	{ label: "₹", value: "INR" },
	{ label: "$", value: "USD" },
]

const id = useId()
const currency = ref(budgetCurrency(props.modelValue) || startingBudgetCurrency(props.country))
const options = computed(() => budgetOptions(currency.value))

// A saved budget or the customer's country can arrive after the form opens. Each moves the switch
// to it, but never after the customer has moved it themselves.
let isSetByCustomer = false
watch(
	() => [props.modelValue, props.country],
	() => {
		const saved = budgetCurrency(props.modelValue)
		if (saved) currency.value = saved
		else if (!isSetByCustomer) currency.value = startingBudgetCurrency(props.country)
	},
)

function switchTo(next) {
	isSetByCustomer = true
	currency.value = next
	if (props.modelValue) emit("update:modelValue", budgetIn(props.modelValue, next))
}
</script>

<template>
	<div class="space-y-1.5">
		<div class="flex items-center justify-between gap-2">
			<FormLabel :id="id" :label="label" :required="required" />
			<TabButtons :options="CURRENCIES" :model-value="currency" aria-label="Budget currency" @update:model-value="switchTo" />
		</div>
		<FormControl
			:id="id"
			type="select"
			size="sm"
			:model-value="modelValue"
			:options="options"
			:placeholder="placeholder"
			:error="error"
			@update:model-value="emit('update:modelValue', $event || '')"
		/>
	</div>
</template>
