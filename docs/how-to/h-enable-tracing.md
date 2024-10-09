[note]
**Note**: All commands are written for `juju >= v3.1`

If you're using `juju 2.9`, check the [`juju 3.0` Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# Enable tracing
This guide contains the steps to enable tracing with [Grafana Tempo](https://grafana.com/docs/tempo/latest/) for your MySQL Router K8s application. 

To summarize:
* [Deploy the Tempo charm in a COS K8s environment](#heading--deploy)
* [Offer interfaces for cross-model integrations](#heading--offer)
* [Consume and integrate cross-model integrations](#heading--consume)
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

Then, deploy the dependencies of Tempo following [this tutorial](https://discourse.charmhub.io/t/tutorial-deploy-tempo-ha-on-top-of-cos-lite/15489). In particular, we would want to:
- Deploy the minio charm
- Deploy the s3 integrator charm
- Add a bucket in minio using a python script
- Configure s3 integrator with the minio credentials

Finally, deploy and integrate with Tempo HA in a [monolithic setup](https://discourse.charmhub.io/t/tutorial-deploy-tempo-ha-on-top-of-cos-lite/15489#heading--deploy-monolithic-setup).

<a href="#heading--offer"><h2 id="heading--offer"> Offer interfaces </h2></a>

Next, offer interfaces for cross-model integrations from the model where Charmed MySQL Router is deployed.

To offer the Tempo integration, run

```shell
juju offer <tempo_coordinator_k8s_application_name>:tracing
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
k8s    admin/cos.tempo                admin   tracing:tracing
```

Next, consume this offer so that it is reachable from the current model:

```shell
juju consume k8s:admin/cos.tempo
```

<a href="#heading--consume"><h2 id="heading--consume"> Offer interfaces </h2></a>

First, deploy [Grafana Agent K8s](https://charmhub.io/grafana-agent-k8s) from the `latest/edge` channel:
```shell
juju deploy grafana-agent-k8s --channel latest/edge
```

Then, integrate Grafana Agent k8s with the consumed interface from the previous section:
```shell
juju integrate grafana-agent-k8s:tracing tempo:tracing
```

Finally, integrate Charmed MySQL Router K8s with Grafana Agent K8s:
```shell
juju integrate mysql-router-k8s:tracing grafana-agent-k8s:tracing-provider
```

Wait until the model settles. The following is an example of the `juju status --relations` on the Charmed MySQL Router K8s model:

```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
database  k8s         microk8s/localhost  3.5.4    unsupported  18:32:28Z

SAAS   Status  Store       URL
tempo  active  k8s         admin/cos.tempo

App                Version                  Status  Scale  Charm              Channel        Rev  Address         Exposed  Message
grafana-agent-k8s  0.40.4                   active      1  grafana-agent-k8s  latest/edge     93  10.152.183.141  no       grafana-dashboards-provider: off, logging-consumer: off, send-remote-write: off
mysql-k8s          8.0.37-0ubuntu0.22.04.3  active      1  mysql-k8s          8.0/edge       201  10.152.183.58   no       
mysql-router-k8s   8.0.37-0ubuntu0.22.04.3  active      1  mysql-router-k8s                    1  10.152.183.50   no       
mysql-test-app     0.0.2                    active      1  mysql-test-app     latest/stable   51  10.152.183.162  no       

Unit                  Workload  Agent  Address       Ports  Message
grafana-agent-k8s/0*  active    idle   10.1.241.221         grafana-dashboards-provider: off, logging-consumer: off, send-remote-write: off
mysql-k8s/0*          active    idle   10.1.241.213         Primary
mysql-router-k8s/0*   active    idle   10.1.241.222         
mysql-test-app/0*     active    idle   10.1.241.218         

Integration provider                 Requirer                             Interface              Type     Message
grafana-agent-k8s:peers              grafana-agent-k8s:peers              grafana_agent_replica  peer     
grafana-agent-k8s:tracing-provider   mysql-router-k8s:tracing             tracing                regular  
mysql-k8s:database                   mysql-router-k8s:backend-database    mysql_client           regular  
mysql-k8s:database-peers             mysql-k8s:database-peers             mysql_peers            peer     
mysql-k8s:restart                    mysql-k8s:restart                    rolling_op             peer     
mysql-k8s:upgrade                    mysql-k8s:upgrade                    upgrade                peer     
mysql-router-k8s:cos                 mysql-router-k8s:cos                 cos                    peer     
mysql-router-k8s:database            mysql-test-app:database              mysql_client           regular  
mysql-router-k8s:mysql-router-peers  mysql-router-k8s:mysql-router-peers  mysql_router_peers     peer     
mysql-router-k8s:upgrade-version-a   mysql-router-k8s:upgrade-version-a   upgrade                peer     
mysql-test-app:application-peers     mysql-test-app:application-peers     application-peers      peer     
tempo:tracing                        grafana-agent-k8s:tracing            tracing                regular  

```

[note]
**Note:** All traces are exported to Tempo using HTTP. Support for sending traces via HTTPS is an upcoming feature.
[/note]

<a href="#heading--view"><h2 id="heading--view"> View traces </h2></a>

After this is complete, the Tempo traces will be accessible from Grafana under the `Explore` section with `tempo-k8s` as the data source. You will be able to select `mysql-router-k8s` as the `Service Name` under the `Search` tab to view traces belonging to Charmed MySQL Router K8s.

Below is a screenshot demonstrating a Charmed MySQL Router K8s trace:

![Example MySQL Router K8s trace with Grafana Tempo|690x382](upload://kPOyBvWjizYAYoQykaVLSJt0N4n.jpeg)

Feel free to read through the [Tempo HA documentation](https://discourse.charmhub.io/t/charmed-tempo-ha/15531) at your leisure to explore its deployment and its integrations.