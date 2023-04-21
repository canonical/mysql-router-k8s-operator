#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL Router k8s charm."""

import logging

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops
from lightkube import ApiError, Client
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Pod, Service

import relations.database_provides
import relations.database_requires
import relations.tls
import workload
from constants import (
    DATABASE_PROVIDES_RELATION,
    DATABASE_REQUIRES_RELATION,
    MYSQL_ROUTER_CONTAINER_NAME,
)

logger = logging.getLogger(__name__)


class MySQLRouterOperatorCharm(ops.CharmBase):
    """Operator charm for MySQL Router."""

    def __init__(self, *args) -> None:
        super().__init__(*args)

        self.database_requires = relations.database_requires.RelationEndpoint(
            data_interfaces.DatabaseRequires(
                self,
                relation_name=DATABASE_REQUIRES_RELATION,
                # HACK: mysqlrouter needs a user, but not a database
                # Use the DatabaseRequires interface to get a user; disregard the database
                database_name="continuous_writes_database",
                extra_user_roles="mysqlrouter",
            )
        )
        self.framework.observe(
            self.database_requires.interface.on.database_created,
            self._reconcile_database_relations,
        )
        self.framework.observe(
            self.on[DATABASE_REQUIRES_RELATION].relation_broken,
            self._reconcile_database_relations,
        )

        self.database_provides = relations.database_provides.RelationEndpoint(
            data_interfaces.DatabaseProvides(self, relation_name=DATABASE_PROVIDES_RELATION)
        )
        self.framework.observe(
            self.database_provides.interface.on.database_requested,
            self._reconcile_database_relations,
        )
        self.framework.observe(
            self.on[DATABASE_PROVIDES_RELATION].relation_broken, self._reconcile_database_relations
        )

        self.framework.observe(
            getattr(self.on, "mysql_router_pebble_ready"), self._on_mysql_router_pebble_ready
        )
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)

        self.workload = workload.Workload(self.unit.get_container(MYSQL_ROUTER_CONTAINER_NAME))

        self.tls = relations.tls.MySQLRouterTLS(self)

    @property
    def _endpoint(self) -> str:
        """The k8s endpoint for the charm."""
        return f"{self.model.app.name}.{self.model.name}.svc.cluster.local"

    def _determine_status(self) -> ops.StatusBase:
        missing_relations = []
        for relation, missing in [
            (DATABASE_REQUIRES_RELATION, self.database_requires.relation is None),
            (DATABASE_PROVIDES_RELATION, self.database_provides.missing_relation),
        ]:
            if missing:
                missing_relations.append(relation)
        if missing_relations:
            return ops.BlockedStatus(
                f"Missing relation{'s' if len(missing_relations) > 1 else ''}: {', '.join(missing_relations)}"
            )
        if not self.workload.container_ready:
            return ops.MaintenanceStatus("Waiting for container")  # TODO
        return ops.ActiveStatus()

    def _set_status(self) -> None:
        if isinstance(
            self.unit.status, ops.BlockedStatus
        ) and not self.unit.status.message.startswith("Missing relation"):
            return
        self.unit.status = self._determine_status()

    def _patch_service(self, name: str, ro_port: int, rw_port: int) -> None:
        """Patch juju created k8s service.
        The k8s service will be tied to pod-0 so that the service is auto cleaned by
        k8s when the last pod is scaled down.
        Args:
            name: The name of the service.
            ro_port: The read only port.
            rw_port: The read write port.
        """
        client = Client()
        pod0 = client.get(
            res=Pod,
            name=self.app.name + "-0",
            namespace=self.model.name,
        )
        service = Service(
            metadata=ObjectMeta(
                name=name,
                namespace=self.model.name,
                ownerReferences=pod0.metadata.ownerReferences,
                labels={
                    "app.kubernetes.io/name": self.app.name,
                },
            ),
            spec=ServiceSpec(
                ports=[
                    ServicePort(
                        name="mysql-ro",
                        port=ro_port,
                        targetPort=ro_port,
                    ),
                    ServicePort(
                        name="mysql-rw",
                        port=rw_port,
                        targetPort=rw_port,
                    ),
                ],
                selector={"app.kubernetes.io/name": self.app.name},
            ),
        )
        client.patch(
            res=Service,
            obj=service,
            name=service.metadata.name,
            namespace=service.metadata.namespace,
            force=True,
            field_manager=self.model.app.name,
        )

    # =======================
    #  Handlers
    # =======================

    def _reconcile_database_relations(self, event=None) -> None:
        """Handle database requires/provides events."""
        if (
            self.unit.is_leader()
            and self.database_requires.relation
            and self.workload.container_ready
        ):
            self.database_provides.reconcile_users(
                event,
                self.database_requires.relation.is_breaking(event),
                self._endpoint,
                self.database_requires.relation,
            )
        if (
            self.database_requires.relation
            and not self.database_requires.relation.is_breaking(event)
            and self.workload.container_ready
        ):
            self.workload.start(
                self.database_requires.relation.host,
                self.database_requires.relation.port,
                self.database_requires.relation.username,
                self.database_requires.relation.password,
            )
        else:
            self.workload.stop()
        self._set_status()

    def _on_mysql_router_pebble_ready(self, _) -> None:
        self.unit.set_workload_version(self.workload.version)
        self._reconcile_database_relations()

    def _on_start(self, _) -> None:
        # If no relations are active, charm status has not been set
        self._set_status()

    def _on_leader_elected(self, _) -> None:
        """Patch existing k8s service to include read-write and read-only services."""
        try:
            self._patch_service(self.app.name, ro_port=6447, rw_port=6446)
        except ApiError:
            logger.exception("Failed to patch k8s service")
            self.unit.status = ops.BlockedStatus("Failed to patch k8s service")


if __name__ == "__main__":
    ops.main.main(MySQLRouterOperatorCharm)
