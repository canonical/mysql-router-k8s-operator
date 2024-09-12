[note]
**Note**: All commands are written for [`juju >= v3.0`](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022)
[/note]

# How to enable monitoring with COS and Grafana

This guide goes over the steps to integrate MySQL Router K8s deployment with COS to enable monitoring in Grafana.

To learn about Alert Rules, see [Charmed MySQL K8s > How to enable COS Alert Rules](https://charmhub.io/mysql-k8s/docs/h-enable-alert-rules).

## Prerequisites
* A deployed [Charmed MySQL Router K8s](/t/12233) operator
* A deployed [‘cos-lite’ bundle in a Kubernetes environment](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s)

## Summary
* [Offer interfaces via the COS controller](#offer-interfaces-via-the-cos-controller)
* [Consume offers via the MySQL Router K8s model](#consume-offers-via-the-mysql-router-k8s-model)
* [Deploy and integrate Grafana](#deploy-and-integrate-grafana)
* [Connect to the Grafana web interface](#connect-to-the-grafana-web-interface)

---

## Offer interfaces via the COS controller

First, we will switch to the COS K8s environment and offer COS interfaces to be cross-model integrated with the Charmed MySQLRouter K8s model.

To switch to the Kubernetes controller for the COS model, run

```shell
juju switch <k8s_controller>:<cos_model_name>
```

To offer the COS interfaces, run
```shell
juju offer grafana:grafana-dashboard
juju offer loki:logging
juju offer prometheus:receive-remote-write
```
## Consume offers via the MySQL Router K8s model

Next, we will switch to the Charmed MySQL Router K8s model, find offers, and consume them.

We are currently on the Kubernetes controller for the COS model. To switch to the MySQL Router K8smodel, run

```shell
juju switch <k8s_db_controller>:<mysql_router_model_name>
```
Display a list of available interfaces with the following command:
```shell
juju find-offers <k8s_cos_controller>:  # Do not miss the ':' here!
```

In the sample output below, `k8s` is the k8s controller name and `cos` is the model where `cos-lite` has been deployed:

```shell
Store  URL               	Access  Interfaces
k8s	admin/cos.grafana 	admin   grafana_dashboard:grafana-dashboard
k8s	admin/cos.loki    	admin   loki_push_api:logging
k8s	admin/cos.prometheus  admin   prometheus_remote_write:receive-remote-write
```

To consume offers to be reachable in the current model, run

```shell
juju consume k8s:admin/cos.grafana
juju consume k8s:admin/cos.loki
juju consume k8s:admin/cos.prometheus
```

## Deploy and integrate Grafana

First, deploy [grafana-agent](https://charmhub.io/grafana-agent):
```shell
juju deploy grafana-agent-k8s --trust
```
Then, integrate (previously known as "[relate](https://juju.is/docs/juju/integration)") `grafana-agent` with Charmed MySQL Router K8s:
```shell
juju integrate grafana-agent-k8s grafana
juju integrate grafana-agent-k8s loki
juju integrate grafana-agent-k8s prometheus
```
Finally, integrate `grafana-agent-k8s` with the consumed COS offers:
```shell
juju integrate grafana-agent-k8s mysql-router-k8s:grafana-dashboard
juju integrate grafana-agent-k8s mysql-router-k8s:logging
juju integrate grafana-agent-k8s mysql-router-k8s:metrics-endpoint
```

After this is complete, Grafana will show the new dashboards `MySQLRouter Exporter` and allow access for Charmed MySQL Router K8s logs on Loki.

An example of `juju status` on Charmed MySQL Router K8s model:

```shell
ubuntu@localhost:~$ juju status
Model 	Controller  Cloud/Region    	Version  SLA      	Timestamp
database  k8s     	microk8s/localhost  3.1.8	unsupported  13:27:08Z

SAAS    	Status  Store  URL
grafana 	active  k8s	admin/cos.grafana
loki    	active  k8s	admin/cos.loki
prometheus  active  k8s	admin/cos.prometheus

App            	   Version              	Status  Scale  Charm           	  Channel 	  Rev  Address     	   Exposed  Message
grafana-agent-k8s  0.35.2               	active  	1  grafana-agent-k8s  stable   	  64   10.152.183.141  no  	 
mysql-k8s      	   8.0.35-0ubuntu0.22.04.1  active  	1  mysql-k8s      	  8.0/stable  127  10.152.183.105  no  	 
mysql-router-k8s   8.0.36-0ubuntu0.22.04.1  active  	1  mysql-router-k8s   8.0/edge	  102  10.152.183.92   no  	 
mysql-test-app 	   0.0.2                	active  	1  mysql-test-app 	  stable   	  36   10.152.183.35   no  	 

Unit              	Workload    Agent  Address   	Ports  Message
grafana-agent-k8s/0*  active	idle   10.1.241.243    	 
mysql-k8s/0*      	  active	idle   10.1.241.239        Primary
mysql-router-k8s/0*   active	idle   10.1.241.240    	 
mysql-test-app/0* 	  active	idle   10.1.241.241    	 
```

An example of `juju status` on the COS K8s model:

```shell
ubuntu@localhost:~$ juju status
Model  Controller  Cloud/Region    	Version  SLA      	Timestamp
cos	k8s     	microk8s/localhost  3.1.8	unsupported  13:28:02Z

App       	Version  Status  Scale  Charm         	Channel  Rev  Address     	Exposed  Message
alertmanager  0.27.0   active  	1  alertmanager-k8s  stable   106  10.152.183.197  no  	 
catalogue          	active  	1  catalogue-k8s 	stable	33  10.152.183.38   no  	 
grafana   	9.5.3	active  	1  grafana-k8s   	stable   106  10.152.183.238  no  	 
loki      	2.9.4	active  	1  loki-k8s      	stable   124  10.152.183.84   no  	 
prometheus	2.49.1   active  	1  prometheus-k8s	stable   171  10.152.183.182  no  	 
traefik   	2.10.5   active  	1  traefik-k8s   	stable   174  10.0.0.44   	no  	 

Unit         	Workload  Agent  Address   	Ports  Message
alertmanager/0*  active	idle   10.1.241.222    	 
catalogue/0* 	active	idle   10.1.241.225    	 
grafana/0*   	active	idle   10.1.241.228    	 
loki/0*      	active	idle   10.1.241.226    	 
prometheus/0*	active	idle   10.1.241.227    	 
traefik/0*   	active	idle   10.1.241.221    	 

Offer   	Application  Charm       	Rev  Connected  Endpoint          	Interface            	Role
grafana 	grafana  	grafana-k8s 	106  2/2    	grafana-dashboard 	grafana_dashboard    	requirer
loki    	loki     	loki-k8s    	124  2/2    	logging           	loki_push_api        	provider
prometheus  prometheus   prometheus-k8s  171  2/2    	receive-remote-write  prometheus_remote_write  provider
```

## Connect to Grafana web interface

To connect to the Grafana web interface, follow the [Browse dashboards](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s?_ga=2.201254254.1948444620.1704703837-757109492.1701777558#heading--browse-dashboards) section of the MicroK8s "Getting started" guide.

```shell
juju run grafana/leader get-admin-password --model <k8s_controller>:<cos_model_name>
```