from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import re
import sys

MIN_PYTHON = (3, 12)
if sys.version_info < MIN_PYTHON:
    sys.exit(f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or higher is required (running {sys.version.split()[0]})")

from dynatrace import Dynatrace
from dynatrace import TOO_MANY_REQUESTS_WAIT

DEFAULT_STALE_AFTER_DAYS = 200
TRUE_VALUES = frozenset({"1", "y", "yes", "true"})
FALSE_VALUES = frozenset({"", "0", "n", "no", "false"})

SUPPORTED_ENTITY_TYPES = [
    "HOST",
    "HOST_GROUP",
    "KUBERNETES_CLUSTER",
    "PROCESS_GROUP",
    "PROCESS_GROUP_INSTANCE",
    "SERVICE",
    "CLOUD_APPLICATION",
    "CLOUD_APPLICATION_NAMESPACE",
    "DISK",
]


@dataclass(frozen=True)
class Config:
    url: str
    token: str
    stale_after_days: int
    delete_enabled: bool


def env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable (case-insensitive, whitespace ignored).

    Unrecognised values are treated as False, so a typo can never enable
    deletion, but a warning is printed.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value not in FALSE_VALUES:
        print(f"WARNING: unrecognised value {raw!r} for {name}; treating as false (dry run)")
    return False


def load_config() -> Config:
    """Read and validate the environment. Exits with all problems listed at once."""
    errors = []

    url = (os.getenv("DT_URL") or "").strip()
    if not url:
        errors.append("DT_URL is required, e.g. https://{tenant-id}.live.dynatrace.com")
    elif not re.match(r"^https://[^/\s]+", url, re.IGNORECASE):
        errors.append(f"DT_URL must start with https:// (got {url!r})")

    token = (os.getenv("DT_TOKEN") or "").strip()
    if not token:
        errors.append("DT_TOKEN is required")

    since_raw = (os.getenv("SINCE") or "").strip()
    stale_after_days = DEFAULT_STALE_AFTER_DAYS
    if since_raw:
        try:
            stale_after_days = int(since_raw)
            if stale_after_days < 1:
                raise ValueError
        except ValueError:
            errors.append(f"SINCE must be a whole number of days >= 1 (got {since_raw!r})")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)

    return Config(url, token, stale_after_days, env_flag("CLEAN"))


def is_not_found(exc: Exception) -> bool:
    """Return True only if the dynatrace client reported an HTTP 404.

    The client raises a bare Exception formatted as
    "Error making request to <url>: <Response [404]>. Response: <body>",
    so match the status in that exact position and ignore the response body.
    """
    msg = exc.args[0] if exc.args and isinstance(exc.args[0], str) else ""
    return re.search(r": <Response \[404\]>\.", msg) is not None


def is_entity_stale(dt_client: Dynatrace, scope: str, now: datetime, stale_after: timedelta, cache: dict) -> bool:
    """Return True if the entity behind `scope` is stale or no longer exists.

    The cache maps scope -> bool (the removal decision only), so no entity
    objects are retained. Lookup errors other than 404 return False and are
    not cached, so they are retried on the next settings object.
    """
    if scope in cache:
        return cache[scope]

    stale = False
    try:
        entity = dt_client.entities.get(scope, fields="lastSeenTms")
        print(f"\t\tEntity: {entity.display_name} : {entity.last_seen}")
        if (entity.last_seen + stale_after) < now:
            print("\t\t\tTOO OLD - will be removed")
            stale = True
    except Exception as exc:
        print(type(exc))
        if not is_not_found(exc):
            return False
        print("\t\t\tNOT FOUND - will be removed")
        stale = True

    cache[scope] = stale
    return stale


def deprecate_settings(dt_client: Dynatrace, config: Config):
    print("Mode: DELETE (CLEAN enabled)" if config.delete_enabled else "Mode: DRY RUN (set CLEAN=Yes to delete)")
    now = datetime.now(timezone.utc)
    stale_after = timedelta(days=config.stale_after_days)
    entity_cache = {}  # scope -> should the settings be removed
    unsupported_types = set()
    schemas = dt_client.settings.list_schemas()
    for schema in schemas:
        # "value" is not needed and can be large; objects are streamed page by page.
        settings_objects = dt_client.settings.list_objects(schema.schema_id, fields="objectId,scope")
        if len(settings_objects) > 0:
            print(f"Found schema: {schema.schema_id} : {len(settings_objects)}")

        for settings_object in settings_objects:
            if settings_object.scope == "environment":
                continue

            entity_type = settings_object.scope.split("-")[0]
            if entity_type not in SUPPORTED_ENTITY_TYPES:
                unsupported_types.add(entity_type)
                continue

            print(f"\tScope: {settings_object.scope}")
            if is_entity_stale(dt_client, settings_object.scope, now, stale_after, entity_cache) and config.delete_enabled:
                dt_client.settings.delete_object(settings_object.object_id)

    print(f"Unsupported types: {unsupported_types}")


def main():
    config = load_config()
    dt_client = Dynatrace(
        config.url,
        config.token,
        retries=3,
        retry_delay_ms=1000,
        too_many_requests_strategy=TOO_MANY_REQUESTS_WAIT,
        headers={"X-Dynatrace-Script": "SettingsDeprecator"},
    )
    deprecate_settings(dt_client, config)


if __name__ == "__main__":
    main()
