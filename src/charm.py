#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL-Router k8s charm."""

import json
import logging
from typing import Optional

from lightkube import ApiError, Client
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Pod, Service
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, WaitingStatus
from ops.pebble import Layer

from constants import (
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

logger = logging.getLogger(__name__)


class MySQLRouterOperatorCharm(CharmBase):
    """Operator charm for MySQLRouter."""

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(
            self.on.mysql_router_pebble_ready, self._on_mysql_router_pebble_ready
        )
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)

        self.database_provides = DatabaseProvidesRelation(self)
        self.database_requires = DatabaseRequiresRelation(self)

    # =======================
    #  Properties
    # =======================

    @property
    def _peers(self) -> Optional[Relation]:
        """Fetch the peer relation."""
        return self.model.get_relation(PEER)

    @property
    def app_peer_data(self):
        """Application peer data object."""
        if not self._peers:
            return {}

        return self._peers.data[self.app]

    @property
    def unit_peer_data(self):
        """Unit peer data object."""
        if not self._peers:
            return {}

        return self._peers.data[self.unit]

    @property
    def read_write_endpoint(self):
        """The read write k8s endpoint for the charm."""
        return f"{self.model.app.name}-read-write.{self.model.name}.svc.cluster.local"

    @property
    def read_only_endpoint(self):
        """The read only k8s endpoint for the charm."""
        return f"{self.model.app.name}-read-only.{self.model.name}.svc.cluster.local"

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

    def _get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get secret from the peer relation databag."""
        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope")

    def _set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
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

    @staticmethod
    def _mysql_router_layer(host: str, port: str, username: str, password: str) -> Layer:
        """Return a layer configuration for the mysql router service.

        Args:
            host: The hostname of the MySQL cluster endpoint
            port: The port of the MySQL cluster endpoint
            username: The username for the bootstrap user
            password: The password for the bootstrap user
        """
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
                            "MYSQL_USER": username,
                            "MYSQL_PASSWORD": password,
                        },
                    },
                },
            }
        )

    def _bootstrap_mysqlrouter(self) -> bool:
        if not self.app_peer_data.get(MYSQL_DATABASE_CREATED):
            return False

        requires_data = json.loads(self.app_peer_data[MYSQL_ROUTER_REQUIRES_DATA])

        [endpoint_host, endpoint_port] = requires_data["endpoints"].split(",")[0].split(":")
        pebble_layer = self._mysql_router_layer(
            endpoint_host,
            endpoint_port,
            requires_data["username"],
            self._get_secret("app", "database-password"),
        )

        container = self.unit.get_container(MYSQL_ROUTER_CONTAINER_NAME)
        plan = container.get_plan()

        if plan.services != pebble_layer.services:
            container.add_layer(MYSQL_ROUTER_SERVICE_NAME, pebble_layer, combine=True)
            container.start(MYSQL_ROUTER_SERVICE_NAME)

            MySQLRouter.wait_until_mysql_router_ready(container)

            self.unit_peer_data[UNIT_BOOTSTRAPPED] = "true"

            return True

        return False

    # =======================
    #  Handlers
    # =======================

    def _on_install(self, _) -> None:
        """Handle the install event."""
        self.unit.status = WaitingStatus()

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
                [
                    1
                    for unit in self._peers.units.union({self.unit})
                    if self._peers.data[unit].get(UNIT_BOOTSTRAPPED)
                ]
            )
            self.app_peer_data[NUM_UNITS_BOOTSTRAPPED] = str(num_units_bootstrapped)


if __name__ == "__main__":
    main(MySQLRouterOperatorCharm)
