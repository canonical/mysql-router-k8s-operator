[note]
**Note**: All commands are written for `juju >= v3.1`

If you're using `juju 2.9`, check the [`juju 3.0` Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# Enable tracing
This guide contains the steps to enable tracing with [Grafana Tempo](https://grafana.com/docs/tempo/latest/) for your MySQL Router K8s application. 

To summarize:
* [Deploy the Tempo charm in a COS K8s environment](#heading--deploy)
* [Integrate it with the COS charms](#heading--integrate)
* [Offer interfaces for cross-model integrations](#heading--offer)
* [View MySQL Router K8s traces on Grafana](#heading--view)


[note type="caution"]
**Warning:** This is feature is in development. It is **not recommended** for production environments. 

This feature is available for Charmed MySQL Router K8s revision 117+ only.
[/note]

## Prerequisites
Enabling tracing with Tempo requires that you:
- Have deployed a Charmed MySQL K8s application
  - See [How to manage MySQL K8s units](https://discourse.charmhub.io/t/charmed-mysql-k8s-how-to-manage-units/9659)
- Have deployed a Charmed MySQL Router K8s application in the same model as the Charmed MySQL application
  - See [How to manage MySQL Router K8s units](https://discourse.charmhub.io/t/mysql-router-k8s-how-to-manage-units/12240)
- Have deployed a 'cos-lite' bundle from the `latest/edge` track in a Kubernetes environment
  - See [Getting started on MicroK8s](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s)

---
<a href="#heading--deploy"><h2 id="heading--deploy"> Deploy Tempo </h2></a>

First, switch to the Kubernetes controller where the COS model is deployed:

```shell
juju switch <k8s_controller_name>:<cos_model_name>
```
Then, deploy the [`tempo-k8s`](https://charmhub.io/tempo-k8s) charm:
```shell
juju deploy -n 1 tempo-k8s --channel latest/edge
```

<a href="#heading--integrate"><h2 id="heading--integrate"> Integrate with the COS charms </h2></a>

Integrate `tempo-k8s` with the COS charms as follows:

```shell
juju integrate tempo-k8s:grafana-dashboard grafana:grafana-dashboard
juju integrate tempo-k8s:grafana-source grafana:grafana-source
juju integrate tempo-k8s:ingress traefik:traefik-route
juju integrate tempo-k8s:metrics-endpoint prometheus:metrics-endpoint
juju integrate tempo-k8s:logging loki:logging
```
If you would like to instrument traces from the COS charms as well, create the following integrations:
```shell
juju integrate tempo-k8s:tracing alertmanager:tracing
juju integrate tempo-k8s:tracing catalogue:tracing
juju integrate tempo-k8s:tracing grafana:tracing
juju integrate tempo-k8s:tracing loki:tracing
juju integrate tempo-k8s:tracing prometheus:tracing
juju integrate tempo-k8s:tracing traefik:tracing
```

<a href="#heading--offer"><h2 id="heading--offer"> Offer interfaces </h2></a>

Next, offer interfaces for cross-model integrations from the model where Charmed MySQL Router is deployed.

To offer the Tempo integration, run

```shell
juju offer tempo-k8s:tracing
```

Then, switch to the Charmed MySQL Router K8s model, find the offers, and integrate (relate) with them:

```shell
juju switch <k8s_controller_name>:<mysql_router_k8s_model_name>

juju find-offers <k8s_controller_name>:  
```
> :exclamation: Do not miss the "`:`" in the command above.

Below is a sample output where `k8s` is the K8s controller name and `cos` is the model where `cos-lite` and `tempo-k8s` are deployed:

```shell
Store  URL                            Access  Interfaces
k8s    admin/cos.tempo-k8s            admin   tracing:tracing
```

Next, consume this offer so that it is reachable from the current model:

```shell
juju consume k8s:admin/cos.tempo-k8s
```

Relate Charmed MySQL Router K8s with the above consumed interface:

```shell
juju integrate mysql-router-k8s:tracing tempo-k8s:tracing
```

Wait until the model settles. The following is an example of the `juju status --relations` on the Charmed MySQL Router K8s model:

```shell
Model      Controller  Cloud/Region        Version  SLA          Timestamp
database   k8s         microk8s/localhost  3.4.3    unsupported  20:15:35Z

SAAS       Status  Store  URL
tempo-k8s  active  k8s    admin/cos.tempo-k8s

App               Version                  Status  Scale  Charm             Channel        Rev  Address         Exposed  Message
mysql-k8s         8.0.36-0ubuntu0.22.04.1  active      1  mysql-k8s         8.0/edge       153  10.152.183.113  no       
mysql-router-k8s  8.0.36-0ubuntu0.22.04.1  active      1  mysql-router-k8s  8.0/edge       120  10.152.183.129  no       
mysql-test-app    0.0.2                    active      1  mysql-test-app    latest/stable   37  10.152.183.48   no       Last written value=12318

Unit                 Workload  Agent  Address       Ports  Message
mysql-k8s/0*         active    idle   10.1.241.204         Primary
mysql-router-k8s/0*  active    idle   10.1.241.218         
mysql-test-app/0*    active    idle   10.1.241.231         Last written value=12318

Integration provider                 Requirer                             Interface           Type     Message
mysql-k8s:database                   mysql-router-k8s:backend-database    mysql_client        regular  
mysql-k8s:database-peers             mysql-k8s:database-peers             mysql_peers         peer     
mysql-k8s:restart                    mysql-k8s:restart                    rolling_op          peer     
mysql-k8s:upgrade                    mysql-k8s:upgrade                    upgrade             peer     
mysql-router-k8s:cos                 mysql-router-k8s:cos                 cos                 peer     
mysql-router-k8s:database            mysql-test-app:database              mysql_client        regular  
mysql-router-k8s:mysql-router-peers  mysql-router-k8s:mysql-router-peers  mysql_router_peers  peer     
mysql-router-k8s:upgrade-version-a   mysql-router-k8s:upgrade-version-a   upgrade             peer     
mysql-test-app:application-peers     mysql-test-app:application-peers     application-peers   peer     
tempo-k8s:tracing                    mysql-router-k8s:tracing             tracing             regular  

```

[note]
**Note:** All traces are exported to Tempo using HTTP. Support for sending traces via HTTPS is an upcoming feature.
[/note]

<a href="#heading--view"><h2 id="heading--view"> View traces </h2></a>

After this is complete, the Tempo traces will be accessible from Grafana under the `Explore` section with `tempo-k8s` as the data source. You will be able to select `mysql-router-k8s` as the `Service Name` under the `Search` tab to view traces belonging to Charmed MySQL Router K8s.

Below is a screenshot demonstrating a Charmed MySQL Router K8s trace:

![Example MySQL Router K8s trace with Grafana Tempo|690x382](upload://kPOyBvWjizYAYoQykaVLSJt0N4n.jpeg)

Feel free to read through the [Tempo documentation](https://discourse.charmhub.io/t/tempo-k8s-docs-index/14005) at your leisure to explore its deployment and its integrations.