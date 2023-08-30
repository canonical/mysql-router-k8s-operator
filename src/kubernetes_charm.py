#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL Router Kubernetes charm"""
from yaml import CSafeLoader
import logging
import socket
import typing

import lightkube
import lightkube.models.core_v1
import lightkube.models.meta_v1
import lightkube.resources.core_v1
import ops

import abstract_charm
import relations.tls
import rock

logger = logging.getLogger(__name__)


class KubernetesRouterCharm(abstract_charm.MySQLRouterCharm):
    """MySQL Router Kubernetes charm"""

    _READ_WRITE_PORT = 6446
    _READ_ONLY_PORT = 6447

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(
            self.on[rock.CONTAINER_NAME].pebble_ready, self._on_workload_container_pebble_ready
        )
        # TODO VM TLS: Move to super class
        self.tls = relations.tls.RelationEndpoint(self)

    @property
    def _subordinate_relation_endpoint_names(self) -> typing.Optional[typing.Iterable[str]]:
        return

    @property
    def tls_certificate_saved(self) -> bool:
        return self.tls.certificate_saved

    @property
    def _container(self) -> rock.Rock:
        return rock.Rock(unit=self.unit)

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

    def _patch_service(self) -> None:
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
                        targetPort=self._READ_WRITE_PORT,
                    ),
                    lightkube.models.core_v1.ServicePort(
                        name="mysql-ro",
                        port=self._READ_ONLY_PORT,
                        targetPort=self._READ_ONLY_PORT,
                    ),
                ],
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

    # =======================
    #  Handlers
    # =======================

    def _on_install(self, _) -> None:
        """Patch existing k8s service to include read-write and read-only services."""
        if not self.unit.is_leader():
            return
        try:
            self._patch_service()
        except lightkube.ApiError:
            logger.exception("Failed to patch k8s service")
            raise

    def _on_workload_container_pebble_ready(self, _) -> None:
        self.unit.set_workload_version(self.get_workload(event=None).version)
        self.reconcile_database_relations()


if __name__ == "__main__":
    ops.main.main(KubernetesRouterCharm)
