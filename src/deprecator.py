"""Remove Dynatrace settings objects scoped to entities that are stale or no longer exist."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import re
import sys

MIN_PYTHON = (3, 12)
if sys.version_info < MIN_PYTHON:
    sys.exit(f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or higher is required (running {sys.version.split()[0]})")

from dynatrace import Dynatrace
from dynatrace import TOO_MANY_REQUESTS_WAIT

log = logging.getLogger("deprecator")

DEFAULT_STALE_AFTER_DAYS = 200
TRUE_VALUES = frozenset({"1", "y", "yes", "true"})
FALSE_VALUES = frozenset({"", "0", "n", "no", "false"})
MAX_ERROR_LENGTH = 300  # the client embeds the whole response body in its error message

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

# Entity scopes look like "<TYPE>-<hex id>", e.g. "HOST-0123456789ABCDEF".
# Types contain only upper-case letters, digits and underscores, never hyphens.
ENTITY_SCOPE_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]*)-[0-9A-Fa-f]+$")


@dataclass(frozen=True)
class Config:
    """Validated run configuration, built from environment variables."""

    url: str
    token: str
    stale_after_days: int
    delete_enabled: bool


@dataclass
class Stats:
    """Counters for the end-of-run summary."""

    checked: int = 0  # settings objects scoped to a supported entity type
    flagged: int = 0  # of those, stale or orphaned (would be / are removed)
    deleted: int = 0
    failed: int = 0


def short_error(exc: Exception) -> str:
    """Return the exception message, truncated so a large response body can't flood the log."""
    message = str(exc)
    if len(message) > MAX_ERROR_LENGTH:
        message = message[:MAX_ERROR_LENGTH] + "..."
    return f"{type(exc).__name__}: {message}"


def env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable (case-insensitive, whitespace ignored).

    Unrecognised values are treated as False, so a typo can never enable
    deletion, but a warning is logged.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value not in FALSE_VALUES:
        log.warning("Unrecognised value %r for %s; treating as false (dry run)", raw, name)
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
            log.error(error)
        sys.exit(2)

    return Config(url, token, stale_after_days, env_flag("CLEAN"))


def entity_type_of(scope: str) -> str | None:
    """Return the entity type of a settings scope (e.g. "HOST-ABC123" -> "HOST").

    Returns None if the scope is not in "<TYPE>-<hex id>" form, such as
    "environment" or any other non-entity scope.
    """
    match = ENTITY_SCOPE_PATTERN.match(scope)
    return match.group(1) if match else None


def is_not_found(exc: Exception) -> bool:
    """Return True only if the dynatrace client reported an HTTP 404.

    The client raises a bare Exception formatted as
    "Error making request to <url>: <Response [404]>. Response: <body>",
    so match the status in that exact position and ignore the response body.
    """
    msg = exc.args[0] if exc.args and isinstance(exc.args[0], str) else ""
    return re.search(r": <Response \[404\]>\.", msg) is not None


def is_entity_stale(dt_client: Dynatrace, scope: str, now: datetime, stale_after: timedelta, cache: dict[str, bool]) -> bool:
    """Return True if the entity behind `scope` is stale or no longer exists.

    The cache maps scope -> bool (the removal decision only), so no entity
    objects are retained. Lookup errors other than 404 return False and are
    not cached, so they are retried on the next settings object.
    """
    if scope in cache:
        return cache[scope]

    # Only the API call is guarded. The dynatrace client raises a bare Exception for
    # every HTTP error, so there is no narrower type to catch; keeping the try block
    # this small stops our own bugs from being swallowed as "lookup failed".
    try:
        entity = dt_client.entities.get(scope, fields="lastSeenTms")
    except Exception as exc:
        if not is_not_found(exc):
            log.warning("%s: entity lookup failed, keeping settings (%s)", scope, short_error(exc))
            return False
        log.info("%s: NOT FOUND - will be removed", scope)
        stale = True
    else:
        if entity.last_seen is None:
            # The entity exists but reports no last-seen time: never guess, keep the settings.
            log.info("%s (%s): NO LAST SEEN TIME - keeping", scope, entity.display_name)
            stale = False
        elif entity.last_seen + stale_after < now:
            log.info("%s (%s): last seen %s - TOO OLD, will be removed", scope, entity.display_name, entity.last_seen)
            stale = True
        else:
            log.info("%s (%s): last seen %s - keeping", scope, entity.display_name, entity.last_seen)
            stale = False

    cache[scope] = stale
    return stale


def delete_settings_object(dt_client: Dynatrace, object_id: str, stats: Stats) -> None:
    """Delete one settings object; log and count a failure instead of aborting the run."""
    try:
        dt_client.settings.delete_object(object_id)
    except Exception as exc:  # bare Exception from the client, see is_entity_stale
        stats.failed += 1
        log.error("DELETE FAILED for %s (%s)", object_id, short_error(exc))
    else:
        stats.deleted += 1
        log.info("DELETED %s", object_id)


def deprecate_settings(dt_client: Dynatrace, config: Config) -> Stats:
    """Scan all settings objects and flag (dry run) or delete those whose entity is stale or gone."""
    log.info("Mode: %s", "DELETE (CLEAN enabled)" if config.delete_enabled else "DRY RUN (set CLEAN=Yes to delete)")
    now = datetime.now(timezone.utc)
    stale_after = timedelta(days=config.stale_after_days)
    entity_cache: dict[str, bool] = {}  # scope -> should the settings be removed
    unsupported_types: set[str] = set()
    stats = Stats()

    for schema in dt_client.settings.list_schemas():
        # "value" is not needed and can be large; objects are streamed page by page.
        settings_objects = dt_client.settings.list_objects(schema.schema_id, fields="objectId,scope")
        if len(settings_objects) > 0:
            log.info("Schema %s: %d objects", schema.schema_id, len(settings_objects))

        for settings_object in settings_objects:
            if settings_object.scope == "environment":
                continue

            entity_type = entity_type_of(settings_object.scope)
            if entity_type not in SUPPORTED_ENTITY_TYPES:
                unsupported_types.add(entity_type or settings_object.scope)
                continue

            stats.checked += 1
            if is_entity_stale(dt_client, settings_object.scope, now, stale_after, entity_cache):
                stats.flagged += 1
                if config.delete_enabled:
                    delete_settings_object(dt_client, settings_object.object_id, stats)

    log.info("Unsupported types/scopes (skipped): %s", sorted(unsupported_types))
    log.info(
        "Summary: checked=%d flagged=%d deleted=%d failed=%d%s",
        stats.checked,
        stats.flagged,
        stats.deleted,
        stats.failed,
        "" if config.delete_enabled else " (dry run, nothing deleted)",
    )
    return stats


def main() -> None:
    """Entry point: configure logging, validate the environment, run, set the exit code."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    config = load_config()
    dt_client = Dynatrace(
        config.url,
        config.token,
        retries=3,
        retry_delay_ms=1000,
        too_many_requests_strategy=TOO_MANY_REQUESTS_WAIT,
        headers={"X-Dynatrace-Script": "SettingsDeprecator"},
    )
    stats = deprecate_settings(dt_client, config)
    if stats.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
