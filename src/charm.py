#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL Router Kubernetes charm"""

import ops

from architecture import WrongArchitectureWarningCharm, is_wrong_architecture

if is_wrong_architecture() and __name__ == "__main__":
    ops.main.main(WrongArchitectureWarningCharm)

import dataclasses
import enum
import functools
import json
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
import relations.secrets
import rock
import workload

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class _ServiceType(enum.Enum):
    """Supported K8s service types"""

    CLUSTER_IP = "ClusterIP"
    NODE_PORT = "NodePort"
    LOAD_BALANCER = "LoadBalancer"


@dataclasses.dataclass(eq=False)
class KubernetesRouterRefresh(abstract_charm.RouterRefresh, charm_refresh.CharmSpecificKubernetes):
    """MySQL Router Kubernetes refresh callbacks & configuration"""


@trace_charm(
    tracing_endpoint="tracing_endpoint",
    extra_types=(
        logrotate.LogRotate,
        relations.cos.COSRelation,
        relations.database_provides.RelationEndpoint,
        relations.database_requires.RelationEndpoint,
        relations.tls.RelationEndpoint,
        rock.Rock,
        workload.RunningWorkload,
        workload.Workload,
    ),
)
class KubernetesRouterCharm(abstract_charm.MySQLRouterCharm):
    """MySQL Router Kubernetes charm"""

    _PEER_RELATION_NAME = "mysql-router-peers"

    _K8S_SERVICE_CONNECTION_TIMEOUT = 3
    _K8S_SERVICE_INITIALIZED_KEY = "k8s-service-initialized"
    _K8S_SERVICE_CREATING_KEY = "k8s-service-creating"

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._namespace = self.model.name

        self.service_name = f"{self.app.name}-service"
        self._lightkube_client = lightkube.Client()

        self._peer_data = relations.secrets.RelationSecrets(self, self._PEER_RELATION_NAME)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(
            self.on[rock.CONTAINER_NAME].pebble_ready, self._on_workload_container_pebble_ready
        )
        try:
            self.refresh = charm_refresh.Kubernetes(
                KubernetesRouterRefresh(
                    workload_name="Router",
                    refresh_user_docs_url="https://charmhub.io/mysql-router-k8s/docs/h-upgrade",
                    oci_resource_name="mysql-router-image",
                )
            )
        except charm_refresh.UnitTearingDown:
            # MySQL server charm will clean up users & router metadata when the MySQL Router app or
            # unit(s) tear down
            self.unit.status = ops.MaintenanceStatus("Tearing down")
            exit()
        except charm_refresh.KubernetesJujuAppNotTrusted:
            exit()
        except charm_refresh.PeerRelationNotReady:
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

    @property
    def _status(self) -> ops.StatusBase:
        if self.config.get("expose-external", "false") not in [
            "false",
            "nodeport",
            "loadbalancer",
        ]:
            return ops.BlockedStatus("Invalid expose-external config value")
        if (
            self._peer_data.get_value(
                relations.secrets.APP_SCOPE, self._K8S_SERVICE_INITIALIZED_KEY
            )
            and not self._check_service_connectivity()
        ):
            if self._peer_data.get_value(
                relations.secrets.APP_SCOPE, self._K8S_SERVICE_CREATING_KEY
            ):
                return ops.MaintenanceStatus("Waiting for K8s service connectivity")
            else:
                return ops.BlockedStatus("K8s service not connectable")

    def is_externally_accessible(self, *, event) -> typing.Optional[bool]:
        """No-op since this charm is exposed with the expose-external config."""

    def _get_service(self) -> typing.Optional[lightkube.resources.core_v1.Service]:
        """Get the managed k8s service."""
        try:
            service = self._lightkube_client.get(
                res=lightkube.resources.core_v1.Service,
                name=self.service_name,
                namespace=self.model.name,
            )
        except lightkube.core.exceptions.ApiError as e:
            if e.status.code == 404:
                return None
            raise

        return service

    @functools.cache
    def _get_pod(self, unit_name: str) -> lightkube.resources.core_v1.Pod:
        """Get the pod for the provided unit name."""
        return self._lightkube_client.get(
            res=lightkube.resources.core_v1.Pod,
            name=unit_name.replace("/", "-"),
            namespace=self.model.name,
        )

    @functools.cache
    def _get_node(self, unit_name: str) -> lightkube.resources.core_v1.Node:
        """Return the node for the provided unit name."""
        node_name = self._get_pod(unit_name).spec.nodeName
        return self._lightkube_client.get(
            res=lightkube.resources.core_v1.Node,
            name=node_name,
            namespace=self.model.name,
        )

    def _reconcile_service(self) -> None:
        expose_external = self.config.get("expose-external", "false")
        if expose_external not in ["false", "nodeport", "loadbalancer"]:
            logger.warning(f"Invalid config value {expose_external=}")
            return

        desired_service_type = {
            "false": _ServiceType.CLUSTER_IP,
            "nodeport": _ServiceType.NODE_PORT,
            "loadbalancer": _ServiceType.LOAD_BALANCER,
        }[expose_external]

        service = self._get_service()
        service_exists = service is not None
        service_type = service_exists and _ServiceType(service.spec.type)
        if service_exists and service_type == desired_service_type:
            return

        pod0 = self._get_pod(f"{self.app.name}/0")

        annotations = (
            json.loads(self.config.get("loadbalancer-extra-annotations", "{}"))
            if desired_service_type == _ServiceType.LOAD_BALANCER
            else {}
        )

        desired_service = lightkube.resources.core_v1.Service(
            metadata=lightkube.models.meta_v1.ObjectMeta(
                name=self.service_name,
                namespace=self.model.name,
                ownerReferences=pod0.metadata.ownerReferences,  # the stateful set
                labels={"app.kubernetes.io/name": self.app.name},
                annotations=annotations,
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
                type=desired_service_type.value,
                selector={"app.kubernetes.io/name": self.app.name},
            ),
        )

        logger.info(f"Creating desired service {desired_service_type=}")
        self._lightkube_client.apply(desired_service, field_manager=self.app.name)

        self._peer_data.set_value(
            relations.secrets.APP_SCOPE, self._K8S_SERVICE_CREATING_KEY, "true"
        )
        self._peer_data.set_value(
            relations.secrets.APP_SCOPE, self._K8S_SERVICE_INITIALIZED_KEY, "true"
        )

        logger.info(f"Request to create desired service {desired_service_type=} dispatched")

    def _check_service_connectivity(self) -> bool:
        """Check if the service is available (connectable with a socket)."""
        if not self._get_service() or not isinstance(
            self.get_workload(event=None), workload.RunningWorkload
        ):
            logger.debug("No service or unauthenticated workload")
            return False

        for endpoints in (
            self._read_write_endpoints,
            self._read_only_endpoints,
        ):
            if endpoints == "":
                logger.debug(
                    f"Empty endpoints {self._read_write_endpoints=} {self._read_only_endpoints=}"
                )
                return False

            for endpoint in endpoints.split(","):
                with socket.socket() as s:
                    s.settimeout(self._K8S_SERVICE_CONNECTION_TIMEOUT)

                    host, port = endpoint.split(":")

                    try:
                        socket_connect_code = s.connect_ex((host, int(port)))
                    except socket.gaierror:
                        # Sometimes, it may take LB hostname record to propagate
                        logger.info(f"Unable to resolve {endpoint=}")
                        return False

                    if socket_connect_code != 0:
                        logger.info(f"Unable to connect to {endpoint=}")
                        return False

        return True

    def _reconcile_ports(self, *, event) -> None:
        """Needed for VM, so no-op"""

    def _update_endpoints(self) -> None:
        if self._check_service_connectivity():
            self._database_provides.update_endpoints(
                router_read_write_endpoints=self._read_write_endpoints,
                router_read_only_endpoints=self._read_only_endpoints,
            )

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
        # Example: mysql-router-k8s-service.my-model.svc.cluster.local
        return f"{self.service_name}.{self.model_service_domain}"

    def _get_node_hosts(self) -> set[str]:
        """Return the node ports of nodes where units of this app are scheduled."""
        peer_relation = self.model.get_relation(self._PEER_RELATION_NAME)
        if not peer_relation:
            return set()

        def _get_node_address(node) -> str:
            # OpenStack will return an internal hostname, not externally accessible
            # Preference: ExternalIP > InternalIP > Hostname
            for typ in ["ExternalIP", "InternalIP", "Hostname"]:
                for address in node.status.addresses:
                    if address.type == typ:
                        return address.address

        hosts = set()
        for unit in peer_relation.units | {self.model.unit}:
            node = self._get_node(unit.name)
            hosts.add(_get_node_address(node))
        return hosts

    def _get_hosts_ports(self, port_type: str) -> str:  # noqa: C901
        """Gets the host and port for the endpoint depending of type of service."""
        if port_type not in ["rw", "ro"]:
            raise ValueError("Invalid port type")

        service = self._get_service()
        if not service:
            return ""

        port = self._READ_WRITE_PORT if port_type == "rw" else self._READ_ONLY_PORT

        service_type = _ServiceType(service.spec.type)

        if service_type == _ServiceType.CLUSTER_IP:
            return f"{self._host}:{port}"
        elif service_type == _ServiceType.NODE_PORT:
            hosts = self._get_node_hosts()

            for p in service.spec.ports:
                if p.name == f"mysql-{port_type}":
                    node_port = p.nodePort

            return ",".join(sorted({f"{host}:{node_port}" for host in hosts}))
        elif service_type == _ServiceType.LOAD_BALANCER and service.status.loadBalancer.ingress:
            if len(service.status.loadBalancer.ingress) != 0:
                ip = service.status.loadBalancer.ingress[0].ip
                hostname = service.status.loadBalancer.ingress[0].hostname

            if ip:
                return f"{ip}:{port}"

            if hostname:
                return f"{hostname}:{port}"

        return ""

    @property
    def _read_write_endpoints(self) -> str:
        return self._get_hosts_ports("rw")

    @property
    def _read_only_endpoints(self) -> str:
        return self._get_hosts_ports("ro")

    @property
    def _exposed_read_write_endpoints(self) -> typing.Optional[str]:
        """Only applies to VM charm, so no-op."""
        pass

    @property
    def _exposed_read_only_endpoints(self) -> typing.Optional[str]:
        """Only applies to VM charm, so no-op."""
        pass

    def get_all_k8s_node_hostnames_and_ips(
        self,
    ) -> typing.Tuple[typing.List[str], typing.List[str]]:
        """Return all node hostnames and IPs registered in k8s."""
        node = self._get_node(self.unit.name)
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
        # TODO fix this if fails because app not trusted and user runs `juju trust`
        if ops.JujuVersion.from_environ().supports_open_port_on_k8s:
            for port in (self._READ_WRITE_PORT, self._READ_ONLY_PORT, 6448, 6449):
                self.unit.open_port("tcp", port)

    def _on_workload_container_pebble_ready(self, _) -> None:
        self.unit.set_workload_version(self.get_workload(event=None).version)


if __name__ == "__main__":
    ops.main.main(KubernetesRouterCharm)
