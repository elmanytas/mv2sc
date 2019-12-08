#!/usr/bin/python3

import sys
import subprocess
import json
import datetime
import re
import time

import pprint

#./mv2sc.py solera kong-postgresql local-hdd-01
namespace_name = sys.argv[1]
deployment_name = sys.argv[2]
new_storageclass_name = sys.argv[3]

# It depends on you are using openshift or kubernetes:
# - openshift -> deploymentconfig
# - kubernetes -> deployment
deployment_kind = "deploymentconfig"

# https://stackoverflow.com/questions/4760215/running-shell-command-and-capturing-the-output#4760517
result = subprocess.run(["kubectl", "get", deployment_kind, deployment_name,
                         "-n", namespace_name, "-o", "json"],
                         stdout=subprocess.PIPE)
deployment = json.loads(result.stdout)

deployment_replicas = deployment["spec"]["replicas"]
pprint.pprint((deployment_replicas))

# scale deployment to 0
result = subprocess.run(["kubectl", "scale", "--replicas=0", deployment_kind,
                         deployment_name,
                         "-n", namespace_name, "-o", "json"],
                         stdout=subprocess.PIPE)

# get date based version for new pvc names
version = datetime.datetime.now().strftime("%Y%m%d%H%M")

# volumes to migrate
pprint.pprint ((deployment["spec"]["template"]["spec"]["volumes"]))
for volume in deployment["spec"]["template"]["spec"]["volumes"]:
    # get pvc
    result = subprocess.run(["kubectl", "get", "pvc",
                             volume["persistentVolumeClaim"]["claimName"],
                             "-n", namespace_name, "-o", "json"],
                             stdout=subprocess.PIPE)
    pvc = json.loads(result.stdout)
    #pprint.pprint((pvc))
    pvc_name = volume["persistentVolumeClaim"]["claimName"]
    pvc_requests_storage = pvc["spec"]["resources"]["requests"]["storage"]
    pvc_accessMode = pvc["spec"]["accessModes"][0]

    # Create new pvc name depending on it was versioned or not
    # a versioned pvc has its date in the end like this: pvc-201912080818
    is_versioned_pvc_name = re.match(".*-\d\d\d\d\d\d\d\d\d\d\d\d$", pvc_name)
    if is_versioned_pvc_name:
        unversioned_pvc_name = "-".join(pvc_name.split("-")[0:-1])
        versioned_pvc_name = unversioned_pvc_name + "-" + version
    else:
        versioned_pvc_name = pvc_name + "-" + version

    # Create new pvc in new storageclass
    new_pvc = """
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: %s
  namespace: %s
spec:
  accessModes:
  - %s
  resources:
    requests:
      storage: %s
  storageClassName: %s
    """ % (versioned_pvc_name,
           namespace_name,
           pvc_accessMode,
           pvc_requests_storage,
           new_storageclass_name)
    pprint.pprint((new_pvc))
    
    result = subprocess.run(["kubectl", "apply", "-f", "-",
                             "-n", namespace_name, "-o", "json"],
                             stdout=subprocess.PIPE, input=new_pvc.encode('utf-8'))

    # wait until volume is bounded
    seconds_to_retry = 2
    retry = 10
    bounded = False
    i = 0
    while i < retry or bounded:
        time.sleep(seconds_to_retry)
        print ((i))
        i = i + 1


    


