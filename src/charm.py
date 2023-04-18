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


class MySQLRouterOperatorCharm(ops.charm.CharmBase):
    """Operator charm for MySQL Router."""

    def __init__(self, *args) -> None:
        super().__init__(*args)

        self.database_requires = relations.database_requires.Relation(
            data_interfaces.DatabaseRequires(
                self,
                relation_name=DATABASE_REQUIRES_RELATION,
                # HACK: mysqlrouter needs a user, but not a database
                # Use the DatabaseRequires interface to get a user; disregard the database
                database_name="_unused_mysqlrouter_database",
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

        self.database_provides = relations.database_provides.Relation(
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

    def _determine_status(self, event) -> ops.model.StatusBase:
        inactive_relations = []
        for relation, active in [
            (DATABASE_REQUIRES_RELATION, self.database_requires.is_desired_active(event)),
            (DATABASE_PROVIDES_RELATION, self.database_provides.is_desired_active(event)),
        ]:
            if not active:
                inactive_relations.append(relation)
        if inactive_relations:
            return ops.model.BlockedStatus(
                f"Missing relation{'s' if len(inactive_relations) > 1 else ''}: {', '.join(inactive_relations)}"
            )
        if not self.workload.container_ready:
            return ops.model.MaintenanceStatus("Waiting for container")  # TODO
        return ops.model.ActiveStatus()

    def _set_status(self, event=None) -> None:
        if isinstance(
            self.unit.status, ops.model.BlockedStatus
        ) and not self.unit.status.message.startswith("Missing relation"):
            return
        self.unit.status = self._determine_status(event)

    def _create_database_and_user(self) -> None:
        if self.database_provides.active:
            # Database and user already created
            return
        password = self.database_provides.generate_password()
        self.database_requires.create_application_database_and_user(
            self.database_provides.username,
            password,
            self.database_provides.database,
        )
        self.database_provides.set_databag(password, self._endpoint)

    def _delete_user(self) -> None:
        if not self.database_provides.active:
            # No user to delete
            return
        self.database_requires.delete_application_user(self.database_provides.username)
        self.database_provides.delete_databag()

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
        if self.database_requires.is_desired_active(event) and self.workload.container_ready:
            self.workload.start(
                self.database_requires.host,
                self.database_requires.port,
                self.database_requires.username,
                self.database_requires.password,
            )
        else:
            self.workload.stop()
        if self.unit.is_leader():
            if self.database_requires.is_desired_active(
                event
            ) and self.database_provides.is_desired_active(event):
                self._create_database_and_user()
            else:
                self._delete_user()
        self._set_status(event)

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
            self.unit.status = ops.model.BlockedStatus("Failed to patch k8s service")


if __name__ == "__main__":
    ops.main.main(MySQLRouterOperatorCharm)
