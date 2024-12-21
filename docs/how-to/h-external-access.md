# How to connect DB from outside of Kubernetes

To expose a Charmed MySQL K8s database externally, this charm (MySQL Router K8s) should be deployed and related with the Charmed MySQL K8s application. Charmed MySQL Router K8s then provides a configuration option `expose-external` (with options `false`, `nodeport` and `loadbalancer`) to control precisely how the database will be externally exposed.

By default (when `expose-external=false`), Charmed MySQL Router K8s creates a K8s service of type `ClusterIP` which it provides as endpoints to the related client applications. These endpoints are only accessible from within the K8s namespace (or juju model) where the MySQL Router K8s application is deployed.

Below is a juju model where MySQL Router K8s is related to MySQL K8s and Data Integrator, which we will later use to demonstrate the configuration of `expose-external`:

```shell
$ juju status --relations
Model     Controller  Cloud/Region        Version  SLA          Timestamp
database  uk8s-3-6-1  microk8s/localhost  3.6.1    unsupported  14:39:08Z

App               Version                  Status  Scale  Charm             Channel        Rev  Address         Exposed  Message
data-integrator                            active      1  data-integrator   latest/stable   78  10.152.183.44   no       
mysql-k8s         8.0.39-0ubuntu0.22.04.1  active      1  mysql-k8s         8.0/candidate  210  10.152.183.143  no       
mysql-router-k8s  8.0.39-0ubuntu0.22.04.1  active      1  mysql-router-k8s  8.0/candidate  531  10.152.183.201  no       

Unit                 Workload  Agent  Address       Ports  Message
data-integrator/0*   active    idle   10.1.241.219         
mysql-k8s/0*         active    idle   10.1.241.217         Primary
mysql-router-k8s/0*  active    idle   10.1.241.218         

Integration provider                   Requirer                               Interface              Type     Message
data-integrator:data-integrator-peers  data-integrator:data-integrator-peers  data-integrator-peers  peer     
mysql-k8s:database                     mysql-router-k8s:backend-database      mysql_client           regular  
mysql-k8s:database-peers               mysql-k8s:database-peers               mysql_peers            peer     
mysql-k8s:restart                      mysql-k8s:restart                      rolling_op             peer     
mysql-k8s:upgrade                      mysql-k8s:upgrade                      upgrade                peer     
mysql-router-k8s:cos                   mysql-router-k8s:cos                   cos                    peer     
mysql-router-k8s:database              data-integrator:mysql                  mysql_client           regular  
mysql-router-k8s:mysql-router-peers    mysql-router-k8s:mysql-router-peers    mysql_router_peers     peer     
mysql-router-k8s:upgrade-version-a     mysql-router-k8s:upgrade-version-a     upgrade                peer
```

When `expose-external=false`, the following shows the endpoints returned to the client:

```shell
$ juju run data-integrator/0 get-credentials
mysql:
  data: '{"database": "test-database", "external-node-connectivity": "true", "requested-secrets":
    "[\"username\", \"password\", \"tls\", \"tls-ca\", \"uris\"]"}'
  database: test-database
  endpoints: mysql-router-k8s-service.database.svc.cluster.local:6446
  password: VRLNoVx6Br4Vn5SNHdoMK52Q
  read-only-endpoints: mysql-router-k8s-service.database.svc.cluster.local:6447
  username: relation-7_4fc92c2813524d6-8
ok: "True"
```

The following shows a mysql client connecting to the the provided endpoints from the data integrator unit (which is deployed in the same K8s namespace, i.e. the same juju model, as MySQL Router K8s):

```shell
$ juju ssh data-integrator/0 bash 
root@data-integrator-0:/var/lib/juju# mysql -h mysql-router-k8s-service.database.svc.cluster.local -P 6446 -u relation-7_4fc92c2813524d6-8 -pVRLNoVx6Br4Vn5SNHdoMK52Q
mysql> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| performance_schema |
| test-database      |
+--------------------+
3 rows in set (0.01 sec)

mysql> exit;
Bye
root@data-integrator-0:/var/lib/juju# mysql -h mysql-router-k8s-service.database.svc.cluster.local -P 6447 -u relation-7_4fc92c2813524d6-8 -pVRLNoVx6Br4Vn5SNHdoMK52Q
mysql> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| performance_schema |
| test-database      |
+--------------------+
3 rows in set (0.01 sec)
```

## External Access

MySQL Router K8s can be made externally accessible by setting `expose-external=nodeport` (corresponding to K8s NodePort service) or `expose-external=loadbalancer` (corresponding to K8s LoadBalancer service).

When `expose-external=nodeport`, MySQL Router K8s will provide as endpoints comma-separated node:port values of the nodes where the MySQL Router K8s units are scheduled.

```shell
$ juju run data-integrator/0 get-credentials
mysql:
  data: '{"database": "test-database", "external-node-connectivity": "true", "requested-secrets":
    "[\"username\", \"password\", \"tls\", \"tls-ca\", \"uris\"]"}'
  database: test-database
  endpoints: 10.0.0.44:31604
  password: VRLNoVx6Br4Vn5SNHdoMK52Q
  read-only-endpoints: 10.0.0.44:31907
  username: relation-7_4fc92c2813524d6-8
ok: "True"

$ charmed-mysql.mysql -h 10.0.0.44 -P 31604 -u relation-7_4fc92c2813524d6-8 -pVRLNoVx6Br4Vn5SNHdoMK52Q
mysql> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| performance_schema |
| test-database      |
+--------------------+
3 rows in set (0.00 sec)

$ charmed-mysql.mysql -h 10.0.0.44 -P 31907 -u relation-7_4fc92c2813524d6-8 -pVRLNoVx6Br4Vn5SNHdoMK52Q
mysql> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| performance_schema |
| test-database      |
+--------------------+
3 rows in set (0.00 sec)
```

Similarly, when `expose-external=loadbalancer`, MySQL Router K8s will provide as endpoints comma-separated node:port values of the load balancer nodes associated with the MySQL Router K8s service.

```shell
$ juju run data-integrator/0 get-credentials
mysql:
  data: '{"database": "test-database", "external-node-connectivity": "true", "requested-secrets":
    "[\"username\", \"password\", \"tls\", \"tls-ca\", \"uris\"]"}'
  database: test-database
  endpoints: 10.0.0.44:6446
  password: VRLNoVx6Br4Vn5SNHdoMK52Q
  read-only-endpoints: 10.0.0.44:6447
  username: relation-7_4fc92c2813524d6-8
ok: "True"

$ charmed-mysql.mysql -h 10.0.0.44 -P 6446 -u relation-7_4fc92c2813524d6-8 -pVRLNoVx6Br4Vn5SNHdoMK52Q
mysql> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| performance_schema |
| test-database      |
+--------------------+
3 rows in set (0.00 sec)

$ charmed-mysql.mysql -h 10.0.0.44 -P 6447 -u relation-7_4fc92c2813524d6-8 -pVRLNoVx6Br4Vn5SNHdoMK52Q
mysql> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| performance_schema |
| test-database      |
+--------------------+
3 rows in set (0.00 sec)
```

[note]
**Note**:  The K8s service created by MySQL Router K8s is owned by the K8s StatefulSet that represents the MySQL Router K8s juju application. Thus, the K8s service is cleaned up when the MySQL Router K8s application is removed. 
[/note]