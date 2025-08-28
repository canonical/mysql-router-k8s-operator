# Get a MySQL Router K8s up and running

This is part of the [MySQL Router K8s Tutorial](/t/12176). Please refer to this page for more information and the overview of the content. The following document will deploy "MySQL Router" together with "MySQL server" (coming from the separate charm "[Charmed MySQL K8s](https://charmhub.io/mysql-k8s)"). 

## Deploy Charmed MySQL K8s + MySQL Router K8s
> :information_source: **Info**: [the minimum Juju version for "Charmed MySQL K8s" is 2.9.44](https://charmhub.io/mysql-k8s/docs/r-requirements)

To deploy Charmed MySQL K8s + MySQL Router K8s, all you need to do is run the following commands:

```shell
juju deploy mysql-router-k8s --channel 8.0 --trust
juju deploy mysql-k8s --channel 8.0 --trust
```
Note: `--trust` is required to create some K8s resources.

Juju will now fetch charms from [Charmhub](https://charmhub.io/) and begin deploying it to the Microk8s Kubernetes. This process can take several minutes depending on how provisioned (RAM, CPU, etc) your machine is. You can track the progress by running:
```shell
juju status --watch 1s
```

This command is useful for checking the status of Juju applications and gathering information about the machines hosting them. Some of the helpful information it displays include IP addresses, ports, state, etc. The command updates the status of charms every second and as the application starts you can watch the status and messages of their change. Wait until the application is ready - when it is ready, `juju status` will show:
```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.46   unsupported  22:33:45+01:00

App               Version                  Status   Scale  Charm             Channel   Rev  Address        Exposed  Message
mysql-k8s         8.0.34-0ubuntu0.22.04.1  active       1  mysql-k8s         8.0/edge  109  10.152.183.68  no       
mysql-router-k8s  8.0.34-0ubuntu0.22.04.1  blocked      1  mysql-router-k8s  8.0/edge   68  10.152.183.52  no       Missing relation: backend-database

Unit                 Workload  Agent  Address     Ports  Message
mysql-k8s/0*         active    idle   10.1.12.36         Primary
mysql-router-k8s/0*  active    idle   10.1.12.14   
```
> :tipping_hand_man: **Tip**: To exit the screen with `juju status --watch 1s`, enter `Ctrl+c`.
If you want to further inspect juju logs, can watch for logs with `juju debug-log`.
More info on logging at [juju logs](https://juju.is/docs/olm/juju-logs).

At this stage MySQL Router will stay in blocked state due to missing relation/integration with MySQL DB, let's integrate them:
```shell
juju integrate mysql-k8s mysql-router-k8s
```
Shortly the `juju status` will report new blocking reason `Missing relation: database` as it waits for a client to consume DB service, let's deploy [data-integrator](https://charmhub.io/data-integrator) and request access to database `test123`:
```shell
juju deploy data-integrator --config database-name=test123
juju relate data-integrator mysql-router-k8s
```
In couple of seconds, the status will be happy for entire model:
```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.46   unsupported  22:37:41+01:00

App               Version                  Status  Scale  Charm             Channel   Rev  Address         Exposed  Message
data-integrator                            active      1  data-integrator   stable     13  10.152.183.142  no       
mysql-k8s         8.0.34-0ubuntu0.22.04.1  active      1  mysql-k8s         8.0/edge  109  10.152.183.68   no       
mysql-router-k8s  8.0.34-0ubuntu0.22.04.1  active      1  mysql-router-k8s  8.0/edge   68  10.152.183.52   no       

Unit                 Workload  Agent  Address     Ports  Message
data-integrator/0*   active    idle   10.1.12.3          
mysql-k8s/0*         active    idle   10.1.12.36         Primary
mysql-router-k8s/0*  active    idle   10.1.12.14     
```

## Access database

The first action most users take after installing MySQL is accessing MySQL. The easiest way to do this is via the [MySQL Command-Line Client](https://dev.mysql.com/doc/refman/8.0/en/mysql.html) `mysql`. Connecting to the database requires that you know the values for `host`, `username` and `password`. To retrieve the necessary fields please run data-integrator action `get-credentials`:
```shell
juju run data-integrator/leader get-credentials
```
Running the command should output:
```yaml
mysql:
  database: test123
  endpoints: mysql-router-k8s.tutorial.svc.cluster.local:6446
  password: Nu7wK85QU7dpVX66X56lozji
  read-only-endpoints: mysql-router-k8s.tutorial.svc.cluster.local:6447
  username: relation-4-6
```

The host’s IP address can be found with `juju status` (the application hosting the Router MySQL K8s application):
```shell
...
App               Version                  Status   Scale  Charm             Channel   Rev  Address         Exposed  Message
mysql-router-k8s  8.0.34-0ubuntu0.22.04.1  active       1  mysql-router-k8s  8.0/edge   68  10.152.183.52   no  
...
```

To access the MySQL database via MySQL Router choose read-write (port 6446) or read-only (port 6447) endpoints:
```shell
mysql -h 10.152.183.52 -P6446 -urelation-4-6 -pNu7wK85QU7dpVX66X56lozji test123
```

Inside MySQL list DBs available on the host `show databases`:
```shell
mysql> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| performance_schema |
| test123            |
+--------------------+
3 rows in set (0.00 sec)

```
> :tipping_hand_man: **Tip**: if at any point you'd like to leave the MySQL client, enter `Ctrl+d` or type `exit`.

You can now interact with MySQL directly using any [MySQL Queries](https://dev.mysql.com/doc/refman/8.0/en/entering-queries.html). For example entering `SELECT VERSION(), CURRENT_DATE;` should output something like:
```shell
mysql> SELECT VERSION(), CURRENT_DATE;
+-------------------------+--------------+
| VERSION()               | CURRENT_DATE |
+-------------------------+--------------+
| 8.0.34-0ubuntu0.22.04.1 | 2023-10-17    |
+-------------------------+--------------+
1 row in set (0.00 sec)
```

Feel free to test out any other MySQL queries. When you’re ready to leave the MySQL shell you can just type `exit`. Now you will be in your original shell where you first started the tutorial; here you can interact with Juju and Microk8s.

### Remove the user

To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:
```shell
juju remove-relation mysql-router-k8s data-integrator
```

Now try again to connect to the same MySQL Router K8s you just used above:
```shell
mysql -h 10.152.183.52 -P6446 -urelation-4-6 -pNu7wK85QU7dpVX66X56lozji test123
```

This will output an error message:
```shell
ERROR 1045 (28000): Access denied for user 'relation-4-6'@'mysql-router-k8s-1.mysql-router-k8s-endpoints.tutorial.svc.clust' (using password: YES)
```
As this user no longer exists. This is expected as `juju remove-relation mysql-router-k8s data-integrator` also removes the user.
Note: data stay remain on the server at this stage!

Relate the the two applications again if you wanted to recreate the user:
```shell
juju relate data-integrator mysql-router-k8s
```
Re-relating generates a new user and password:
```shell
juju run data-integrator/leader get-credentials
```
You can connect to the database with this new credentials.
From here you will see all of your data is still present in the database.