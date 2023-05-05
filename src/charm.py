#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL Router kubernetes (k8s) charm"""

import logging
import socket

import lightkube
import lightkube.models.core_v1
import lightkube.models.meta_v1
import lightkube.resources.core_v1
import ops
import tenacity

import relations.database_provides
import relations.database_requires
import relations.tls
import workload

logger = logging.getLogger(__name__)


class MySQLRouterOperatorCharm(ops.CharmBase):
    """Operator charm for MySQL Router"""

    def __init__(self, *args) -> None:
        super().__init__(*args)

        self.database_requires = relations.database_requires.RelationEndpoint(self)

        self.database_provides = relations.database_provides.RelationEndpoint(self)

        self.framework.observe(
            getattr(self.on, "mysql_router_pebble_ready"), self._on_mysql_router_pebble_ready
        )

        # Start workload after pod churn or charm upgrade
        # (https://juju.is/docs/sdk/start-event#heading--emission-sequence)
        # Also, set status on first start if no relations active
        self.framework.observe(self.on.start, self.reconcile_database_relations)

        self.framework.observe(self.on.leader_elected, self._on_leader_elected)

        self.tls = relations.tls.RelationEndpoint(self)

    @property
    def workload(self):
        """MySQL Router workload"""
        # Defined as a property instead of an attribute in __init__ since this class is
        # not re-instantiated between events (if there are deferred events)
        container = self.unit.get_container(workload.Workload.CONTAINER_NAME)
        if self.database_requires.relation:
            return workload.AuthenticatedWorkload(
                _container=container,
                _admin_username=self.database_requires.relation.username,
                _admin_password=self.database_requires.relation.password,
                _host=self.database_requires.relation.host,
                _port=self.database_requires.relation.port,
                _charm=self,
            )
        return workload.Workload(_container=container)

    @property
    def _endpoint(self) -> str:
        """K8s endpoint for MySQL Router"""
        return f"{self.model.app.name}.{self.model.name}.svc.cluster.local"

    def _determine_status(self) -> ops.StatusBase:
        """Report charm status."""
        missing_relations = []
        for relation in [self.database_requires, self.database_provides]:
            if relation.missing_relation:
                missing_relations.append(relation.NAME)
        if missing_relations:
            return ops.BlockedStatus(
                f"Missing relation{'s' if len(missing_relations) > 1 else ''}: {', '.join(missing_relations)}"
            )
        if not self.workload.container_ready:
            return ops.MaintenanceStatus("Waiting for container")
        return ops.ActiveStatus()

    def _set_status(self) -> None:
        """Set charm status.

        Except if charm is in unrecognized state
        """
        if isinstance(
            self.unit.status, ops.BlockedStatus
        ) and not self.unit.status.message.startswith("Missing relation"):
            return
        self.unit.status = self._determine_status()
        logger.debug(f"Set status to {self.unit.status}")

    def wait_until_mysql_router_ready(self) -> None:
        """Wait until a connection to MySQL Router is possible.

        Retry every 5 seconds for up to 30 seconds.
        """
        logger.debug("Waiting until MySQL Router is ready")
        self.unit.status = ops.WaitingStatus("MySQL Router starting")
        try:
            for attempt in tenacity.Retrying(
                reraise=True,
                stop=tenacity.stop_after_delay(30),
                wait=tenacity.wait_fixed(5),
            ):
                with attempt:
                    for port in [6446, 6447]:
                        with socket.socket() as s:
                            assert s.connect_ex(("localhost", port)) == 0
        except AssertionError:
            logger.exception("Unable to connect to MySQL Router")
            raise
        else:
            logger.debug("MySQL Router is ready")
        self._set_status()

    def _patch_service(self, *, name: str, ro_port: int, rw_port: int) -> None:
        """Patch Juju-created k8s service.

        The k8s service will be tied to pod-0 so that the service is auto cleaned by
        k8s when the last pod is scaled down.

        Args:
            name: The name of the service.
            ro_port: The read only port.
            rw_port: The read write port.
        """
        logger.debug(f"Patching k8s service {name=}, {ro_port=}, {rw_port=}")
        client = lightkube.Client()
        pod0 = client.get(
            res=lightkube.resources.core_v1.Pod,
            name=self.app.name + "-0",
            namespace=self.model.name,
        )
        service = lightkube.resources.core_v1.Service(
            metadata=lightkube.models.meta_v1.ObjectMeta(
                name=name,
                namespace=self.model.name,
                ownerReferences=pod0.metadata.ownerReferences,
                labels={
                    "app.kubernetes.io/name": self.app.name,
                },
            ),
            spec=lightkube.models.core_v1.ServiceSpec(
                ports=[
                    lightkube.models.core_v1.ServicePort(
                        name="mysql-ro",
                        port=ro_port,
                        targetPort=ro_port,
                    ),
                    lightkube.models.core_v1.ServicePort(
                        name="mysql-rw",
                        port=rw_port,
                        targetPort=rw_port,
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
            field_manager=self.model.app.name,
        )
        logger.debug(f"Patched k8s service {name=}, {ro_port=}, {rw_port=}")

    # =======================
    #  Handlers
    # =======================

    def reconcile_database_relations(self, event=None) -> None:
        """Handle database requires/provides events."""
        logger.debug(
            "State of reconcile "
            f"{self.unit.is_leader()=}, "
            f"{isinstance(self.workload, workload.AuthenticatedWorkload)=}, "
            f"{self.database_requires.relation and self.database_requires.relation.is_breaking(event)=}, "
            f"{self.workload.container_ready=}"
        )
        if (
            self.unit.is_leader()
            and isinstance(self.workload, workload.AuthenticatedWorkload)
            and self.workload.container_ready
        ):
            self.database_provides.reconcile_users(
                event=event,
                event_is_database_requires_broken=self.database_requires.relation.is_breaking(
                    event
                ),
                router_endpoint=self._endpoint,
                shell=self.workload.shell,
            )
        if (
            isinstance(self.workload, workload.AuthenticatedWorkload)
            and self.workload.container_ready
            and not self.database_requires.relation.is_breaking(event)
        ):
            self.workload.enable(tls=self.tls.certificate_saved)
        else:
            self.workload.disable()
        self._set_status()

    def _on_mysql_router_pebble_ready(self, _) -> None:
        self.unit.set_workload_version(self.workload.version)
        self.reconcile_database_relations()

    def _on_leader_elected(self, _) -> None:
        """Patch existing k8s service to include read-write and read-only services."""
        try:
            self._patch_service(name=self.app.name, ro_port=6447, rw_port=6446)
        except lightkube.ApiError:
            logger.exception("Failed to patch k8s service")
            raise


if __name__ == "__main__":
    ops.main.main(MySQLRouterOperatorCharm)
