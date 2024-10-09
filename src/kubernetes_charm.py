#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL Router Kubernetes charm"""

import logging
import socket
import typing

import charm_refresh
import lightkube
import lightkube.models.core_v1
import lightkube.models.meta_v1
import lightkube.resources.core_v1
import ops
import tenacity
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm

import abstract_charm
import kubernetes_logrotate
import logrotate
import relations.cos
import relations.database_provides
import relations.database_requires
import rock
import workload

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class RouterRefresh(charm_refresh.CharmSpecific):
    @staticmethod
    def run_pre_refresh_checks_after_1_unit_refreshed() -> None:
        pass

    @classmethod
    def is_compatible(
        cls,
        *,
        old_charm_version: charm_refresh.CharmVersion,
        new_charm_version: charm_refresh.CharmVersion,
        old_workload_version: str,
        new_workload_version: str,
    ) -> bool:
        if not super().is_compatible(
            old_charm_version=old_charm_version,
            new_charm_version=new_charm_version,
            old_workload_version=old_workload_version,
            new_workload_version=new_workload_version,
        ):
            return False
        # TODO: check workload version
        return True


@trace_charm(
    tracing_endpoint="tracing_endpoint",
    extra_types=(
        logrotate.LogRotate,
        relations.cos.COSRelation,
        relations.database_provides.RelationEndpoint,
        relations.database_requires.RelationEndpoint,
        relations.tls.RelationEndpoint,
        rock.Rock,
        workload.AuthenticatedWorkload,
        workload.Workload,
    ),
)
class KubernetesRouterCharm(abstract_charm.MySQLRouterCharm):
    """MySQL Router Kubernetes charm"""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._namespace = self.model.name

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(
            self.on[rock.CONTAINER_NAME].pebble_ready, self._on_workload_container_pebble_ready
        )
        try:
            self.refresh = charm_refresh.Refresh(
                RouterRefresh(
                    cloud=charm_refresh.Cloud.KUBERNETES,
                    workload_name="Router",
                    refresh_user_docs_url="https://example.com",
                    oci_resource_name="mysql-router-image",
                )
            )
        except charm_refresh.PeerRelationMissing:
            self.unit.status = ops.MaintenanceStatus("Waiting for peer relation")
            if self.unit.is_leader():
                self.app.status = ops.MaintenanceStatus("Waiting for peer relation")
            exit()

    @property
    def _subordinate_relation_endpoint_names(self) -> typing.Optional[typing.Iterable[str]]:
        return

    @property
    def _container(self) -> rock.Rock:
        return rock.Rock(unit=self.unit)

    @property
    def _logrotate(self) -> logrotate.LogRotate:
        return kubernetes_logrotate.LogRotate(container_=self._container)

    def is_externally_accessible(self, *, event) -> typing.Optional[bool]:
        """No-op since this charm is exposed with node-port"""

    def _reconcile_node_port(self, *, event) -> None:
        self._patch_service(event)

    def _reconcile_ports(self, *, event) -> None:
        """Needed for VM, so no-op"""

    def wait_until_mysql_router_ready(self, *, event=None) -> None:
        logger.debug("Waiting until MySQL Router is ready")
        self.unit.status = ops.MaintenanceStatus("MySQL Router starting")
        try:
            for attempt in tenacity.Retrying(
                reraise=True,
                stop=tenacity.stop_after_delay(30),
                wait=tenacity.wait_fixed(5),
            ):
                with attempt:
                    for port in (
                        self._READ_WRITE_PORT,
                        self._READ_ONLY_PORT,
                        self._READ_WRITE_X_PORT,
                        self._READ_ONLY_X_PORT,
                    ):
                        with socket.socket() as s:
                            assert s.connect_ex(("localhost", port)) == 0
        except AssertionError:
            logger.exception("Unable to connect to MySQL Router")
            raise
        else:
            logger.debug("MySQL Router is ready")

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
        return f"{self._node_ip}:{self._node_port('rw')}"

    @property
    def _exposed_read_only_endpoint(self) -> str:
        return f"{self._node_ip}:{self._node_port('ro')}"

    def _patch_service(self, event=None) -> None:
        """Patch Juju-created k8s service.

        The k8s service will be tied to pod-0 so that the service is auto cleaned by
        k8s when the last pod is scaled down.
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
                type=(
                    "NodePort"
                    if self._database_provides.external_connectivity(event)
                    else "ClusterIP"
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

    @property
    def _node_name(self) -> str:
        """Return the node name for this unit's pod ip."""
        pod = lightkube.Client().get(
            lightkube.resources.core_v1.Pod,
            name=self.unit.name.replace("/", "-"),
            namespace=self._namespace,
        )
        return pod.spec.nodeName

    def get_all_k8s_node_hostnames_and_ips(
        self,
    ) -> typing.Tuple[typing.List[str], typing.List[str]]:
        """Return all node hostnames and IPs registered in k8s."""
        node = lightkube.Client().get(
            lightkube.resources.core_v1.Node,
            name=self._node_name,
            namespace=self._namespace,
        )
        hostnames = []
        ips = []
        for a in node.status.addresses:
            if a.type in ["ExternalIP", "InternalIP"]:
                ips.append(a.address)
            elif a.type == "Hostname":
                hostnames.append(a.address)
        return hostnames, ips

    @property
    def _node_ip(self) -> typing.Optional[str]:
        """Return node IP."""
        node = lightkube.Client().get(
            lightkube.resources.core_v1.Node,
            name=self._node_name,
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

    def _node_port(self, port_type: str) -> int:
        """Return node port."""
        service = lightkube.Client().get(
            lightkube.resources.core_v1.Service, self.app.name, namespace=self._namespace
        )
        if not service or not service.spec.type == "NodePort":
            return -1
        # svc.spec.ports
        # [ServicePort(port=3306, appProtocol=None, name=None, nodePort=31438, protocol='TCP', targetPort=3306)]
        if port_type == "rw":
            port = self._READ_WRITE_PORT
        elif port_type == "ro":
            port = self._READ_ONLY_PORT
        else:
            raise ValueError(f"Invalid {port_type=}")
        logger.debug(f"Looking for NodePort for {port_type} in {service.spec.ports}")
        for svc_port in service.spec.ports:
            if svc_port.port == port:
                return svc_port.nodePort
        raise Exception(f"NodePort not found for {port_type}")

    # =======================
    #  Handlers
    # =======================

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


if __name__ == "__main__":
    ops.main.main(KubernetesRouterCharm)
