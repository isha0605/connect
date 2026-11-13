<script setup>
// The Listing's photo and video editor: tiles in gallery order (the first is the cover), dragged
// or moved from each tile's menu, with Replace and Remove. It only builds the list; the page saves
// it with the rest of the listing. A video's first frame is uploaded as its poster, which the
// profile's tiles show.
import { computed, ref } from "vue"
import { Badge, Button, Dropdown, toast, useFileUpload } from "frappe-ui"
import { MAX_GALLERY_PHOTOS, MAX_GALLERY_VIDEOS, MAX_IMAGE_BYTES, MAX_VIDEO_BYTES } from "@app/utils/partnerProfile"

const VIDEO_TYPES = ["video/mp4", "video/webm"]
const ACCEPT = `image/*,${VIDEO_TYPES.join(",")}`
// Far enough in to miss a black first frame, near enough to fit any clip.
const POSTER_AT_SECONDS = 0.5

const props = defineProps({
	// [{ image, video }]: a photo has only an image; a video has its poster as the image
	photos: { type: Array, default: () => [] },
})
const emit = defineEmits(["change", "uploading"])

const uploadingAt = ref(null) // the index being replaced, or "new"
const draggedIndex = ref(null)
const dropIndex = ref(null)

const isVideo = (photo) => !!photo.video
const videoCount = computed(() => props.photos.filter(isVideo).length)
const photoCount = computed(() => props.photos.length - videoCount.value)
const maxItems = MAX_GALLERY_PHOTOS + MAX_GALLERY_VIDEOS
const isFull = computed(() => props.photos.length >= maxItems)
const countLabel = computed(() => `${props.photos.length} of ${maxItems}`)

function change(photos) {
	emit("change", photos)
}

function move(from, to) {
	if (to < 0 || to >= props.photos.length || from === to) return
	const photos = [...props.photos]
	photos.splice(to, 0, photos.splice(from, 1)[0])
	change(photos)
}

function remove(index) {
	change(props.photos.filter((_photo, i) => i !== index))
}

function menuFor(index) {
	return [
		{ label: "Move earlier", icon: "lucide-chevron-left", condition: () => index > 0, onClick: () => move(index, index - 1) },
		{
			label: "Move later",
			icon: "lucide-chevron-right",
			condition: () => index < props.photos.length - 1,
			onClick: () => move(index, index + 1),
		},
		{ label: "Replace", icon: "lucide-replace", onClick: () => pickFile(index) },
		{ label: "Remove", icon: "lucide-trash-2", theme: "red", onClick: () => remove(index) },
	]
}

// ---- Drag to reorder ----

function onDragStart(index, event) {
	draggedIndex.value = index
	event.dataTransfer.effectAllowed = "move"
	// Firefox starts a drag only when it carries data.
	event.dataTransfer.setData("text/plain", String(index))
}

function onDragOver(index) {
	if (draggedIndex.value !== null) dropIndex.value = index
}

function onDrop(index) {
	if (draggedIndex.value !== null) move(draggedIndex.value, index)
	onDragEnd()
}

function onDragEnd() {
	draggedIndex.value = null
	dropIndex.value = null
}

// ---- Adding and replacing ----

// Why `file` can't go at `index` (null to add it), or "".
function fileProblem(file, index) {
	const replaced = index === null ? null : props.photos[index]
	if (VIDEO_TYPES.includes(file.type)) {
		if (file.size > MAX_VIDEO_BYTES) return "Videos must be under 25 MB."
		const others = videoCount.value - (replaced && isVideo(replaced) ? 1 : 0)
		return others >= MAX_GALLERY_VIDEOS ? `You can add up to ${MAX_GALLERY_VIDEOS} videos.` : ""
	}
	if (!file.type.startsWith("image/")) return "Upload a photo, or an MP4 or WebM video."
	if (file.size > MAX_IMAGE_BYTES) return "Images must be under 5 MB."
	const others = photoCount.value - (replaced && !isVideo(replaced) ? 1 : 0)
	return others >= MAX_GALLERY_PHOTOS ? `You can add up to ${MAX_GALLERY_PHOTOS} photos.` : ""
}

function pickFile(index = null) {
	if (uploadingAt.value !== null) return
	const input = document.createElement("input")
	input.type = "file"
	input.accept = ACCEPT
	input.onchange = () => {
		const file = input.files?.[0]
		if (file) addFile(file, index)
	}
	input.click()
}

async function addFile(file, index) {
	const problem = fileProblem(file, index)
	if (problem) {
		toast.error(problem)
		return
	}

	setUploading(index === null ? "new" : index)
	try {
		const photo = VIDEO_TYPES.includes(file.type) ? await uploadVideo(file) : { image: await upload(file), video: "" }
		change(index === null ? [...props.photos, photo] : props.photos.map((p, i) => (i === index ? photo : p)))
	} catch (error) {
		toast.error(error?.userMessage || "Couldn't upload that file. Try again.")
	} finally {
		setUploading(null)
	}
}

function setUploading(at) {
	uploadingAt.value = at
	emit("uploading", at !== null)
}

async function upload(file) {
	const uploaded = await useFileUpload().upload(file, { private: false })
	return uploaded.file_url || ""
}

async function uploadVideo(file) {
	const poster = await capturePoster(file)
	const [video, image] = await Promise.all([upload(file), upload(poster)])
	return { image, video }
}

// The video's frame at POSTER_AT_SECONDS, as a JPEG, read from the file before it's uploaded.
function capturePoster(file) {
	return new Promise((resolve, reject) => {
		const url = URL.createObjectURL(file)
		const video = document.createElement("video")
		const fail = () => {
			URL.revokeObjectURL(url)
			reject(Object.assign(new Error("unreadable video"), { userMessage: "Couldn't read that video. Try an MP4 file." }))
		}
		video.muted = true
		video.playsInline = true
		video.preload = "auto"
		video.onerror = fail
		video.onloadedmetadata = () => {
			video.currentTime = Math.min(POSTER_AT_SECONDS, (video.duration || 0) / 2)
		}
		video.onseeked = () => {
			const canvas = document.createElement("canvas")
			canvas.width = video.videoWidth
			canvas.height = video.videoHeight
			canvas.getContext("2d").drawImage(video, 0, 0)
			canvas.toBlob(
				(blob) => {
					URL.revokeObjectURL(url)
					if (!blob) return fail()
					resolve(new File([blob], `${file.name.replace(/\.[^.]+$/, "")}-poster.jpg`, { type: "image/jpeg" }))
				},
				"image/jpeg",
				0.85,
			)
		}
		video.src = url
	})
}
</script>

<template>
	<section class="flex flex-col gap-4" aria-label="Photos and video">
		<div class="flex items-center justify-between gap-3">
			<div class="flex items-center gap-2">
				<h3 class="text-base font-semibold text-ink-gray-9">Photos and video</h3>
				<Badge :label="countLabel" theme="gray" />
			</div>
			<Button
				variant="subtle"
				icon-left="lucide-plus"
				:label="uploadingAt === 'new' ? 'Uploading…' : 'Add photo or video'"
				:loading="uploadingAt === 'new'"
				:disabled="isFull || uploadingAt !== null"
				@click="pickFile()"
			/>
		</div>

		<p class="text-p-sm text-ink-gray-5">
			The first is your cover. Drag to reorder, or use each tile's menu. Up to {{ MAX_GALLERY_PHOTOS }} photos
			and {{ MAX_GALLERY_VIDEOS }} videos.
		</p>

		<ol v-if="photos.length || uploadingAt === 'new'" class="grid grid-cols-2 gap-3 sm:grid-cols-4">
			<li
				v-for="(photo, index) in photos"
				:key="`${index}-${photo.video || photo.image}`"
				class="group relative aspect-[16/10] overflow-hidden rounded-lg bg-surface-gray-2 transition-opacity"
				:class="{
					'opacity-40': draggedIndex === index,
					'ring-2 ring-outline-gray-4': dropIndex === index && draggedIndex !== index,
					'cursor-grab': uploadingAt === null,
				}"
				:draggable="uploadingAt === null"
				@dragstart="onDragStart(index, $event)"
				@dragover.prevent="onDragOver(index)"
				@drop.prevent="onDrop(index)"
				@dragend="onDragEnd"
			>
				<img
					v-if="photo.image"
					:src="photo.image"
					:alt="isVideo(photo) ? `Video ${index + 1}` : `Photo ${index + 1}`"
					class="pointer-events-none size-full object-cover"
				/>
				<video
					v-else-if="photo.video"
					:src="photo.video"
					preload="metadata"
					muted
					class="pointer-events-none size-full object-cover"
				/>

				<span
					v-if="index === 0"
					class="absolute left-2 top-2 rounded-md bg-surface-white px-1.5 py-0.5 text-xs font-medium text-ink-gray-8"
				>
					Cover
				</span>
				<span
					v-if="isVideo(photo)"
					class="lucide-play absolute bottom-2 left-2 size-4 text-ink-white drop-shadow"
					aria-label="Video"
				/>
				<div
					v-if="uploadingAt === index"
					class="absolute inset-0 flex items-center justify-center text-sm text-ink-gray-8"
					style="background: rgb(255 255 255 / 0.7)"
				>
					Uploading…
				</div>

				<div class="absolute right-2 top-2">
					<Dropdown :options="menuFor(index)" align="end">
						<Button
							variant="outline"
							size="sm"
							icon="lucide-more-horizontal"
							class="bg-surface-white"
							:aria-label="`More for ${isVideo(photo) ? 'video' : 'photo'} ${index + 1}`"
							:disabled="uploadingAt !== null"
						/>
					</Dropdown>
				</div>
			</li>

			<li
				v-if="uploadingAt === 'new'"
				class="flex aspect-[16/10] items-center justify-center rounded-lg bg-surface-gray-2 text-sm text-ink-gray-6"
			>
				Uploading…
			</li>
		</ol>

		<p v-else class="text-p-sm text-ink-gray-5">No photos or videos yet.</p>
	</section>
</template>
