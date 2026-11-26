# Partner data migration

This tool moves partner data from frappe.io and Frappe Cloud (Press) into Connect. It reads both sites through their APIs, asks only for the fields it maps to a Connect field, and checks every value before it saves. It never writes to frappe.io or Frappe Cloud.

It moves:

| Site | DocType | Connect record |
| --- | --- | --- |
| frappe.io | Partner, enabled only, with its industry and country served | Partner, with its owner as a member |
| Frappe Cloud | Team whose `partner_email` or `user` is a migrated partner's email, or that has an onboarding pending review. Only name, user and partner_email are read | Links each team to its partner by email |
| Frappe Cloud | Partner Onboarding with the status Pending Review: teams that applied and are not partners yet | Partner Application, pending review, on a new partner |
| Frappe Cloud | Partner Certificate, Partner Audit and Partner Non Conformance of those teams | Partner Certificate, Partner Audit and Partner Non Conformance |

The tool reads frappe.io first, then asks Frappe Cloud only for the records of those partners and applicants. It reads lists, not one record at a time, so a run takes about 25 requests for 400 partners.

Files come last, in their own step: partner logos, incorporation certificates, company logos, audit reports and non-conformance evidence.

## 1. Set up the connections

Do this once. In Desk, open **Integration Settings**:

| Section | Site URL | API key and secret |
| --- | --- | --- |
| **frappe.io Settings** | `https://frappe.io` | A frappe.io API user that can read **Partner** |
| **Press Settings** | `https://frappecloud.com` | The Press API user that Connect already uses. It must also read **Team**, **Partner Onboarding**, **Partner Certificate**, **Partner Audit** and **Partner Non Conformance**, and download their private files |

Tick **Enabled** in both sections. Read access is enough. Give both API users read-only roles.

## 2. Do a trial run

1. In Desk, open **Partner Migration** and add a new run.
2. Choose the **Sources**, then save:
   - **Both**: the normal migration. frappe.io goes first, then Press.
   - **frappe.io only**: for example, when the Press connection is not ready yet.
   - **Press only**: for example, to run Press again after you correct team emails. This needs frappe.io migrated first: the run asks Frappe Cloud for the teams of the partners already migrated from frappe.io. Without them, an applicant whose partner is on frappe.io would become a partner that frappe.io would later duplicate. The run refuses to start until frappe.io is migrated.
3. Click **Trial Run**.

A run needs only the connections of its sources. If one is not set up, the step stops before it starts and tells you which one. If you change the sources, the run goes back to Draft and needs a new trial run.

The trial runs in the background. The status goes from Queued to Running to Trial Done, and the page updates when the run ends. A trial run reads both sites, makes every change, then rolls all of it back.

Open the **Results** tab:

- **Problems** shows how many lines need action, and the table under it lists them.
- **Summary** shows how many report lines of each kind the run wrote.
- **Full Report** is a zip with one CSV for each kind and a `summary.txt`.
- **Source Snapshot** is a zip with what the run read from each site, as JSON.

These kinds of problem need action. A clean trial run has none of them:

| Kind | Meaning | What to do |
| --- | --- | --- |
| `automations_on` | A Notification, Webhook, Assignment Rule or Server Script acts on a DocType the run saves. It would send, assign or call out once for every migrated record. Muting email is not enough: Frappe would still queue the emails and send them after the run. | Switch it off in Desk for the migration, and on again after it. |
| `failed` | A partner could not be saved. Only that partner was rolled back. The line gives the reason. | Fix the mapping, or the data on frappe.io or Frappe Cloud. |
| `unmatched` | No partner can take a Frappe Cloud team's records, usually because its frappe.io partner `failed`. | Fix that partner's failure. |
| `conflicts` | A certificate belongs to a different partner in Connect, a non-conformance has no migrated audit, or one person would own two partners. | Decide case by case. |
| `files_failed` | A file could not be copied. The line gives the reason. | Fix the cause and click **Copy Files** again. |

These kinds are information only:

- `skipped`: an older copy of a certificate. Connect keeps the newest one for each holder and course.
- `partners_created`, `partners_matched`, `partners_updated`: what happened to each partner.
- `members_added`: the owners and admins who join their partner.
- `managers_missing`: a frappe.io success manager who has no Connect login.
- `values_dropped`: a bad phone, contact email, website, industry or country served that was left out, so its partner could still come over. The partner can add it in Connect.
- `owners_skipped`: a Frappe staff email (`@frappe.io`) named as a partner's user. Staff do not become owners.
- `partners_deleted_in_Connect`, `applications_deleted_in_Connect`, `audits_deleted_in_Connect`: records an earlier run made that someone has since deleted in Connect. The run leaves them deleted.

Fix the problems and click **Trial Run** again until the run is clean. If a step stops, the status is Failed and the **Error** section on the Results tab shows why.

## 3. Run the migration, then check it

Do this first on a copy of the production site, then on production. Before the migration on production:

- Take a backup of the database. The tool has no undo: the backup is the undo.
- Pick a quiet time. A partner who edits their profile while the migration saves it fails with "document changed".
- Do the last trial run and the migration on the same day: both read the sites as they are at that moment.

1. When the trial run is clean, **Ready to Migrate** is ticked: click **Run Migration** and confirm. The button shows only after a clean trial run. The migration reads its sources again, saves the records, then copies their files (see below).
2. When the status is Migrated, click **Check**.

The check only reads. For each DocType, the **Summary** shows how many records are at the source and how many are in Connect. The problems table names each record that is `missing` (not migrated) or `gone` (deleted after the run). The summary also counts `files_not_copied`, the files that **Copy Files** can try again. A check with no problems ticks **Ready for Frappe CRM**.

Only one run can work at a time. If a step stays Queued or Running because its background job stopped, click **Mark as Failed**. A step that stops keeps none of its changes.

You can run the migration again with a new run. Each source record is linked to its Connect record by a **Migration Record**, which you can find in Desk. It does not make copies:

- A frappe.io partner already in Connect gets only the fields frappe.io still owns: email, enabled, and the contract dates. Its other fields are filled only where Connect has nothing. What a partner edits in Connect, and the tier Connect works out, are never overwritten.
- Press records already in Connect stay as they are.
- A record deleted in Connect stays deleted.

## 4. The files

**Run Migration** copies the files after it saves the records. A trial run copies no files. The migration downloads each file whose address it recorded, and attaches it to its Connect record:

| File | Goes to | Private |
| --- | --- | --- |
| frappe.io partner logo | Partner logo | No |
| Onboarding incorporation certificate | Partner Application | Yes |
| Onboarding company logo | Partner Application, and the logo of a partner made from that onboarding | No |
| Audit report | Partner Audit | Yes |
| Non-conformance evidence | Partner Non Conformance | Yes |

- A field that already has a file in Connect keeps it. The step never replaces a file.
- A file that cannot be copied is listed as `files_failed` with the reason: not found, refused, too large for the upload limit in System Settings, or a PDF that cannot be read. The other files carry on.
- Each file is saved as soon as it is copied. If copying stops, the records stay migrated.
- To try the missing files again, click **Copy Files** on a migrated run. It reads no records again and copies only the files that are still missing.
- The step sends a site's API key only to that site. A file kept on another host is downloaded without a key.

## 5. After the migration

During a run, Connect sends no invitations and nothing to Frappe CRM. When **Ready for Frappe CRM** is ticked, click **Send to Frappe CRM** and confirm. This sends every approved partner to Frappe CRM once. The partners go only when tier and listing changes are on in Integration Settings.

Owners get no invitation email. They sign in with an email code. Frappe announces the move to partners.

## Command line, for testing

The same steps run from the command line, with the same connections:

```
bench --site <site> execute connect.partner.migration.run.run
bench --site <site> execute connect.partner.migration.run.run --kwargs "{'apply': True}"
bench --site <site> execute connect.partner.migration.check.run
```

The first command is a trial run, and the second saves. Each writes a report folder into `sites/<site>/private/partner-migration`, with what was read in its `source` folder.
