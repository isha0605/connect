<script setup>
// frappe-ui's ScrollArea for Studio pages: a thin scrollbar that shows while scrolling, in place of the
// browser's. Studio doesn't offer ScrollArea as a block, so a page places this and puts its blocks in the slot.
import { ScrollArea } from "frappe-ui"
</script>

<template>
	<ScrollArea>
		<slot />
	</ScrollArea>
</template>
