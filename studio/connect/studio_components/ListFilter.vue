<script setup>
// A list's Filter button, as Frappe CRM's: the number of filters on it, and a popover of
// "Where field / operator / value" rows with Add Filter and Clear all filters. It only builds the
// filters (v-model); the page applies them with utils/listFilters.
import { computed } from "vue"
import { Button, Combobox, DatePicker, Icon, Popover, Select, TextInput } from "frappe-ui"
import { OPERATORS, needsValue, newFilter } from "@app/utils/listFilters"

const props = defineProps({
	// [{ fieldname, label, type: "text" | "select" | "date", options }]
	fields: { type: Array, default: () => [] },
	modelValue: { type: Array, default: () => [] },
})
const emit = defineEmits(["update:modelValue"])

const TYPING_DELAY_MS = 300
let typingTimer = null

const fieldOptions = computed(() => props.fields.map((field) => ({ label: field.label, value: field.fieldname })))
const fieldOf = (fieldname) => props.fields.find((field) => field.fieldname === fieldname)
const operatorsOf = (filter) => OPERATORS[fieldOf(filter.fieldname)?.type || "text"]
const typeOf = (filter) => fieldOf(filter.fieldname)?.type || "text"

function update(filters) {
	emit("update:modelValue", filters)
}

function replace(index, filter) {
	update(props.modelValue.map((current, i) => (i === index ? filter : current)))
}

function addFilter(fieldname) {
	if (fieldname) update([...props.modelValue, newFilter(fieldOf(fieldname))])
}

function setField(index, fieldname) {
	if (fieldname) replace(index, newFilter(fieldOf(fieldname)))
}

function setPart(index, part, value) {
	replace(index, { ...props.modelValue[index], [part]: value ?? "" })
}

// Typing filters the list once the person pauses, not on every key.
function setTypedValue(index, value) {
	clearTimeout(typingTimer)
	typingTimer = setTimeout(() => setPart(index, "value", value), TYPING_DELAY_MS)
}

function remove(index) {
	update(props.modelValue.filter((_, i) => i !== index))
}
</script>

<template>
	<div class="flex items-center">
		<Popover align="end">
			<template #trigger>
				<Button
					label="Filter"
					icon-left="lucide-list-filter"
					:class="modelValue.length ? 'rounded-r-none' : ''"
				>
					<template v-if="modelValue.length" #suffix>
						<span
							class="grid size-5 place-items-center rounded-[5px] bg-surface-base text-xs font-medium text-ink-gray-8 shadow-sm"
						>
							{{ modelValue.length }}
						</span>
					</template>
				</Button>
			</template>

			<div class="min-w-72 p-2 sm:min-w-[400px]">
				<div
					v-for="(filter, index) in modelValue"
					:key="index"
					class="mb-4 flex flex-wrap items-center gap-2 sm:mb-3 sm:flex-nowrap"
				>
					<span class="w-12 shrink-0 text-end text-base text-ink-gray-5">
						{{ index === 0 ? "Where" : "And" }}
					</span>
					<Combobox
						class="w-36"
						aria-label="Field"
						:model-value="filter.fieldname"
						:options="fieldOptions"
						@update:model-value="setField(index, $event)"
					/>
					<Select
						class="w-32"
						aria-label="Operator"
						:model-value="filter.operator"
						:options="operatorsOf(filter)"
						@update:model-value="setPart(index, 'operator', $event)"
					/>
					<div class="w-40">
						<template v-if="needsValue(filter.operator)">
							<Select
								v-if="typeOf(filter) === 'select'"
								class="w-full"
								aria-label="Value"
								placeholder="Select"
								:model-value="filter.value"
								:options="fieldOf(filter.fieldname).options"
								@update:model-value="setPart(index, 'value', $event)"
							/>
							<DatePicker
								v-else-if="typeOf(filter) === 'date'"
								aria-label="Date"
								placeholder="Date"
								:model-value="filter.value"
								@update:model-value="setPart(index, 'value', $event)"
							/>
							<TextInput
								v-else
								aria-label="Value"
								placeholder="Value"
								:model-value="filter.value"
								@update:model-value="setTypedValue(index, $event)"
							/>
						</template>
					</div>
					<Button variant="ghost" icon="lucide-x" aria-label="Remove filter" @click="remove(index)" />
				</div>

				<p v-if="!modelValue.length" class="mb-3 flex h-7 items-center px-3 text-sm text-ink-gray-5">
					Empty - Choose a field to filter by
				</p>

				<div class="flex items-center justify-between gap-2">
					<Combobox
						trigger="button"
						variant="ghost"
						placeholder="Add Filter"
						:model-value="null"
						:options="fieldOptions"
						@update:model-value="addFilter"
					>
						<template #prefix>
							<Icon icon="lucide-plus" class="size-4 text-ink-gray-5" />
						</template>
						<!-- no chevron: CRM's Add Filter is a plain button -->
						<template #suffix><span /></template>
					</Combobox>
					<Button
						v-if="modelValue.length"
						class="!text-ink-gray-5"
						variant="ghost"
						label="Clear all filters"
						@click="update([])"
					/>
				</div>
			</div>
		</Popover>
		<Button
			v-if="modelValue.length"
			class="rounded-l-none border-l"
			icon="lucide-x"
			aria-label="Clear all filters"
			@click="update([])"
		/>
	</div>
</template>
