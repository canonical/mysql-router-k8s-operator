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
import tenacity
from charms.tempo_k8s.v1.charm_tracing import trace_charm

import abstract_charm
import kubernetes_logrotate
import kubernetes_upgrade
import logrotate
import relations.cos
import relations.database_provides
import relations.database_requires
import rock
import upgrade
import workload

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@trace_charm(
    tracing_endpoint="tracing_endpoint",
    extra_types=(
        kubernetes_upgrade.Upgrade,
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

        self._service_name = f"{self.app.name}-service"
        self._lightkube_client = lightkube.Client()

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self.reconcile)
        self.framework.observe(
            self.on[rock.CONTAINER_NAME].pebble_ready, self._on_workload_container_pebble_ready
        )
        self.framework.observe(self.on.stop, self._on_stop)

    @property
    def _subordinate_relation_endpoint_names(self) -> typing.Optional[typing.Iterable[str]]:
        return

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

    def is_externally_accessible(self, *, event) -> typing.Optional[bool]:
        """No-op since this charm is exposed with node-port"""

    def _get_current_service_type(self) -> typing.Optional[str]:
        """Get the current service type."""
        try:
            service = self._lightkube_client.get(
                res=lightkube.resources.core_v1.Service,
                name=self._service_name,
                namespace=self.model.name,
            )
        except lightkube.core.exceptions.ApiError as e:
            if e.status.code == 404:
                return None
            raise

        return service.spec.type

    def _apply_service(self, service_type: str) -> None:
        """Apply the service type provided."""
        pod0 = self._lightkube_client.get(
            res=lightkube.resources.core_v1.Pod,
            name=self.app.name + "-0",
            namespace=self.model.name,
        )

        service = lightkube.resources.core_v1.Service(
            metadata=lightkube.models.meta_v1.ObjectMeta(
                name=self._service_name,
                namespace=self.model.name,
                ownerReferences=pod0.metadata.ownerReferences,  # the stateful set
                labels={"app.kubernetes.io/name": self.app.name},
            ),
            spec=lightkube.models.core_v1.ServiceSpec(
                ports=[
                    lightkube.models.core_v1.ServicePort(
                        name="mysql-rw",
                        port=self._READ_WRITE_PORT,
                        targetPort=self._READ_WRITE_PORT,
                    ),
                    lightkube.models.core_v1.ServicePort(
                        name="mysql-ro",
                        port=self._READ_ONLY_PORT,
                        targetPort=self._READ_ONLY_PORT,
                    ),
                ],
                type=service_type,
                selector={"app.kubernetes.io/name": self.app.name},
            ),
        )

        try:
            logger.info(f"Applying service {service_type=}")
            self._lightkube_client.apply(service, field_manager=self.app.name)
            logger.info(f"Applied service {service_type=}")
        except lightkube.core.exceptions.ApiError as e:
            if e.status.code == 403:
                # TODO: send charm into a blocked status
                logger.error("Could not create service, application needs `juju trust`")
            raise

    def _reconcile_services(self) -> None:
        expose_external = self.config.get("expose-external", "false")
        if expose_external not in ["false", "nodeport", "loadbalancer"]:
            logger.warning(f"Invalid config value {expose_external=}")
            return

        expose_external_to_service_type = {
            "false": "ClusterIP",
            "nodeport": "NodePort",
            "loadbalancer": "LoadBalancer",
        }

        current_service_type = self._get_current_service_type()
        if (
            not current_service_type
            or current_service_type != expose_external_to_service_type[expose_external]
        ):
            self._apply_service(expose_external_to_service_type[expose_external])

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

    def _get_host_port(self, port_type: str) -> str:
        """Gets the host and port for the endpoint depending of type of service."""
        if port_type not in ["rw", "ro"]:
            return ""

        current_service_type = self._get_current_service_type()
        if current_service_type == "ClusterIP":
            port = self._READ_WRITE_PORT if port_type == "rw" else self._READ_ONLY_PORT
            return f"{self._host}:{port}"

        service = self._lightkube_client.get(
            lightkube.resources.core_v1.Service,
            name=self._service_name,
            namespace=self.model.name,
        )

        port = None
        for p in service.spec.ports:
            if p.name == f"mysql-{port_type}":
                port = p.port

        if not port:
            return ""

        if current_service_type == "NodePort":
            return f"{service.spec.clusterIP}:{port}"
        elif current_service_type == "LoadBalancer" and service.status.loadBalancer.ingress:
            return f"{service.status.loadBalancer.ingress[0].ip}:{port}"

        return ""

    @property
    def _read_write_endpoint(self) -> str:
        return self._get_host_port("rw")

    @property
    def _read_only_endpoint(self) -> str:
        return self._get_host_port("ro")

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

        self._apply_service("ClusterIP")

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
        self._upgrade.unit_state = upgrade.UnitState.RESTARTING


if __name__ == "__main__":
    ops.main.main(KubernetesRouterCharm)
