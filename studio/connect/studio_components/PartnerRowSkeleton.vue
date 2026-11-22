<script setup>
// Placeholder rows shaped like a partner directory row, shown until the first partner list arrives.
import { Skeleton } from "frappe-ui"

defineProps({
	rows: { type: Number, default: 3 },
})
</script>

<template>
	<div class="partner-row-skeleton" aria-busy="true" aria-label="Loading partners">
		<div v-for="row in rows" :key="row" class="row">
			<Skeleton class="logo" />
			<div class="lines">
				<Skeleton class="line name" />
				<Skeleton class="line city" />
				<Skeleton class="line facts" />
			</div>
		</div>
	</div>
</template>

<style scoped>
/* Same height and dividers as a loaded partner row, so the list doesn't jump when data arrives. */
.row {
	display: flex;
	gap: 12px;
	box-sizing: border-box;
	height: 163px;
	padding: 28px 12px 29px;
}
.row + .row {
	border-top: 1px solid var(--outline-gray-1);
}
.logo {
	width: 40px;
	height: 40px;
	flex-shrink: 0;
	border-radius: 8px;
}
.lines {
	display: flex;
	flex: 1;
	flex-direction: column;
	gap: 8px;
	padding-top: 3px;
}
.line {
	height: 12px;
	border-radius: 4px;
}
.name {
	width: 30%;
}
.city {
	width: 18%;
}
.facts {
	width: 45%;
	margin-top: 10px;
}
</style>
