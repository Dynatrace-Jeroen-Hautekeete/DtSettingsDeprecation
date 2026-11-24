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


def deprecate_settings():
    now = datetime.now(timezone.utc)
    stale_after = timedelta(days=STALE_AFTER_DAYS)
    schemas = dt_client.settings.list_schemas()
    for schema in schemas:
        settings_objects = dt_client.settings.list_objects(schema.schema_id, fields="objectId,value,scope")
        if len(settings_objects) > 0:
            print(f"Found schema: {schema.schema_id} : {len(settings_objects)}")

        for settings_object in settings_objects:
            if settings_object.scope != "environment":
                entity_type = settings_object.scope.split("-")[0]
                should_remove = False
                if entity_type in SUPPORTED_ENTITY_TYPES:
                    print(f"\tScope: {settings_object.scope}")
                    try:
                        scoped_entity = dt_client.entities.get(settings_object.scope, fields="lastSeenTms")
                        print(f"\t\tEntity: {scoped_entity.display_name} : {scoped_entity.last_seen}")

                        if (scoped_entity.last_seen + stale_after) < now:
                            print("\t\t\tTOO OLD - will be removed")
                            should_remove = True
                    except Exception as exc:
                        print(type(exc))
                        if is_not_found(exc):
                            print("\t\t\tNOT FOUND - will be removed")
                            should_remove = True
                else:
                    unsupported_types.add(entity_type)
                if should_remove and DELETE_ENABLED:
                    dt_client.settings.delete_object(settings_object.object_id)

    print(f"Unsupported types: {unsupported_types}")


if __name__ == "__main__":
    deprecate_settings()
