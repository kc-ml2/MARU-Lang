# Ingest API

## Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/ingest/upload` | Upload a file and ingest it | Editor |
| `GET` | `/ingest/status` | Get document status for a team | Editor |
| `POST` | `/ingest/check` | Check which files need uploading | Editor |
| `POST` | `/ingest/{document_id}/retry` | Re-ingest a failed (or, with force, active) document | Editor |
| `POST` | `/ingest/groups/{group_id}/retry` | Re-ingest every retryable document in a folder (queue mode only) | Editor |
| `DELETE` | `/ingest/{document_id}` | Delete a document and its embeddings | Team admin |
| `DELETE` | `/ingest/groups/{group_id}` | Delete a folder's entire subtree (docs + descendant folders) | Team admin |

## Processing model (read this first)

Embedding runs in one of two modes, decided by server config (`task_queue_enabled`):

- **Queue on** — upload/retry **enqueue** the job to a worker and return immediately
  with `status: "queued"`. Poll `GET /ingest/status` to follow progress.
- **Queue off** — upload/retry run embedding **synchronously**; the response carries
  the real outcome (`"active"` or `"error"` + message). Requests can take tens of
  seconds for large files — use a generous client timeout (the CLI uses 300s).

The frontend should handle both: treat `"queued"` as "in progress, poll status",
and `"active"`/`"error"` as final.

**Document status flow:**

```
uploading → processing → active (searchable)
                       ↘ error  (retryable)
deleting  = delete requested while in-flight; finalized by the worker
inactive  = deliberately disabled (not searchable, not retryable)
```

## Upload (`POST /ingest/upload`)

Upload a file to permanent storage and ingest it (parse → chunk → embed).

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | File to upload |
| `team_id` | int | Yes | Team ID |
| `folder_path` | string | No | Folder path; its last segment names the document group |
| `mtime` | float | Yes | Original file modification time (unix timestamp) |

Supported formats: pdf, docx/doc, pptx, xlsx/xls, hwp/hwpx/hwpml (Korean documents),
csv/tsv, json, html, xml, yaml, md, txt, and common code/text files.

**Response:**

```json
{
  "document_id": "01J5X...",
  "name": "document-name",
  "status": "queued",
  "is_reupload": false,
  "error": null
}
```

- `status`: `"queued"` (worker will process) | `"active"` (done, searchable) |
  `"error"` (failed — message in `error`)
- `is_reupload`: `true` when the same file (by fingerprint) existed and was replaced.
- Re-uploading an **unchanged** file (same path/size/mtime) is skipped by
  `/ingest/check`; to re-process a failed or already-active document use **retry**.

## Status (`GET /ingest/status`)

Get all documents for a team with their current status.

**Query params:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | int | Yes | Team ID |
| `group_id` | int | No | Filter to one folder (DocumentGroup id, e.g. from `GET /teams/{team_id}`). Unknown/foreign ids return an empty list. |

**Response:**

```json
{
  "team_id": 1,
  "total": 3,
  "documents": [
    {
      "id": "01J5X...",
      "name": "readme",
      "status": "active",
      "group_id": 7,
      "folder_path": "my-project",
      "file_size": 12345,
      "created_at": "2026-06-10T10:00:00Z",
      "updated_at": "2026-06-10T10:01:00Z",
      "error": null,
      "audit_logs": [
        {"action": "UPLOAD", "user_name": "Admin", "detail": {}, "created_at": "..."}
      ]
    }
  ]
}
```

**Possible statuses:** `uploading`, `processing`, `active`, `error`, `inactive`, `deleting`

## Retry (`POST /ingest/{document_id}/retry`)

Re-ingest one document. Same response semantics as upload.

**Query params:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | int | Yes | Team ID |
| `force` | bool | No | `true` also allows re-ingesting an **active** document (full re-parse/re-embed, e.g. after a parser change). Default `false` = error documents only. |

**Response:** same shape as upload (`status`: `"queued"` / `"active"` / `"error"`).

**Errors:**

- `404` — document not found in this team
- `409` — document is not retryable: in-flight (`uploading`/`processing`),
  `deleting`, or `inactive` are never retried; `active` requires `force=true`.

**Bulk retry is client-side by design**: fetch `GET /ingest/status`, filter
`status == "error"` (plus `"active"` for a force re-ingest), and call retry per
document — this gives per-document progress/results in the UI.

```js
// Example: retry all failed documents of a team
const { documents } = await api.get(`/ingest/status?team_id=${teamId}`);
for (const doc of documents.filter(d => d.status === "error")) {
  const res = await api.post(`/ingest/${doc.id}/retry?team_id=${teamId}`);
  // res.status: "queued" → poll status later; "active" → done; "error" → show res.error
}
```

## Group retry (`POST /ingest/groups/{group_id}/retry`)

Bulk convenience: re-ingest **every retryable document in one folder** with a
single call. **Queue mode only** — jobs are enqueued to the worker; poll
`GET /ingest/status?team_id=&group_id=` for progress.

**Query params:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | int | Yes | Team ID |
| `force` | bool | No | `true` also re-ingests **active** documents in the folder |

**Response:**

```json
{
  "group_id": 7,
  "requeued": [
    {"document_id": "01J5X...", "name": "report"},
    {"document_id": "01J5Y...", "name": "annex"}
  ],
  "count": 2,
  "skipped": 1
}
```

- `requeued` — documents reset and enqueued.
- `skipped` — documents in the folder that were not retryable (in-flight,
  `deleting`, `inactive`, or `active` without `force`). Skipping is silent by
  design — bulk retry never fails on individual document states.

**Errors:**

- `409` — the server runs without the task queue (`task_queue_enabled` off).
  Use per-document `POST /ingest/{document_id}/retry` instead, whose synchronous
  response carries real outcomes.

A foreign/unknown `group_id` simply requeues nothing (`count: 0`).

## Check (`POST /ingest/check`)

Check which files from a list need to be uploaded by comparing fingerprints
(team + path + size + mtime). A match means "this exact version is already
ingested **for this team**"; a modified file (different size/mtime) needs
upload again — the upload then **updates the existing document in place**
(same `document_id`, embeddings replaced), it does not create a sibling.

**Request:**

```json
{
  "team_id": 1,
  "files": [
    {
      "fileName": "readme.md",
      "absolutePath": "/path/to/readme.md",
      "size": 1234,
      "mtime": 1712000000.0
    }
  ]
}
```

**Response:**

```json
{
  "indices_to_upload": [0],
  "total": 1
}
```

`indices_to_upload` contains the array indices of files that are new or modified.
Unchanged files are skipped — failed documents are re-processed via **retry**,
not re-upload.

## Delete (`DELETE /ingest/{document_id}`)

Delete a document and its embeddings. Requires **team admin** role.

**Query params:** `team_id` (required)

**Response:**

```json
{ "document_id": "01J5X...", "deleted": true }
```

If the document is mid-ingest, it is marked `deleting` and finalized by the
worker shortly after (the row disappears from `/ingest/status` once finalized).

## Folder delete (`DELETE /ingest/groups/{group_id}`)

Delete a folder's **entire subtree**: every document in it and in its
descendant folders, then the empty folder rows themselves. Requires **team
admin** role.

**Query params:** `team_id` (required)

**Response:**

```json
{ "group_id": 7, "deleted": 4, "deferred": 1, "group_removed": false }
```

- `deleted` — documents removed immediately (embeddings + storage included)
- `deferred` — in-flight documents marked `deleting`; the worker finalizes them
- `group_removed` — whether the folder row itself was removed. `false` while
  deferred documents remain; the folder disappears once the worker finishes.

`404` — folder not found in this team.
