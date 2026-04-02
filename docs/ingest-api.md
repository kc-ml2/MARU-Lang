# Ingest API

## Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/ingest/upload` | Upload a file and start background ingest | Editor |
| `GET` | `/ingest/status` | Get document status for a team | Editor |
| `POST` | `/ingest/check` | Check which files need uploading | Editor |

## Upload (`POST /ingest/upload`)

Upload a file to permanent storage and start background ingestion (embedding).

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | File to upload |
| `team_id` | int | Yes | Team ID |
| `folder_path` | string | No | Folder path for group hierarchy |
| `mtime` | float | Yes | Original file modification time (unix timestamp) |

**Response:**

```json
{
  "document_id": "01J5X...",
  "name": "document-name",
  "status": "uploading"
}
```

**Status flow:** `uploading` → `processing` → `active` or `error`

## Status (`GET /ingest/status`)

Get all documents for a team with their current status.

**Query params:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | int | Yes | Team ID |

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
      "file_size": 12345,
      "created_at": "2026-04-02T10:00:00Z",
      "updated_at": "2026-04-02T10:01:00Z",
      "error": null
    }
  ]
}
```

**Possible statuses:** `uploading`, `processing`, `active`, `error`, `inactive`

## Check (`POST /ingest/check`)

Check which files from a list need to be uploaded by comparing fingerprints.

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
