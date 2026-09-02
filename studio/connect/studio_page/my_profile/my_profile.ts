import { computed, ref, watch } from "vue"
import { toast, call, useFileUpload } from "frappe-ui"

export default function setup(context) {
	// ---- Profile settings popup (sidebar avatar) ----
	// Mirrors the same feature on find_partners/shortlisted/messaging — kept in sync there
	// since Studio pages don't share component logic, only markup/state shape by convention.
	// Named distinctly from this page's own editPartnerName/saveMyProfile/savingProfile (which
	// edit the Partner *business* profile via the tabs below): this dialog edits the logged-in
	// user's own account (name/phone/role) plus their company roster, an unrelated concern that
	// happens to share the same sidebar entry point on every page.
	const showProfileSettingsDialog = ref(false)
	const profileSettingsSection = ref("profile")
	const editFullName = ref("")
	const editPhone = ref("")
	const editRole = ref("")
	const originalFullName = ref("")
	const originalPhone = ref("")
	const originalRole = ref("")
	const savingAccountProfile = ref(false)
	const uploadingProfileImage = ref(false)
	const showAddTeamMemberDialog = ref(false)
	const newTeamMemberEmail = ref("")
	const newTeamMemberRole = ref("")
	const newTeamMemberPassword = ref("")
	const addingTeamMember = ref(false)
	const showDisableTeamMemberDialog = ref(false)
	const memberToDisable = ref(null)
	const disablingTeamMember = ref(false)

	function isPartnerAdmin() {
		return !!(context.myContext.data && context.myContext.data.partner && context.myContext.data.partner.is_admin)
	}

	function isCustomerAdmin() {
		return !!(context.myContext.data && context.myContext.data.customer && context.myContext.data.customer.is_admin)
	}

	function isAnyAdmin() {
		return isPartnerAdmin() || isCustomerAdmin()
	}

	function openProfileSettings() {
		profileSettingsSection.value = "profile"
		const account = context.myAccount.data
		editFullName.value = (account && account.full_name) || ""
		editPhone.value = (account && account.phone) || ""
		editRole.value = (account && account.role) || ""
		originalFullName.value = editFullName.value
		originalPhone.value = editPhone.value
		originalRole.value = editRole.value
		showProfileSettingsDialog.value = true
	}

	function selectProfileSettingsSection(section) {
		profileSettingsSection.value = section
	}

	async function saveMyAccountProfile() {
		const fullName = editFullName.value.trim()
		if (!fullName || savingAccountProfile.value) return
		savingAccountProfile.value = true
		try {
			await call("connect.api.account.update_my_profile", {
				full_name: fullName,
				phone: editPhone.value.trim(),
				role: editRole.value.trim(),
			})
			await context.myAccount.reload()
			originalFullName.value = editFullName.value
			originalPhone.value = editPhone.value
			originalRole.value = editRole.value
			toast({ title: "Profile updated", icon: "check", iconClasses: "text-green-600" })
		} catch (e) {
			toast({
				title: "Could not update profile",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			savingAccountProfile.value = false
		}
	}

	// picking a new avatar happens the same way as the company logo below — a throwaway
	// <input> is the smallest way to reach the browser's native file dialog.
	function openProfileImagePicker() {
		if (uploadingProfileImage.value) return
		const input = document.createElement("input")
		input.type = "file"
		input.accept = "image/*"
		input.style.display = "none"
		input.addEventListener("change", () => {
			const file = input.files && input.files[0]
			if (file) uploadProfileImage(file)
			input.remove()
		})
		document.body.appendChild(input)
		input.click()
	}

	function uploadProfileImage(file) {
		uploadingProfileImage.value = true
		const { upload } = useFileUpload()
		upload(file, { upload_endpoint: "/api/method/connect.api.account.upload_profile_image" })
			.then(() => {
				context.myAccount.reload()
				toast({ title: "Photo updated", icon: "check", iconClasses: "text-green-600" })
			})
			.catch((e) => {
				toast({
					title: "Could not upload photo",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			})
			.finally(() => {
				uploadingProfileImage.value = false
			})
	}

	function teamRowOptions(item) {
		const me = context.myContext.data && context.myContext.data.user
		const disabled = !isAnyAdmin() || item.user === me
		return [
			{ label: "Disable", icon: "lucide-user-minus", theme: "red", disabled, onClick: () => confirmDisableTeamMember(item) },
		]
	}

	function confirmDisableTeamMember(item) {
		memberToDisable.value = item
		showDisableTeamMemberDialog.value = true
	}

	async function disableTeamMember() {
		if (!memberToDisable.value || disablingTeamMember.value) return
		disablingTeamMember.value = true
		try {
			await call("connect.api.account.remove_team_member", { member: memberToDisable.value.name })
			showDisableTeamMemberDialog.value = false
			memberToDisable.value = null
			context.myTeam.reload()
			toast({ title: "Team member disabled", icon: "check", iconClasses: "text-green-600" })
		} catch (e) {
			toast({
				title: "Could not disable team member",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			disablingTeamMember.value = false
		}
	}

	async function addTeamMember() {
		if (!newTeamMemberEmail.value) {
			toast({ title: "Enter an email", icon: "x-circle", iconClasses: "text-red-600" })
			return
		}
		addingTeamMember.value = true
		try {
			const data = await call("connect.api.account.add_team_member", {
				email: newTeamMemberEmail.value,
				role: newTeamMemberRole.value || null,
				password: newTeamMemberPassword.value || null,
			})
			showAddTeamMemberDialog.value = false
			newTeamMemberEmail.value = ""
			newTeamMemberRole.value = ""
			newTeamMemberPassword.value = ""
			context.myTeam.reload()
			toast({
				title: data && data.created_user ? "New account created and added" : "Team member added",
				icon: "check",
				iconClasses: "text-green-600",
			})
		} catch (e) {
			toast({
				title: "Could not add team member",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			addingTeamMember.value = false
		}
	}

	// ---- Live-editable copies of the Partner doc ----
	// Populated once myProfile resolves (see populateFromProfile below), and bound directly
	// to both the form inputs on the right and the live-preview card on the left, so the
	// preview updates as the partner types instead of lagging behind the saved record.
	const editLogo = ref("")
	// CSS background-position percentages for the logo box — lets a partner drag their logo
	// around to reframe it instead of it always sitting dead-centered/cropped.
	const editLogoPositionX = ref(50)
	const editLogoPositionY = ref(50)
	const editPartnerName = ref("")
	const editTagline = ref("")
	const editDescription = ref("")
	const editCountry = ref("")
	const editCity = ref("")
	const editAddress = ref("")
	const editWebsite = ref("")
	const editIndustry = ref("")
	const editYearFounded = ref("")
	const editRollouts = ref("")
	const editHourlyRate = ref("")
	const editResponseTimeHours = ref("")
	const editSitesDeployed = ref("")
	const editTypicalProjectSize = ref("")
	const editProposalTimeline = ref("")
	const editCertifiedExperts = ref("")
	const editCertsErpnext = ref("")
	const editCertsFrappeFramework = ref("")
	const editCountriesServed = ref("")
	const editReferencesCount = ref("")
	const editStarterPack = ref(false)
	const editDemoAvailable = ref(false)
	// Table MultiSelect fields (apps/migrations/business_processes/languages) come back from
	// get_partner_document as rows like [{app: "ERPNext"}, ...] — these refs hold just the
	// flat list of title strings, same shape filterOptions returns, so the "does this chip
	// include me" check in the tag pickers is a plain .includes().
	const editApps = ref([])
	// Same field the customer-facing partner-profile sidebar shows as "Migration Paths" —
	// kept alongside Apps & Frameworks here for the same reason it sits next to it there.
	const editMigrations = ref([])
	const editBusinessProcesses = ref([])
	const editLanguages = ref([])

	// Which of the About / Success Stories / Reviews / Pricing tabs is showing — mirrors the
	// same tab set (and the same activeTab-driven show/hide pattern) as the customer-facing
	// partner-profile page, just editable here instead of read-only.
	const activeTab = ref("about")

	// Founder's Story is a single row in the "team" child table (the one with is_founder set),
	// pulled out into its own flat fields the same way the other child-table-backed sections are.
	const editFounderName = ref("")
	const editFounderDesignation = ref("")
	const editFounderBio = ref("")
	const editFounderPhoto = ref("")

	// Success stories / packs / add-ons are edited as "current list + add-new mini-form", not
	// inline-editable rows — Studio's TextInput modelValue only binds to a named variable, not
	// to an arbitrary dataItem.field path, so a per-row two-way-bound table isn't an option here.
	const editSuccessStories = ref([])
	// Same category-filter pattern as the customer-facing partner-profile page's Success
	// Stories tab — "All" plus whichever categories this partner's own stories actually use.
	const successStoryCategory = ref("All")
	const newStoryClientName = ref("")
	const newStoryClientLogo = ref("")
	const newStoryHeadline = ref("")
	const newStoryCategory = ref("")
	const newStoryUrl = ref("")

	// Same "prove it with case studies" bar the customer-facing partner-profile page's
	// backend applies (see _compute_display_industries in partner.py): a success-story
	// category needs at least 2 stories before it's surfaced as an Industry tag. Computed
	// client-side too (not just read off the saved record) so the left preview reacts
	// immediately as the partner adds/removes stories here, same as the rest of this card.
	const displayIndustries = computed(() => {
		const counts = {}
		for (const story of editSuccessStories.value) {
			const category = (story.category || "").trim()
			if (category) counts[category] = (counts[category] || 0) + 1
		}
		const industries = []
		if (editIndustry.value) industries.push(editIndustry.value)
		for (const category in counts) {
			if (counts[category] >= 2 && !industries.includes(category)) industries.push(category)
		}
		return industries
	})

	// Star row for the Reviews tab's rating summary — filled stars for the rounded rating,
	// hollow for the rest, always five total.
	const starRating = computed(() => {
		const rounded = Math.max(0, Math.min(5, Math.round(Number((context.myProfile.data && context.myProfile.data.rating) || 0))))
		return "★".repeat(rounded) + "☆".repeat(5 - rounded)
	})

	// Reviews-over-time chart (partner portal only — not shown on the customer-facing
	// partner profile). AxisChart (frappe-ui 1.0.0-beta.25) doesn't bucket/aggregate data
	// itself — timeGrain only affects axis label formatting — so counts are pre-aggregated
	// into {period, count} rows here, keyed by the selected grain.
	const reviewChartGrain = ref("month")

	const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

	// One area per rating dimension (not stacked — these are independent 1-5 averages, not
	// additive quantities), each period's value being that dimension's average among reviews
	// that actually supplied it that period (reviews from the live form never do — see
	// _compute_display_industries-style "0 means nobody rated it" convention in partner.py).
	const REVIEW_DIMENSIONS = [
		{ key: "business_understanding", color: "#4f46e5" },
		{ key: "implementation_quality", color: "#0ea5e9" },
		{ key: "communication", color: "#10b981" },
		{ key: "timeliness", color: "#f59e0b" },
		{ key: "support", color: "#ef4444" },
		{ key: "technical_expertise", color: "#a855f7" },
	]

	const FALLBACK_CHART_CONFIG = {
		data: [],
		xAxis: { key: "period", type: "category" },
		yAxis: {},
		series: [],
	}

	const reviewChartConfig = computed(() => {
		try {
			const reviews = context.myReviews.data || []
			const buckets = {}
			for (const r of reviews) {
				if (!r.reviewed_on) continue
				const d = new Date(r.reviewed_on)
				if (isNaN(d.getTime())) continue
				const key =
					reviewChartGrain.value === "year"
						? String(d.getFullYear())
						: d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0")
				if (!buckets[key]) {
					buckets[key] = { sums: {}, counts: {} }
					for (const dim of REVIEW_DIMENSIONS) {
						buckets[key].sums[dim.key] = 0
						buckets[key].counts[dim.key] = 0
					}
				}
				for (const dim of REVIEW_DIMENSIONS) {
					const value = r[dim.key]
					if (value) {
						buckets[key].sums[dim.key] += value
						buckets[key].counts[dim.key] += 1
					}
				}
			}
			const periods = Object.keys(buckets).sort()
			const data = periods.map((key) => {
				let label = key
				if (reviewChartGrain.value === "month") {
					const [y, m] = key.split("-")
					label = MONTH_NAMES[Number(m) - 1] + " " + y
				}
				const row = { period: label }
				for (const dim of REVIEW_DIMENSIONS) {
					const { sums, counts } = buckets[key]
					row[dim.key] = counts[dim.key] ? Math.round((sums[dim.key] / counts[dim.key]) * 10) / 10 : 0
				}
				return row
			})
			return {
				data,
				xAxis: { key: "period", type: "category", title: reviewChartGrain.value === "year" ? "Year" : "Month" },
				yAxis: { title: "Average Score", yMin: 0, yMax: 5 },
				series: REVIEW_DIMENSIONS.map((dim) => ({
					name: dim.key,
					type: "area",
					color: dim.color,
					fillOpacity: 0.15,
					showDataPoints: true,
				})),
			}
		} catch (e) {
			console.error("reviewChartConfig failed:", e)
			return FALLBACK_CHART_CONFIG
		}
	})

	const editPacks = ref([])
	const newPackKey = ref("")
	const newPackName = ref("")
	const newPackPrice = ref("")
	const newPackHours = ref("")
	const newPackValidityDays = ref("")
	const newPackIncludesSummary = ref("")

	const editAddons = ref([])
	const newAddonName = ref("")
	const newAddonHours = ref("")

	const savingProfile = ref(false)

	function populateFromProfile() {
		const p = context.myProfile.data
		if (!p) return
		editLogo.value = p.logo || ""
		editLogoPositionX.value = p.logo_position_x ?? 50
		editLogoPositionY.value = p.logo_position_y ?? 50
		editPartnerName.value = p.partner_name || ""
		editTagline.value = p.tagline || ""
		editDescription.value = p.description || ""
		editCountry.value = p.country || ""
		editCity.value = p.city || ""
		editAddress.value = p.address || ""
		editWebsite.value = p.website || ""
		editIndustry.value = p.industry || ""
		editYearFounded.value = p.year_founded || ""
		editRollouts.value = p.rollouts || ""
		editHourlyRate.value = p.hourly_rate || ""
		editResponseTimeHours.value = p.response_time_hours || ""
		editSitesDeployed.value = p.sites_deployed || ""
		editTypicalProjectSize.value = p.typical_project_size || ""
		editProposalTimeline.value = p.proposal_timeline || ""
		editCertifiedExperts.value = p.certified_experts || ""
		editCertsErpnext.value = p.certs_erpnext || ""
		editCertsFrappeFramework.value = p.certs_frappe_framework || ""
		editCountriesServed.value = p.countries_served || ""
		editReferencesCount.value = p.references_count || ""
		editStarterPack.value = !!p.starter_pack
		editDemoAvailable.value = !!p.demo_available
		editApps.value = (p.apps || []).map((row) => row.app)
		editMigrations.value = (p.migrations || []).map((row) => row.migration_path)
		editBusinessProcesses.value = (p.business_processes || []).map((row) => row.business_process)
		editLanguages.value = (p.languages || []).map((row) => row.language)

		const founder = (p.team || []).find((row) => row.is_founder) || {}
		editFounderName.value = founder.member_name || ""
		editFounderDesignation.value = founder.designation || ""
		editFounderBio.value = founder.bio || ""
		editFounderPhoto.value = founder.photo || ""

		editSuccessStories.value = (p.success_stories || []).map((row) => ({
			client_name: row.client_name,
			client_logo: row.client_logo,
			headline: row.headline,
			category: row.category,
			url: row.url,
		}))
		editPacks.value = (p.packs || []).map((row) => ({
			pack_key: row.pack_key,
			pack_name: row.pack_name,
			price: row.price,
			hours: row.hours,
			validity_days: row.validity_days,
			includes_summary: row.includes_summary,
		}))
		editAddons.value = (p.addons || []).map((row) => ({
			addon_name: row.addon_name,
			typical_hours: row.typical_hours,
		}))
	}

	watch(() => context.myProfile.data, populateFromProfile, { immediate: true })

	// myProfile's own params are bound (see the page JSON) to myContext.data.partner.partner,
	// which is null until myContext resolves — so the resource is deliberately left off "auto"
	// and fetched here explicitly, once, the moment a partner id actually exists. Doing it this
	// way (an explicit .reload() gated on the dependency, same as every other cross-resource
	// .reload() in this codebase) avoids firing the fetch early with an empty partner id.
	// Passing the partner id straight into reload() (rather than calling reload() bare)
	// matters here: Studio's own internal params-sync watcher and this one both react to
	// the same myContext.data change, and bare reload() falls back to the resource's
	// current internal params — which is a race if Studio's watcher hasn't updated it
	// yet. Passing params explicitly sidesteps that race entirely.
	watch(
		() => context.myContext.data,
		(val) => {
			if (val && val.partner && val.partner.partner) {
				context.myProfile.reload({ partner: val.partner.partner })
				context.myReviews.reload({ partner: val.partner.partner })
			}
		},
		{ immediate: true },
	)

	// Same "redirect out if the role doesn't match" shape used elsewhere in this codebase
	// (e.g. the Contact Partner / shortlist actions redirecting guests to /login), just
	// applied to the whole page instead of a single action, since this page only makes
	// sense for a logged-in partner.
	watch(
		() => context.myContext.fetched && !(context.myContext.data && context.myContext.data.partner),
		(shouldRedirect) => {
			if (shouldRedirect) {
				window.location.href = "/login?redirect-to=" + encodeURIComponent(window.location.pathname)
			}
		},
		{ immediate: true },
	)

	// Set (not toggle) membership from the checkbox's own emitted checked state — the
	// installed frappe-ui Checkbox both assigns its defineModel() ref (which auto-emits
	// update:modelValue) AND explicitly re-emits update:modelValue itself, so every click
	// fires this handler twice. A blind toggle would cancel itself out on the second call;
	// setting explicitly from eventArgs[0] is idempotent regardless of how many times it fires.
	function setInList(list, value, checked) {
		const cur = list.value || []
		if (checked) {
			if (!cur.includes(value)) list.value = [...cur, value]
		} else if (cur.includes(value)) {
			list.value = cur.filter((v) => v !== value)
		}
	}

	function toggleApp(value, checked) {
		setInList(editApps, value, checked)
	}

	function toggleMigration(value, checked) {
		setInList(editMigrations, value, checked)
	}

	function toggleBusinessProcess(value, checked) {
		setInList(editBusinessProcesses, value, checked)
	}

	function toggleLanguage(value, checked) {
		setInList(editLanguages, value, checked)
	}

	// Classifications are now "pick from dropdown, click +" instead of a full checkbox grid —
	// selected values render as removable chips (via the toggle* functions above, called with
	// checked=false) below each dropdown.
	const newAppSelection = ref("")
	const newMigrationSelection = ref("")
	const newBusinessProcessSelection = ref("")
	const newLanguageSelection = ref("")

	function addToList(list, valueRef) {
		const value = valueRef.value
		if (value && !list.value.includes(value)) list.value = [...list.value, value]
		valueRef.value = ""
	}

	function addApp() {
		addToList(editApps, newAppSelection)
	}

	function addMigration() {
		addToList(editMigrations, newMigrationSelection)
	}

	function addBusinessProcess() {
		addToList(editBusinessProcesses, newBusinessProcessSelection)
	}

	function addLanguage() {
		addToList(editLanguages, newLanguageSelection)
	}

	function addSuccessStory() {
		if (!newStoryClientName.value.trim()) return
		editSuccessStories.value = [
			...editSuccessStories.value,
			{
				client_name: newStoryClientName.value.trim(),
				client_logo: newStoryClientLogo.value.trim(),
				headline: newStoryHeadline.value.trim(),
				category: newStoryCategory.value.trim(),
				url: newStoryUrl.value.trim(),
			},
		]
		newStoryClientName.value = ""
		newStoryClientLogo.value = ""
		newStoryHeadline.value = ""
		newStoryCategory.value = ""
		newStoryUrl.value = ""
	}

	function removeSuccessStory(story) {
		editSuccessStories.value = editSuccessStories.value.filter((row) => row !== story)
	}

	function addPack() {
		if (!newPackKey.value || !newPackName.value.trim()) return
		editPacks.value = [
			...editPacks.value,
			{
				pack_key: newPackKey.value,
				pack_name: newPackName.value.trim(),
				price: newPackPrice.value,
				hours: newPackHours.value,
				validity_days: newPackValidityDays.value,
				includes_summary: newPackIncludesSummary.value.trim(),
			},
		]
		newPackKey.value = ""
		newPackName.value = ""
		newPackPrice.value = ""
		newPackHours.value = ""
		newPackValidityDays.value = ""
		newPackIncludesSummary.value = ""
	}

	function removePack(pack) {
		editPacks.value = editPacks.value.filter((row) => row !== pack)
	}

	function addAddon() {
		if (!newAddonName.value.trim()) return
		editAddons.value = [
			...editAddons.value,
			{ addon_name: newAddonName.value.trim(), typical_hours: newAddonHours.value },
		]
		newAddonName.value = ""
		newAddonHours.value = ""
	}

	function removeAddon(addon) {
		editAddons.value = editAddons.value.filter((row) => row !== addon)
	}

	// Same throwaway-<input> file picker used for the account avatar (see find_partners.ts /
	// shortlisted.ts's openProfileImagePicker) — it's the smallest way to reach the browser's
	// native file dialog from a click handler.
	// Tracks whether the mousedown-to-mouseup on the logo box actually moved (vs. a plain
	// click), so a drag doesn't also reopen the file picker via the box's own click handler.
	let logoDragMoved = false

	function startLogoDrag(event) {
		if (!editLogo.value) return
		event.preventDefault()
		logoDragMoved = false
		const target = event.currentTarget
		const box = target.getBoundingClientRect()
		const startX = event.clientX
		const startY = event.clientY
		const startPosX = editLogoPositionX.value
		const startPosY = editLogoPositionY.value

		function move(e) {
			const dxPct = ((e.clientX - startX) / box.width) * 100
			const dyPct = ((e.clientY - startY) / box.height) * 100
			if (Math.abs(dxPct) > 1 || Math.abs(dyPct) > 1) logoDragMoved = true
			// the logo box uses backgroundSize: contain — the whole (never-cropped) image
			// just slides directly with the position percentage, so cursor movement maps
			// straight onto it: drag right/down moves the logo right/down.
			editLogoPositionX.value = Math.max(0, Math.min(100, startPosX + dxPct))
			editLogoPositionY.value = Math.max(0, Math.min(100, startPosY + dyPct))
		}

		function swallowClick(e) {
			e.stopImmediatePropagation()
			e.preventDefault()
		}

		function stop() {
			document.removeEventListener("mousemove", move)
			document.removeEventListener("mouseup", stop)
			if (logoDragMoved) {
				target.addEventListener("click", swallowClick, { capture: true, once: true })
			}
		}

		document.addEventListener("mousemove", move)
		document.addEventListener("mouseup", stop)
	}

	// Logo/founder-photo pickers are frappe-ui's <FileUploader> (see the page JSON) rather
	// than a hand-rolled <input type=file> — its default slot exposes openFileSelector/
	// uploading to drive our own custom-styled box, and its uploadArgs.upload_endpoint routes
	// the actual upload through our own permission-scoped backend methods instead of Frappe's
	// generic one. These just handle its success/failure emits.
	function onLogoUploaded(data) {
		editLogo.value = (data && data.logo) || editLogo.value
		context.myProfile.reload()
		toast({ title: "Logo updated", icon: "check", iconClasses: "text-green-600" })
	}

	function onLogoUploadFailed(error) {
		toast({
			title: "Could not upload logo",
			text: error && error.message,
			icon: "x-circle",
			iconClasses: "text-red-600",
		})
	}

	// Unlike the company logo, this doesn't save itself — the founder is a "team" child row
	// that may not exist yet, so there's nothing to attach the file to ahead of time (see
	// upload_partner_asset). The returned URL just fills editFounderPhoto, persisted on the
	// next Save changes like the rest of the Founder's Story fields.
	function onFounderPhotoUploaded(data) {
		editFounderPhoto.value = (data && data.file_url) || editFounderPhoto.value
	}

	function onFounderPhotoUploadFailed(error) {
		toast({
			title: "Could not upload photo",
			text: error && error.message,
			icon: "x-circle",
			iconClasses: "text-red-600",
		})
	}

	async function saveMyProfile() {
		if (savingProfile.value) return
		savingProfile.value = true
		try {
			await call("connect.api.partner.update_my_partner_profile", {
				partner_name: editPartnerName.value.trim(),
				tagline: editTagline.value.trim(),
				description: editDescription.value.trim(),
				country: editCountry.value.trim(),
				city: editCity.value.trim(),
				address: editAddress.value.trim(),
				website: editWebsite.value.trim(),
				industry: editIndustry.value,
				year_founded: editYearFounded.value,
				rollouts: editRollouts.value,
				hourly_rate: editHourlyRate.value,
				response_time_hours: editResponseTimeHours.value,
				sites_deployed: editSitesDeployed.value,
				typical_project_size: editTypicalProjectSize.value.trim(),
				proposal_timeline: editProposalTimeline.value.trim(),
				certified_experts: editCertifiedExperts.value,
				certs_erpnext: editCertsErpnext.value,
				certs_frappe_framework: editCertsFrappeFramework.value,
				countries_served: editCountriesServed.value,
				references_count: editReferencesCount.value,
				starter_pack: editStarterPack.value ? 1 : 0,
				demo_available: editDemoAvailable.value ? 1 : 0,
				logo_position_x: editLogoPositionX.value,
				logo_position_y: editLogoPositionY.value,
				apps: editApps.value,
				migrations: editMigrations.value,
				business_processes: editBusinessProcesses.value,
				languages: editLanguages.value,
				founder: {
					member_name: editFounderName.value.trim(),
					designation: editFounderDesignation.value.trim(),
					bio: editFounderBio.value.trim(),
					photo: editFounderPhoto.value.trim(),
				},
				success_stories: editSuccessStories.value,
				packs: editPacks.value,
				addons: editAddons.value,
			})
			await context.myProfile.reload()
			toast({ title: "Profile saved", icon: "check" })
		} catch (e) {
			toast({ title: "Could not save", text: (e && e.message) || "Please try again", icon: "x" })
		} finally {
			savingProfile.value = false
		}
	}

	return {
		editLogo,
		editLogoPositionX,
		editLogoPositionY,
		editPartnerName,
		editTagline,
		editDescription,
		editCountry,
		editCity,
		editAddress,
		editWebsite,
		editIndustry,
		editYearFounded,
		editRollouts,
		editHourlyRate,
		editResponseTimeHours,
		editSitesDeployed,
		editTypicalProjectSize,
		editProposalTimeline,
		editCertifiedExperts,
		editCertsErpnext,
		editCertsFrappeFramework,
		editCountriesServed,
		editReferencesCount,
		editStarterPack,
		editDemoAvailable,
		editApps,
		editMigrations,
		editBusinessProcesses,
		editLanguages,
		activeTab,
		editFounderName,
		editFounderDesignation,
		editFounderBio,
		editFounderPhoto,
		editSuccessStories,
		successStoryCategory,
		displayIndustries,
		starRating,
		reviewChartGrain,
		reviewChartConfig,
		newStoryClientName,
		newStoryClientLogo,
		newStoryHeadline,
		newStoryCategory,
		newStoryUrl,
		editPacks,
		newPackKey,
		newPackName,
		newPackPrice,
		newPackHours,
		newPackValidityDays,
		newPackIncludesSummary,
		editAddons,
		newAddonName,
		newAddonHours,
		savingProfile,
		toggleApp,
		toggleMigration,
		toggleBusinessProcess,
		toggleLanguage,
		newAppSelection,
		newMigrationSelection,
		newBusinessProcessSelection,
		newLanguageSelection,
		addApp,
		addMigration,
		addBusinessProcess,
		addLanguage,
		addSuccessStory,
		removeSuccessStory,
		addPack,
		removePack,
		addAddon,
		removeAddon,
		onLogoUploaded,
		onLogoUploadFailed,
		onFounderPhotoUploaded,
		onFounderPhotoUploadFailed,
		startLogoDrag,
		saveMyProfile,
		showProfileSettingsDialog,
		profileSettingsSection,
		editFullName,
		editPhone,
		editRole,
		originalFullName,
		originalPhone,
		originalRole,
		savingAccountProfile,
		uploadingProfileImage,
		showAddTeamMemberDialog,
		newTeamMemberEmail,
		newTeamMemberRole,
		newTeamMemberPassword,
		addingTeamMember,
		showDisableTeamMemberDialog,
		memberToDisable,
		disablingTeamMember,
		isAnyAdmin,
		openProfileSettings,
		selectProfileSettingsSection,
		saveMyAccountProfile,
		openProfileImagePicker,
		teamRowOptions,
		disableTeamMember,
		addTeamMember,
	}
}
