# DtSettingsDeprecation

This utility will scan your Dynatrace tenant for settings objects that are scoped to topology entities.  
When those entities haven't been observed over the past time, this tool will remove those configuration settings to keep your tenant clean.

## Prerequisites

Create Dynatrace token with scopes:  
* read settings  
* write settings  
* read schemas  

## Installation

pip install -r requirements.txt

## Run

export DT_URL=https://{tenant-id}.live.dynatrace.com (or https://{mycluster}/e/{environment-uuid})  
export DT_TOKEN=dt0c01.###.######  
(optional, default=200) export SINCE={num-days}  
  
cd src  
python deprecator.py  