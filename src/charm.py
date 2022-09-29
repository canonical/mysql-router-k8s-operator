#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL-Router k8s charm."""

import json
import logging
from typing import Dict, Optional

import lightkube
from lightkube import codecs
from lightkube.resources.core_v1 import Service
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
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
from mysql_helpers import MySQL
from relations.database_provides import DatabaseProvidesRelation
from relations.database_requires import DatabaseRequiresRelation

logger = logging.getLogger(__name__)


class MySQLRouterOperatorCharm(CharmBase):
    """Operator charm for MySQLRouter."""

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(
            self.on.mysql_router_pebble_ready, self._on_mysql_router_pebble_ready
        )
        self.framework.observe(self.on.update_status, self._on_update_status)

        self.database_provides = DatabaseProvidesRelation(self)
        self.database_requires = DatabaseRequiresRelation(self)

    # =======================
    #  Properties
    # =======================

    @property
    def _peers(self) -> list:
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

    def _mysql_router_layer(self, host: str, port: str, username: str, password: str) -> Dict:
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

    def _bootstrap_mysqlrouter(self) -> None:
        if not self.app_peer_data.get(MYSQL_DATABASE_CREATED):
            return False

        requires_data = json.loads(self.app_peer_data[MYSQL_ROUTER_REQUIRES_DATA])
        pebble_layer = self._mysql_router_layer(
            requires_data["endpoints"].split(",")[0].split(":")[0],
            "3306",
            requires_data["username"],
            self._get_secret("app", "database-password"),
        )

        container = self.unit.get_container(MYSQL_ROUTER_CONTAINER_NAME)
        plan = container.get_plan()

        if plan.services != pebble_layer.services:
            container.add_layer(MYSQL_ROUTER_SERVICE_NAME, pebble_layer, combine=True)
            container.start(MYSQL_ROUTER_SERVICE_NAME)

            MySQL.wait_until_mysql_router_ready(container)

            self.unit_peer_data[UNIT_BOOTSTRAPPED] = "true"

            # Triggers a peer_relation_changed event in the DatabaseProvidesRelation
            num_units_bootstrapped = int(self.app_peer_data.get(NUM_UNITS_BOOTSTRAPPED, "0"))
            self.app_peer_data[NUM_UNITS_BOOTSTRAPPED] = str(num_units_bootstrapped + 1)

            return True

        return False

    # =======================
    #  Handlers
    # =======================

    def _on_leader_elected(self, _) -> None:
        """Handle the leader elected event.

        Creates read-write and read-only services from a template file, and deletes
        the service created by juju for the application.
        """
        client = lightkube.Client()

        # Delete the service created by juju if it still exists
        try:
            client.delete(Service, name=self.model.app.name, namespace=self.model.name)
        except lightkube.ApiError as e:
            if e.status.code != 404:
                self.unit.status = BlockedStatus("Failed to delete k8s service")
                return

        # Create the read-write and read-only services defined in the yaml file
        with open("src/k8s_services.yaml", "r") as resource_file:
            for service in codecs.load_all_yaml(
                resource_file, context={"app_name": self.model.app.name}
            ):
                try:
                    client.create(service)
                except lightkube.ApiError as e:
                    # Do nothing if the service already exists
                    if e.status.code != 409:
                        self.unit.status = BlockedStatus("Failed to create k8s service")
                        return

        self.unit.status = WaitingStatus()

    def _on_mysql_router_pebble_ready(self, _) -> None:
        """Handle the mysql-router pebble ready event."""
        if self._bootstrap_mysqlrouter():
            self.unit.status = ActiveStatus()

    def _on_update_status(self, _) -> None:
        """Handle the update status event.

        Bootstraps mysqlrouter if the relations exist, but pebble_ready event
        fired before the requires relation was formed.
        """
        if (
            isinstance(self.unit.status, WaitingStatus)
            and self.app_peer_data.get(MYSQL_DATABASE_CREATED)
            and self._bootstrap_mysqlrouter()
        ):
            self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(MySQLRouterOperatorCharm)
