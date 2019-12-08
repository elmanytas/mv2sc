# Move storageclass

From a deployment and a storageclass:
- scale deployment to 0
- for each volume of deployment
  - creates new volume in storageclass
  - creates a pod with rsyncd in new volume
  - creates a pod with rsync in old volume
  - sync data
  - reconfigure deployment with new volume
- scale deployment to 1

