#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL-Router k8s charm."""

import json
import logging
from typing import Optional, Set

from lightkube import ApiError, Client
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Pod, Service
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, WaitingStatus
from ops.pebble import Layer

from constants import (
    DATABASE_PROVIDES_RELATION,
    DATABASE_REQUIRES_RELATION,
    MYSQL_DATABASE_CREATED,
    MYSQL_ROUTER_CONTAINER_NAME,
    MYSQL_ROUTER_REQUIRES_DATA,
    MYSQL_ROUTER_SERVICE_NAME,
    NUM_UNITS_BOOTSTRAPPED,
    PEER,
    UNIT_BOOTSTRAPPED,
)
from mysql_router_helpers import MySQLRouter
from relations.database_provides import DatabaseProvidesRelation
from relations.database_requires import DatabaseRequiresRelation
from relations.tls import MySQLRouterTLS

logger = logging.getLogger(__name__)


class MySQLRouterOperatorCharm(CharmBase):
    """Operator charm for MySQLRouter."""

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(
            getattr(self.on, "mysql_router_pebble_ready"), self._on_mysql_router_pebble_ready
        )
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)

        self.database_provides = DatabaseProvidesRelation(self)
        self.database_requires = DatabaseRequiresRelation(self)
        self.tls = MySQLRouterTLS(self)

    # =======================
    #  Properties
    # =======================

    @property
    def peers(self) -> Optional[Relation]:
        """Fetch the peer relation."""
        return self.model.get_relation(PEER)

    @property
    def app_peer_data(self):
        """Application peer data object."""
        if not self.peers:
            return {}

        return self.peers.data[self.app]

    @property
    def unit_peer_data(self):
        """Unit peer data object."""
        if not self.peers:
            return {}

        return self.peers.data[self.unit]

    @property
    def read_write_endpoint(self):
        """The read write k8s endpoint for the charm."""
        return f"{self.model.app.name}-read-write.{self.model.name}.svc.cluster.local"

    @property
    def read_only_endpoint(self):
        """The read only k8s endpoint for the charm."""
        return f"{self.model.app.name}-read-only.{self.model.name}.svc.cluster.local"

    @property
    def unit_hostname(self) -> str:
        """Get the hostname.localdomain for a unit.

        Translate juju unit name to hostname.localdomain, necessary
        for correct name resolution under k8s.

        Returns:
            A string representing the hostname.localdomain of the unit.
        """
        return f"{self.unit.name.replace('/', '-')}.{self.app.name}-endpoints"

    # =======================
    #  Helpers
    # =======================

    def _create_service(self, name: str, port: int) -> None:
        """Create a k8s service that is tied to pod-0.

        The k8s service is tied to pod-0 so that the service is auto cleaned by
        k8s when the last pod is scaled down.
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
                        name="mysql",
                        port=port,
                        targetPort=port,
                    )
                ],
                selector={"app.kubernetes.io/name": self.app.name},
            ),
        )
        client.apply(
            obj=service,
            name=service.metadata.name,
            namespace=service.metadata.namespace,
            force=True,
            field_manager=self.model.app.name,
        )

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get secret from the peer relation databag."""
        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope")

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
        """Set secret in the peer relation databag."""
        if scope == "unit":
            if not value:
                del self.unit_peer_data[key]
                return
            self.unit_peer_data.update({key: value})
        elif scope == "app":
            if not value:
                del self.app_peer_data[key]
                return
            self.app_peer_data.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope")

    @property
    def mysql_router_layer(self) -> Layer:
        """Return a layer configuration for the mysql router service."""
        requires_data = json.loads(self.app_peer_data[MYSQL_ROUTER_REQUIRES_DATA])
        host, port = requires_data["endpoints"].split(",")[0].split(":")
        return Layer(
            {
                "summary": "mysql router layer",
                "description": "the pebble config layer for mysql router",
                "services": {
                    MYSQL_ROUTER_SERVICE_NAME: {
                        "override": "replace",
                        "summary": "mysql router",
                        "command": "/run.sh mysqlrouter",
                        "startup": "enabled",
                        "environment": {
                            "MYSQL_HOST": host,
                            "MYSQL_PORT": port,
                            "MYSQL_USER": requires_data["username"],
                            "MYSQL_PASSWORD": self.get_secret("app", "database-password") or "",
                        },
                    },
                },
            }
        )

    def _bootstrap_mysqlrouter(self) -> bool:
        if not self.app_peer_data.get(MYSQL_DATABASE_CREATED):
            return False

        pebble_layer = self.mysql_router_layer

        container = self.unit.get_container(MYSQL_ROUTER_CONTAINER_NAME)
        plan = container.get_plan()

        if plan.services != pebble_layer.services:
            container.add_layer(MYSQL_ROUTER_SERVICE_NAME, pebble_layer, combine=True)
            container.start(MYSQL_ROUTER_SERVICE_NAME)

            MySQLRouter.wait_until_mysql_router_ready()

            self.unit_peer_data[UNIT_BOOTSTRAPPED] = "true"

            return True

        return False

    @property
    def missing_relations(self) -> Set[str]:
        """Return a set of missing relations."""
        missing_relations = set()
        for relation_name in [DATABASE_REQUIRES_RELATION, DATABASE_PROVIDES_RELATION]:
            if not self.model.get_relation(relation_name):
                missing_relations.add(relation_name)
        return missing_relations

    # =======================
    #  Handlers
    # =======================

    def _on_install(self, _) -> None:
        """Handle the install event."""
        self.unit.status = WaitingStatus()
        # Try set workload version
        container = self.unit.get_container(MYSQL_ROUTER_CONTAINER_NAME)
        if container.can_connect():
            if version := MySQLRouter.get_version(container):
                self.unit.set_workload_version(version)

    def _on_leader_elected(self, _) -> None:
        """Handle the leader elected event.

        Creates read-write and read-only services from a template file, and deletes
        the service created by juju for the application.
        """
        # Create the read-write and read-only services
        try:
            self._create_service(f"{self.app.name}-read-only", 6447)
            self._create_service(f"{self.app.name}-read-write", 6446)
        except ApiError as e:
            logger.exception("Failed to create k8s service", exc_info=e)
            self.unit.status = BlockedStatus("Failed to create k8s service")
            return

    def _on_mysql_router_pebble_ready(self, _) -> None:
        """Handle the mysql-router pebble ready event."""
        if self._bootstrap_mysqlrouter():
            self.unit.status = ActiveStatus()

    def _on_peer_relation_changed(self, _) -> None:
        """Handle the peer relation changed event.

        Bootstraps mysqlrouter if the relations exist, but pebble_ready event
        fired before the requires relation was formed.
        """
        if (
            isinstance(self.unit.status, WaitingStatus)
            and self.app_peer_data.get(MYSQL_DATABASE_CREATED)
            and self._bootstrap_mysqlrouter()
        ):
            self.unit.status = ActiveStatus()

        if self.unit.is_leader():
            num_units_bootstrapped = sum(
                1
                for _ in self.peers.units.union({self.unit})
                if self.unit_peer_data.get(UNIT_BOOTSTRAPPED)
            )
            self.app_peer_data[NUM_UNITS_BOOTSTRAPPED] = str(num_units_bootstrapped)

    def _on_update_status(self, _) -> None:
        """Handle update-status event."""
        if self.missing_relations:
            self.unit.status = WaitingStatus(
                f"Waiting for relations: {' '.join(self.missing_relations)}"
            )
            return
        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(MySQLRouterOperatorCharm)
