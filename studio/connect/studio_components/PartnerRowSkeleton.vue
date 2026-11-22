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
			<div class="top">
				<Skeleton class="logo" />
				<div class="lines">
					<Skeleton class="line name" />
					<Skeleton class="line city" />
				</div>
				<div class="actions">
					<Skeleton class="save" />
					<Skeleton class="connect" />
				</div>
			</div>
			<Skeleton class="line facts" />
			<Skeleton class="line expertise" />
		</div>
	</div>
</template>

<style scoped>
/* Bars sit where a loaded row's name, city, facts and expertise sit (facts and expertise start
   under the logo), with the same height and dividers, so the list doesn't jump when data arrives. */
.row {
	display: flex;
	flex-direction: column;
	box-sizing: border-box;
	height: 163px;
	padding: 28px 12px 0;
}
.top {
	display: flex;
	gap: 12px;
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
}
.line {
	height: 10px;
	border-radius: 4px;
}
.name {
	width: 28%;
	height: 12px;
	margin-top: 5px;
}
.city {
	width: 18%;
	margin-top: 12px;
}
.facts {
	width: 34%;
	margin-top: 20px;
}
.expertise {
	width: 26%;
	margin-top: 14px;
}
.actions {
	display: flex;
	flex-shrink: 0;
	gap: 8px;
	align-items: flex-start;
}
.save {
	width: 32px;
	height: 32px;
	border-radius: 8px;
}
.connect {
	width: 96px;
	height: 28px;
	margin-top: 2px;
	border-radius: 8px;
}
</style>
