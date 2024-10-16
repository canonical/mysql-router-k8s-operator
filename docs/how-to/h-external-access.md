# How to connect DB from outside of Kubernetes

To make the Charmed MySQL K8s database reachable from outside the Kubernetes cluster, this charm MySQL Router K8s should be deployed. It creates and manages several K8s services including the NodePort one:

```shell
kubectl get services -n <model>
```

```
TODO
```

The `TODO` NodePort service exposes a port to access both R/W and R/O MySQL servers from outside of K8s. The charm opens NodePort if requested in relation as `external-node-connectivity: true`. Example (relate mysql-router-k8s with data-integrator):
```shell
> juju run data-integrator/0 get-credentials
...
TODO
```
> **Note**: the relation flag `external-node-connectivity` is experimental and will be replaced in the future. Follow https://warthogs.atlassian.net/browse/DPE-5636 for more details. 

> **Note**: The `mysql-router-k8s` and `mysql-router-k8s-endpoints` ClusterIP services seen above are created for every Juju application by default as part of the StatefulSet they are associated with. These services are not relevant to users and can be safely ignored.

## Client connections using the bootstrap service

A client can be configured to connect to the `TODO` service using a Kubernetes NodeIP, and desired NodePort.

To get NodeIPs:

```shell
kubectl get nodes -o wide -n model | awk -v OFS='\t\t' '{print $1, $6}'
```

```
NAME        INTERNAL-IP
node-0      10.155.67.110
node-1      10.155.67.120
node-2      10.155.67.130
```

NodeIPs are different for each deployment as they are randomly allocated.
For the example from the previous section, the created NodePorts was:

```shell
TODO
```

Users can use this NodePort to access read-write / Primary server from outside of K8s:
```shell
TODO
```
Read-only servers can be accessed using the `_readonly` suffix to the desired DB name:
```shell
TODO
```