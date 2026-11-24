from datetime import datetime, timedelta, timezone
import os
import re
from dynatrace import Dynatrace
from dynatrace import TOO_MANY_REQUESTS_WAIT

DT_URL = os.getenv("DT_URL")
DT_TOKEN = os.getenv("DT_TOKEN")
STALE_AFTER_DAYS = int(os.getenv("SINCE", "200"))
DELETE_ENABLED = os.getenv("CLEAN", "No") in ["1", "Y", "y", "YES", "Yes", "yes", "TRUE", "True", "true"]

dt_client = Dynatrace(
    DT_URL,
    DT_TOKEN,
    retries=3,
    retry_delay_ms=1000,
    too_many_requests_strategy=TOO_MANY_REQUESTS_WAIT,
    headers={"X-Dynatrace-Script": "SettingsDeprecator"},
)

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
unsupported_types = set()


def is_not_found(exc: Exception) -> bool:
    """Return True only if the dynatrace client reported an HTTP 404.

    The client raises a bare Exception formatted as
    "Error making request to <url>: <Response [404]>. Response: <body>",
    so match the status in that exact position and ignore the response body.
    """
    msg = exc.args[0] if exc.args and isinstance(exc.args[0], str) else ""
    return re.search(r": <Response \[404\]>\.", msg) is not None


def is_entity_stale(scope: str, now: datetime, stale_after: timedelta, cache: dict) -> bool:
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
        print(f"		Entity: {entity.display_name} : {entity.last_seen}")
        if (entity.last_seen + stale_after) < now:
            print("			TOO OLD - will be removed")
            stale = True
    except Exception as exc:
        print(type(exc))
        if not is_not_found(exc):
            return False
        print("			NOT FOUND - will be removed")
        stale = True

    cache[scope] = stale
    return stale


def deprecate_settings():
    now = datetime.now(timezone.utc)
    stale_after = timedelta(days=STALE_AFTER_DAYS)
    entity_cache = {}  # scope -> should the settings be removed
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

            print(f"	Scope: {settings_object.scope}")
            if is_entity_stale(settings_object.scope, now, stale_after, entity_cache) and DELETE_ENABLED:
                dt_client.settings.delete_object(settings_object.object_id)

    print(f"Unsupported types: {unsupported_types}")


if __name__ == "__main__":
    deprecate_settings()
