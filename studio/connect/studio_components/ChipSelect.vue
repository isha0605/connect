<script setup>
// A multi-select shown as its picks: a grey box of chips, each with × to remove it, and a chevron
// that opens frappe-ui's MultiSelect list to add more. Used where the Listing edits in place.
import { MultiSelect } from "frappe-ui"

const props = defineProps({
	modelValue: { type: Array, default: () => [] },
	// [{ label, value }]
	options: { type: Array, default: () => [] },
	placeholder: { type: String, default: "Select" },
	label: { type: String, default: "" },
})
const emit = defineEmits(["update:modelValue"])

function update(values) {
	emit("update:modelValue", values || [])
}

function remove(value) {
	update(props.modelValue.filter((picked) => picked !== value))
}
</script>

<template>
	<MultiSelect :model-value="modelValue" :options="options" class="w-full" @update:model-value="update">
		<template #trigger="{ open, selectedOptions, setOpen }">
			<div
				role="combobox"
				tabindex="0"
				:aria-label="label || placeholder"
				:aria-expanded="open"
				class="flex min-h-8 w-full cursor-pointer items-center gap-2 rounded bg-surface-gray-2 px-2 py-1.5 outline-none transition-colors hover:bg-surface-gray-3 focus-visible:ring-2 focus-visible:ring-outline-gray-3"
				@keydown.enter.prevent="setOpen(!open)"
				@keydown.space.prevent="setOpen(!open)"
			>
				<div class="flex min-w-0 flex-1 flex-wrap gap-1.5">
					<span
						v-for="option in selectedOptions"
						:key="option.value"
						class="inline-flex items-center gap-1 rounded bg-surface-white px-1.5 py-0.5 text-sm text-ink-gray-7"
					>
						{{ option.label }}
						<button
							type="button"
							class="lucide-x size-3 text-ink-gray-5 hover:text-ink-gray-8"
							:aria-label="`Remove ${option.label}`"
							@click.stop="remove(option.value)"
							@keydown.enter.stop
						/>
					</span>
					<span v-if="!selectedOptions.length" class="text-base text-ink-gray-4">{{ placeholder }}</span>
				</div>
				<span class="lucide-chevron-down size-4 shrink-0 text-ink-gray-4" aria-hidden="true" />
			</div>
		</template>
	</MultiSelect>
</template>
