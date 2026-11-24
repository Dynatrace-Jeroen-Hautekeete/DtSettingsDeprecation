# DtSettingsDeprecation

Removes Dynatrace settings objects that are scoped to individual entities which are no longer seen (or no longer exist).

## How it works

For every settings schema, the script lists all settings objects and, for each object whose scope is an entity (not `environment`):

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
| `DT_URL`   | yes      | -       | Dynatrace environment URL. |
| `DT_TOKEN` | yes      | -       | API token with permission to read and write settings and read entities. |
| `SINCE`    | no       | `200`   | Number of days since an entity was last seen after which its settings are considered stale. |
| `CLEAN`    | no       | `No`    | Set to `1`, `Y`, `YES` or `TRUE` (any of the spellings `Y/y`, `Yes/YES/yes`, `True/TRUE/true`) to actually delete. Anything else is a dry run. |

## Usage

```
pip install -r requirements.txt

# Dry run
python src/deprecator.py

# Delete stale settings
CLEAN=Yes python src/deprecator.py
```

On PowerShell use `$env:CLEAN = "Yes"` before running.

Review the dry-run output before enabling `CLEAN`; deletions cannot be undone.
