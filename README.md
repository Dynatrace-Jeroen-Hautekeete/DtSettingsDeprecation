# DtSettingsDeprecation

Removes Dynatrace settings objects that are scoped to individual entities which are no longer seen (or no longer exist).

## How it works

For every settings schema, the script first reads the schema's allowed scopes and skips the schema, without listing its objects, when it cannot be scoped to any supported entity type. If the allowed scopes cannot be read, the schema is scanned anyway. It then lists the settings objects and, for each object whose scope is an entity (not `environment`):

1. Takes the entity type from the scope (e.g. `HOST-ABC123` -> `HOST`).
2. Skips the object if the type is not in `SUPPORTED_ENTITY_TYPES`. Skipped types are listed at the end of the run.
3. Looks up the entity. The settings object is marked for removal if:
   - the entity was last seen more than `SINCE` days ago, or
   - the entity lookup returns HTTP 404 (entity not found).
4. Any other lookup error (timeout, 401/403, ...) never causes removal.

Objects are only deleted when `CLEAN` is enabled. **By default the script is a dry run** and only prints what it would remove.

## Supported entity types

`HOST`, `HOST_GROUP`, `KUBERNETES_CLUSTER`, `PROCESS_GROUP`, `PROCESS_GROUP_INSTANCE`, `SERVICE`, `CLOUD_APPLICATION`, `CLOUD_APPLICATION_NAMESPACE`, `DISK`

The list is defined in `SUPPORTED_ENTITY_TYPES` in [src/deprecator.py](src/deprecator.py). Making it configurable is planned.

## Configuration (environment variables)

| Variable   | Required | Default | Description |
|------------|----------|---------|-------------|
| `DT_URL`   | yes      | -       | Dynatrace environment URL. Must start with `https://` (plain `http://` is rejected so the API token is never sent unencrypted). |
| `DT_TOKEN` | yes      | -       | API token with permission to read and write settings, read schemas and read entities. |
| `SINCE`    | no       | `200`   | Whole number of days (>= 1) since an entity was last seen after which its settings are considered stale. |
| `CLEAN`    | no       | `No`    | Set to `1`, `y`, `yes` or `true` (case-insensitive) to actually delete. Anything else is a dry run; unrecognised values print a warning. The mode is printed at the start of the run. |

## Requirements

- Python 3.12 or higher (enforced at startup)
- `dt` 1.2.2 (see [requirements.txt](requirements.txt))

## Usage

```
pip install -r requirements.txt

# Dry run
python src/deprecator.py

# Delete stale settings
CLEAN=Yes python src/deprecator.py
```

Invalid or missing `DT_URL`, `DT_TOKEN` or `SINCE` are all reported up front and the script exits with code 2 before contacting Dynatrace.

Each run ends with a summary line (`checked`, `flagged`, `deleted`, `failed`). A failed delete is logged and the run continues; the script then exits with code 1. Entities that exist but report no last-seen time are always kept.

On PowerShell use `$env:CLEAN = "Yes"` before running.

Review the dry-run output before enabling `CLEAN`; deletions cannot be undone.
