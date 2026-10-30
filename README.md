# TU CSIT Notice Hub

The project has a static HTML/CSS/JavaScript notice feed, a Vercel Python API, and a legacy Streamlit dashboard. The authoritative notice source is the Institute of Science and Technology (IoST), Tribhuvan University:

<https://iost.tu.edu.np/notices>

The source currently serves cursor-paginated notice listings, individual detail pages, and document links (including PDFs hosted by `portal.tu.edu.np`). The importer reads those public pages only; it does not bypass access controls.

## Local setup

Python 3.10 or later is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-streamlit.txt
python iost_sync.py sync
streamlit run app.py
```

The SQLite database defaults to `notices.db`, and verified attachments default to `notice_files\`. Both locations are ignored by Git. Set `NOTICE_DB_PATH` and `NOTICE_STORAGE_DIR` to persistent paths before running the importer if the project directory is not durable.

## Historical import and automatic sync

`sync` checks the newest listing pages and imports unseen notice details and attachments. It is safe to repeat and never deletes an archived notice or attachment.

```powershell
python iost_sync.py sync --dry-run
python iost_sync.py sync
python iost_sync.py backfill --dry-run --max-pages 3
python iost_sync.py backfill --max-pages 10
```

Backfill resumes from its saved cursor. Run it repeatedly until `sync_state.backfill_complete` is set. Backfill is not marked complete while unresolved `sync_failures` exist; correct the issue and run `python iost_sync.py retry-failures`, then resume backfill to verify traversal. A failed notice does not stop the rest of the batch.

For a self-hosted Windows machine with persistent storage, create a Task Scheduler task that runs `python.exe iost_sync.py sync` from the project directory on a five-minute repetition trigger. The machine and storage must remain available. On a Linux host, configure the equivalent cron/systemd timer. Do not schedule requests from the visitor's browser.

## Deployment and persistence limitation

The checked-in Vercel setup is a static frontend plus serverless Python functions. Vercel function filesystems are not a durable SQLite database or permanent document store, and no external database/object-storage credentials or sync authentication are configured in this repository. Therefore:

- The API serves the local SQLite archive when it is present; otherwise it returns a clearly labeled live preview from the official listing.
- The live preview is not a historical archive and does not persist upstream changes.
- The importer and document API are ready for a host where `NOTICE_DB_PATH` and `NOTICE_STORAGE_DIR` point to durable shared storage, but the current Vercel deployment cannot safely run the archival sync without a separately provisioned persistent database and object store.
- No production import, scheduled task, cloud service, or deployment has been run or provisioned.

Before deploying the complete archival service, provide persistent database and file storage and a server-side scheduler. Configure both the web process and sync worker to use the same persistent database/storage paths. Run a dry-run first, then a small batch, validate the PDF viewing/download endpoints, and only then continue historical backfill. Do not expose a manual sync endpoint without authentication.

## API and archive behavior

- `GET /api/notices` reads archived notices when a database is configured and populated; otherwise it fetches a bounded recent preview from the official listing. Both modes apply category, programme, semester, source-ID/title search, sort order, page, and page-size parameters before returning results. Programme choices and category totals are derived from the available notice titles/archive. Programme names are assigned only when explicitly identified in a title; combined notices can match more than one programme. Supported categories distinguish exam routines, exam centres, other examination notices, results, admissions, form fill-ups, and general notices. Supported sort values are `newest` (the default official order) and `oldest`; page sizes are capped at 100.
- Existing SQLite archive rows receive a one-time migration of derived category, semester, urgency, and programme metadata. Official notice titles and source URLs are not changed.
- `GET /api/document?attachment_id=<id>&disposition=inline|attachment` serves a validated local attachment, supports byte ranges, and preserves the original filename.
- Source IDs and canonical source URLs are unique in SQLite. Metadata is insert-only so an upstream title change cannot silently rewrite the archived record.
- Attachment downloads are restricted to HTTPS on official IoST/TU hosts, capped at 25 MB, checked against MIME type and file signature, and written atomically.
- The importer records sync runs, resumable backfill cursor state, and per-notice failures. It does not expose a public mutation route.

## Tests

```powershell
python -m pytest -q
```

The tests cover the source parser, duplicate prevention, additive database migration, attachment metadata and validation, and official-source-only behavior. Live historical backfill and scheduled execution must be verified on the chosen persistent host; they are not claimed as completed by local tests.
