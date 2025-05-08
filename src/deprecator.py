from datetime import datetime, timedelta, timezone
import os
from dynatrace import Dynatrace
from dynatrace import TOO_MANY_REQUESTS_WAIT

dt_url=os.getenv("DT_URL")
dt_token=os.getenv("DT_TOKEN")
since=int(os.getenv("SINCE","200"))
clean=os.getenv("CLEAN","No")

dtapi = Dynatrace(dt_url,dt_token, retries=3, retry_delay_ms=1000, too_many_requests_strategy=TOO_MANY_REQUESTS_WAIT,headers={"X-Dynatrace-Script":"SettingsDeprecator"})

suptypes = [ 
    "HOST", 
    "HOST_GROUP", 
    "KUBERNETES_CLUSTER", 
    "PROCESS_GROUP", 
    "PROCESS_GROUP_INSTANCE",
    "SERVICE",
    "CLOUD_APPLICATION",
    "CLOUD_APPLICATION_NAMESPACE",
    "DISK"
]
unsuptypes = set()


def deprecateSettings():
    current_dateTime = datetime.now(timezone.utc)
    deprecation=timedelta(days=since)
    schemas = dtapi.settings.list_schemas()
    for schema in schemas:
        settingsobjects = dtapi.settings.list_objects(schema.schema_id,fields="objectId,value,scope")
        if len(settingsobjects)>0:
            print(f"Found schema: {schema.schema_id} : {len(settingsobjects)}")
        
        for sobject in settingsobjects:
            if sobject.scope != "environment":
                curtype = sobject.scope.split("-")[0]
                removal = False
                if curtype in suptypes:
                    print(f"\tScope: {sobject.scope}")
                    try:
                        scopedentity = dtapi.entities.get(sobject.scope, fields="lastSeenTms")
                        print(f"\t\tEntity: {scopedentity.display_name} : {scopedentity.last_seen}")
                        
                        if (scopedentity.last_seen + deprecation) < current_dateTime:
                            print(f"\t\t\tTOO OLD - will be removed")
                            removal = True
                    except Exception as inst:
                        print(type(inst))
                        if "[404]" in inst.args[0]:
                            print(f"\t\t\tNOT FOUND - will be removed")
                            removal = True                        
                else:
                    unsuptypes.add(curtype)
                if removal and clean in ["1","Y","y","YES","Yes","yes","TRUE","True","true"]:
                    dtapi.settings.delete_object(sobject.object_id)
    
    print(f"Unsupported types: {unsuptypes}")        
        
    

if __name__ == "__main__":
    deprecateSettings()


