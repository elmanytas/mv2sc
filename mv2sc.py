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
#pprint.pprint((deployment_replicas))

# scale deployment to 0
result = subprocess.run(["kubectl", "scale", "--replicas=0", deployment_kind,
                         deployment_name,
                         "-n", namespace_name, "-o", "json"],
                         stdout=subprocess.PIPE)

# get date based version for new pvc names
version = datetime.datetime.now().strftime("%Y%m%d%H%M")

# volumes to migrate
#pprint.pprint ((deployment["spec"]["template"]["spec"]["volumes"]))
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
    #pprint.pprint((new_pvc))
    
    result = subprocess.run(["kubectl", "apply", "-f", "-",
                             "-n", namespace_name, "-o", "json"],
                             stdout=subprocess.PIPE, input=new_pvc.encode('utf-8'))

    # wait until volume is bounded
    seconds_to_retry = 2
    retry = 2
    bounded = False
    i = 0
    while i < retry and not bounded:
        time.sleep(seconds_to_retry)
        print ((i))
        result = subprocess.run(["kubectl", "get", "pvc", versioned_pvc_name,
                                 "-n", namespace_name, "-o", "json"],
                                 stdout=subprocess.PIPE)
        new_pvc = json.loads(result.stdout)
        if new_pvc["status"]["phase"] == "Bound":
            bounded = True
        i = i + 1
    
    #if not bounded:
    #    print (("timeout waiting for bound " + versioned_pvc_name))
    #    exit (1)

    # create a pod with rsyncd and origin volume mounted in /data
    # https://hub.docker.com/r/apnar/rsync-server
    origin_pvc_name = pvc_name
    rsyncd_pod = """
apiVersion: v1
kind: Pod
metadata:
  name: rsyncd-%s
  namespace: %s
  labels:
    name: rsyncd-%s
spec:
  containers:
  - name: rsyncd-%s
    image: apnar/rsync-server
    env:
    - name: USERNAME
      value: root
    - name: PASSWORD
      value: rsync
    volumeMounts:
    - name: storage
      mountPath: /data
  volumes:
  - name: storage
    persistentVolumeClaim: 
      claimName: %s
    """ % (origin_pvc_name,
           namespace_name,
           origin_pvc_name,
           origin_pvc_name,
           origin_pvc_name)
    #pprint.pprint((rsyncd_pod))
    rsyncd_svc = """
apiVersion: v1
kind: Service
metadata:
  name: rsyncd-%s
  namespace: %s
spec:
  ports:
  - name: rsyncd
    port: 22
    protocol: TCP
    targetPort: 22
  selector:
    name: rsyncd-%s
  type: ClusterIP
    """ % (origin_pvc_name,
           namespace_name,
           origin_pvc_name)
#    pprint.pprint((rsyncd_svc))

    result = subprocess.run(["kubectl", "apply", "-f", "-",
                             "-n", namespace_name, "-o", "json"],
                             stdout=subprocess.PIPE, input=rsyncd_pod.encode('utf-8'))
    result = subprocess.run(["kubectl", "apply", "-f", "-",
                             "-n", namespace_name, "-o", "json"],
                             stdout=subprocess.PIPE, input=rsyncd_svc.encode('utf-8'))

    # create a pod with rsync as destination
    destination_pvc_name = versioned_pvc_name
    rsync_pod = """
apiVersion: v1
kind: Pod
metadata:
  name: rsync-%s
  namespace: %s
spec:
  containers:
  - name: rsync-%s
    image: apnar/rsync-server
    volumeMounts:
    - name: storage
      mountPath: /data
  volumes:
  - name: storage
    persistentVolumeClaim: 
      claimName: %s
    """ % (destination_pvc_name,
           namespace_name,
           destination_pvc_name,
           destination_pvc_name)
    result = subprocess.run(["kubectl", "apply", "-f", "-",
                             "-n", namespace_name, "-o", "json"],
                             stdout=subprocess.PIPE, input=rsync_pod.encode('utf-8'))

    time.sleep(30)
    # rsync everything: https://stackoverflow.com/questions/3299951/how-to-pass-password-automatically-for-rsync-ssh-command#19570794
    # install sshpass
    # kubect"apt-get update; apt-get -y install sshpass"
    result = subprocess.run(["kubectl", "-n", namespace_name, "exec", "rsync-"+destination_pvc_name, "--", "/bin/bash", "-c", "apt-get update"])
    result = subprocess.run(["kubectl", "-n", namespace_name, "exec", "rsync-"+destination_pvc_name, "--", "/bin/bash", "-c", "apt-get install sshpass"])
    # "sshpass -p 'rsync' rsync --progress -avz -e 'ssh -o StrictHostKeyChecking=no' root@rsyncd-"+origin_pvc_name+":/data/ /data/"
    result = subprocess.run(["kubectl", "-n", namespace_name, "exec", "rsync-"+destination_pvc_name, "--", "/bin/bash", "-c", "sshpass -p 'rsync' rsync --progress -avz -e 'ssh -o StrictHostKeyChecking=no' root@rsyncd-"+origin_pvc_name+":/data/ /data/"])
