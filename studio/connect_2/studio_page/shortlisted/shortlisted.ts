import { ref } from "vue"
import { toast, call, useFileUpload } from "frappe-ui"

export default function setup(context) {
	// ---- Profile settings popup (sidebar avatar) ----
	// Mirrors the same feature on the messaging page (see messaging.ts) — kept in sync there
	// since Studio pages don't share component logic, only markup/state shape by convention.
	const showProfileSettingsDialog = ref(false)
	const profileSettingsSection = ref("profile")
	const editFullName = ref("")
	const editPhone = ref("")
	const editRole = ref("")
	const originalFullName = ref("")
	const originalPhone = ref("")
	const originalRole = ref("")
	const savingProfile = ref(false)
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
		const profile = context.myProfile.data
		editFullName.value = (profile && profile.full_name) || ""
		editPhone.value = (profile && profile.phone) || ""
		editRole.value = (profile && profile.role) || ""
		originalFullName.value = editFullName.value
		originalPhone.value = editPhone.value
		originalRole.value = editRole.value
		showProfileSettingsDialog.value = true
	}

	function selectProfileSettingsSection(section) {
		profileSettingsSection.value = section
	}

	async function saveMyProfile() {
		const fullName = editFullName.value.trim()
		if (!fullName || savingProfile.value) return
		savingProfile.value = true
		try {
			await call("connect.api.account.update_my_profile", {
				full_name: fullName,
				phone: editPhone.value.trim(),
				role: editRole.value.trim(),
			})
			await context.myProfile.reload()
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
			savingProfile.value = false
		}
	}

	// picking a new avatar happens the same way as chat attachments on the messaging page —
	// a throwaway <input> is the smallest way to reach the browser's native file dialog.
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
				context.myProfile.reload()
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

	return {
		showProfileSettingsDialog,
		profileSettingsSection,
		editFullName,
		editPhone,
		editRole,
		originalFullName,
		originalPhone,
		originalRole,
		savingProfile,
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
		saveMyProfile,
		openProfileImagePicker,
		teamRowOptions,
		disableTeamMember,
		addTeamMember,
	}
}
