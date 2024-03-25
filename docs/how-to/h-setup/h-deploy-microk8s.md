# Deploy MySQL Router K8s

Please follow the [MySQL Router K8s Tutorial](/t/12176) for technical details and explanations.

Short story for your Ubuntu 22.04 LTS (`Wordpress` used as an client example for `MySQL Router`:
```shell
sudo snap install multipass
multipass launch --cpus 4 --memory 8G --disk 30G --name my-vm charm-dev # tune CPU/RAM/HDD accordingly to your needs
multipass shell my-vm

juju add-model wordpress-demo
juju deploy mysql-k8s --channel 8.0/stable --trust # --config profile=testing
juju deploy mysql-router-k8s --channel 8.0/stable --trust

juju integrate mysql-k8s mysql-router-k8s

juju status --watch 1s
```

The expected result:
```shell 
Model           Controller  Cloud/Region        Version  SLA          Timestamp
wordpress-demo  microk8s    microk8s/localhost  3.1.6    unsupported  14:39:27+02:00

App               Version                  Status   Scale  Charm             Channel     Rev  Address         Exposed  Message
mysql-k8s         8.0.34-0ubuntu0.22.04.1  active       1  mysql-k8s         8.0/stable   99  10.152.183.189  no       
mysql-router-k8s  8.0.34-0ubuntu0.22.04.1  blocked      1  mysql-router-k8s  8.0/stable   69  10.152.183.81   no       Missing relation: database

Unit                 Workload  Agent  Address     Ports  Message
mysql-k8s/0*         active    idle   10.1.12.61         Primary
mysql-router-k8s/0*  active    idle   10.1.12.16         
```
The charm MySQL Router K8s is now waiting for relations with a client application, e.g. [mysql-test-app](https://charmhub.io/mysql-test-app), [wordpress](https://charmhub.io/wordpress-k8s), ...

Check the [Testing](/t/12234) reference to test your deployment.