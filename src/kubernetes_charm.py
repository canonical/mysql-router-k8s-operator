#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL Router Kubernetes charm"""

import logging
import socket
import typing

import lightkube
import lightkube.models.core_v1
import lightkube.models.meta_v1
import lightkube.resources.core_v1
import ops

import abstract_charm
import kubernetes_logrotate
import kubernetes_upgrade
import logrotate
import relations.tls
import rock
import upgrade

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class KubernetesRouterCharm(abstract_charm.MySQLRouterCharm):
    """MySQL Router Kubernetes charm"""

    _READ_WRITE_PORT = 6446
    _READ_ONLY_PORT = 6447

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._namespace = self.model.name

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(
            self.on[rock.CONTAINER_NAME].pebble_ready, self._on_workload_container_pebble_ready
        )
        self.framework.observe(self.on.stop, self._on_stop)
        # TODO VM TLS: Move to super class
        self.tls = relations.tls.RelationEndpoint(self)

    @property
    def _subordinate_relation_endpoint_names(self) -> typing.Optional[typing.Iterable[str]]:
        return

    @property
    def tls_certificate_saved(self) -> bool:
        return self.tls.certificate_saved

    @property
    def _tls_key(self) -> typing.Optional[str]:
        return self.tls.key

    @property
    def _tls_certificate(self) -> typing.Optional[str]:
        return self.tls.certificate

    @property
    def _tls_certificate_authority(self) -> typing.Optional[str]:
        return self.tls.certificate_authority

    @property
    def _container(self) -> rock.Rock:
        return rock.Rock(unit=self.unit)

    @property
    def _logrotate(self) -> logrotate.LogRotate:
        return kubernetes_logrotate.LogRotate(container_=self._container)

    @property
    def _upgrade(self) -> typing.Optional[kubernetes_upgrade.Upgrade]:
        try:
            return kubernetes_upgrade.Upgrade(self)
        except upgrade.PeerRelationNotReady:
            pass

    def reconcile_node_port(self, event) -> None:
        """Reconcile node port."""
        self._patch_service()

    @property
    def model_service_domain(self) -> str:
        """K8s service domain for Juju model"""
        # Example: "mysql-router-k8s-0.mysql-router-k8s-endpoints.my-model.svc.cluster.local"
        fqdn = socket.getfqdn()
        # Example: "mysql-router-k8s-0.mysql-router-k8s-endpoints."
        prefix = f"{self.unit.name.replace('/', '-')}.{self.app.name}-endpoints."
        assert fqdn.startswith(f"{prefix}{self.model.name}.")
        # Example: my-model.svc.cluster.local
        return fqdn.removeprefix(prefix)

    @property
    def _host(self) -> str:
        """K8s service hostname for MySQL Router"""
        # Example: mysql-router-k8s.my-model.svc.cluster.local
        return f"{self.app.name}.{self.model_service_domain}"

    @property
    def _read_write_endpoint(self) -> str:
        return f"{self._host}:{self._READ_WRITE_PORT}"

    @property
    def _read_only_endpoint(self) -> str:
        return f"{self._host}:{self._READ_ONLY_PORT}"

    @property
    def _exposed_read_write_endpoint(self) -> str:
        return f"{self.get_k8s_node_ip()}:{self.node_port('rw')}"

    @property
    def _exposed_read_only_endpoint(self) -> str:
        return f"{self.get_k8s_node_ip()}:{self.node_port('ro')}"

    def _patch_service(self) -> None:
        """Patch Juju-created k8s service.

        The k8s service will be tied to pod-0 so that the service is auto cleaned by
        k8s when the last pod is scaled down.

        If the service is set for unexpose=True, the NodePort will be removed.
        Otherwise, the service will be set to NodePort if at least one client requests
        that the service be exposed.
        """
        logger.debug("Patching k8s service")
        client = lightkube.Client()
        pod0 = client.get(
            res=lightkube.resources.core_v1.Pod,
            name=self.app.name + "-0",
            namespace=self.model.name,
        )
        service = lightkube.resources.core_v1.Service(
            metadata=lightkube.models.meta_v1.ObjectMeta(
                name=self.app.name,
                namespace=self.model.name,
                ownerReferences=pod0.metadata.ownerReferences,
                labels={
                    "app.kubernetes.io/name": self.app.name,
                },
            ),
            spec=lightkube.models.core_v1.ServiceSpec(
                ports=[
                    lightkube.models.core_v1.ServicePort(
                        name="mysql-rw",
                        port=self._READ_WRITE_PORT,
                        targetPort=self._READ_WRITE_PORT,  # Value ignored if NodePort
                    ),
                    lightkube.models.core_v1.ServicePort(
                        name="mysql-ro",
                        port=self._READ_ONLY_PORT,
                        targetPort=self._READ_ONLY_PORT,  # Value ignored if NodePort
                    ),
                ],
                # If all exposed services are removed, the NodePort will be removed
                type=(
                    "NodePort" if self._database_provides.external_connectivity else "ClusterIP"
                ),
                selector={"app.kubernetes.io/name": self.app.name},
            ),
        )
        client.patch(
            res=lightkube.resources.core_v1.Service,
            obj=service,
            name=service.metadata.name,
            namespace=service.metadata.namespace,
            force=True,
            field_manager=self.app.name,
        )
        logger.debug("Patched k8s service")

    def _get_node_name_for_pod(self) -> str:
        """Return the node name for a given pod."""
        pod = lightkube.Client().get(
            lightkube.resources.core_v1.Pod,
            name=self.unit.name.replace("/", "-"),
            namespace=self._namespace,
        )
        return pod.spec.nodeName

    # =======================
    #  Handlers
    # =======================

    def get_all_k8s_node_hostnames_and_ips(self) -> typing.Tuple[typing.List[str]]:
        """Return all node hostnames and IPs registered in k8s."""
        node = lightkube.Client().get(
            lightkube.resources.core_v1.Node,
            name=self._get_node_name_for_pod(),
            namespace=self._namespace,
        )
        hostnames, ips = [], []
        for a in node.status.addresses:
            if a.type in ["ExternalIP", "InternalIP"]:
                ips.append(a.address)
            elif a.type == "Hostname":
                hostnames.append(a.address)
        return hostnames, ips

    def get_k8s_node_ip(self) -> typing.Optional[str]:
        """Return node IP."""
        node = lightkube.Client().get(
            lightkube.resources.core_v1.Node,
            name=self._get_node_name_for_pod(),
            namespace=self._namespace,
        )
        # [
        #    NodeAddress(address='192.168.0.228', type='InternalIP'),
        #    NodeAddress(address='example.com', type='Hostname')
        # ]
        # Remember that OpenStack, for example, will return an internal hostname, which is not
        # accessible from the outside. Give preference to ExternalIP, then InternalIP first
        # Separated, as we want to give preference to ExternalIP, InternalIP and then Hostname
        for typ in ["ExternalIP", "InternalIP", "Hostname"]:
            for a in node.status.addresses:
                if a.type == typ:
                    return a.address
        return None

    def node_port(self, port_type="rw") -> int:
        """Return node port."""
        service = lightkube.Client().get(
            lightkube.resources.core_v1.Service, self.app.name, namespace=self._namespace
        )
        if not service or not service.spec.type == "NodePort":
            return -1
        # svc.spec.ports
        # [ServicePort(port=3306, appProtocol=None, name=None, nodePort=31438, protocol='TCP', targetPort=3306)]
        port = self._READ_ONLY_PORT if port_type == "ro" else self._READ_WRITE_PORT
        logger.debug(f"Looking for NodePort for {port_type} in {service.spec.ports}")
        for svc_port in service.spec.ports:
            if svc_port.port == port:
                return svc_port.nodePort
        raise Exception(f"NodePort not found for {port_type}")

    def _on_install(self, _) -> None:
        """Open ports & patch k8s service."""
        if ops.JujuVersion.from_environ().supports_open_port_on_k8s:
            for port in (self._READ_WRITE_PORT, self._READ_ONLY_PORT, 6448, 6449):
                self.unit.open_port("tcp", port)
        if not self.unit.is_leader():
            return
        try:
            self._patch_service()
        except lightkube.ApiError:
            logger.exception("Failed to patch k8s service")
            raise

    def _on_workload_container_pebble_ready(self, _) -> None:
        self.unit.set_workload_version(self.get_workload(event=None).version)
        self.reconcile()

    def _on_stop(self, _) -> None:
        # During the stop event, the unit could be upgrading, scaling down, or just restarting.
        if self._unit_lifecycle.tearing_down_and_app_active:
            # Unit is tearing down and 1+ other units are not tearing down (scaling down)
            # The partition should never be greater than the highest unit number, since that will
            # cause `juju refresh` to have no effect
            return
        unit_number = int(self.unit.name.split("/")[-1])
        # Raise partition to prevent other units from restarting if an upgrade is in progress.
        # If an upgrade is not in progress, the leader unit will reset the partition to 0.
        if kubernetes_upgrade.partition.get(app_name=self.app.name) < unit_number:
            kubernetes_upgrade.partition.set(app_name=self.app.name, value=unit_number)
            logger.debug(f"Partition set to {unit_number} during stop event")
        if not self._upgrade:
            logger.debug("Peer relation missing during stop event")
            return
        self._upgrade.unit_state = "restarting"


if __name__ == "__main__":
    ops.main.main(KubernetesRouterCharm)
