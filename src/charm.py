#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""MySQL-Router charm."""

import json
import logging
from typing import Any

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)
DATABASE = "database"
PEER = "mysql-router"


class MySQLRouterOperatorCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)

        self.name = "mysqlrouter"

        self.framework.observe(self.on.mysqlrouter_pebble_ready, self._on_mysqlrouter_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.on.database_relation_created, self._on_database_relation_created
        )
        self.framework.observe(
            self.on.database_relation_departed, self._on_database_relation_departed
        )

    @property
    def has_db(self) -> bool:
        """Only consider a DB connection if we have config info."""
        rel = self.model.get_relation(DATABASE)
        return len(rel.units) > 0 if rel is not None else False

    @property
    def peers(self) -> list:
        """Fetch the peer relation."""
        return self.model.get_relation(PEER)

    def set_peer_data(self, key: str, data: Any) -> None:
        """Put information into the peer data."""
        if self.unit.is_leader():
            self.peers.data[self.app][key] = json.dumps(data)

    def get_peer_data(self, key: str) -> Any:
        """Retrieve information from the peer data."""
        data = self.peers.data[self.app].get(key, "{}")
        return json.loads(data)

    def _configure(self) -> None:
        """Configure the charm."""
        # Get the relation data
        data = self.get_peer_data(DATABASE)

        config_data = json.loads(data["mysql"])

        # Define Pebble layer configuration
        pebble_layer = self._mysqlrouter_layer(
            port=config_data["port"],
            host=config_data["host"],
            user=config_data["user"],
            password=config_data["password"],
        )
        # Add initial Pebble config layer using the Pebble API
        container = self.unit.get_container(self.name)
        plan = container.get_plan()

        if plan.services != pebble_layer.services:
            logger.info("Config changed")
            container.add_layer(self.name, pebble_layer, combine=True)

            if container.get_service(self.name).is_running():
                container.stop(self.name)

            container.start(self.name)
            logging.info("mysqlrouter restarted")

        self.unit.status = ActiveStatus()

    def _on_mysqlrouter_pebble_ready(self, event) -> None:
        """Define and start a workload using the Pebble API."""
        if not self.has_db:
            logger.debug("No database relation found")
            self.unit.status = WaitingStatus("Waiting for database relation")
            event.defer()
            return

        self._configure()

    def _mysqlrouter_layer(self, host, port, user, password) -> dict:
        """Return a layer configuration for the mysqlrouter service.

        Args:
            host (str): The hostname of the MySQL cluster.
            port (int): The port of the MySQL cluster.
            user (str): The username for the MySQL cluster.
            password (str): The password for the MySQL cluster.
        """
        return Layer(
            {
                "summary": "mysqlrouter layer",
                "description": "pebble config layer for mysqlrouter",
                "services": {
                    "mysqlrouter": {
                        "override": "replace",
                        "summary": "mysqlrouter",
                        "command": "./run.sh",
                        "startup": "enabled",
                        "environment": {
                            "MYSQL_PORT": port,
                            "MYSQL_HOST": host,
                            "MYSQL_USER": user,
                            "MYSQL_PASSWORD": password,
                        },
                    }
                },
            }
        )

    def _on_config_changed(self, event) -> None:
        """Handle config-changed event."""
        if not self.has_db:
            logger.debug("No database relation found")
            self.unit.status = WaitingStatus("Waiting for database relation")
            event.defer()
            return

        self._configure()

    def _on_database_relation_created(self, event) -> None:
        """Handle database relation created event."""
        logger.info("Database relation created")
        if not self.has_db:
            logger.info("No database relation found")
            self.unit.status = WaitingStatus("Waiting for database relation")
            event.defer()
            return

        data = dict(event.relation.data[event.app])
        self.set_peer_data(DATABASE, data)
        self._configure()

    def _on_database_relation_departed(self, event) -> None:
        """Handle database relation departed event."""
        container = event.workload
        # Remove the pebble layer
        container.stop("mysqlrouter")

        self.unit.status = WaitingStatus("Waiting for database relation")


if __name__ == "__main__":
    main(MySQLRouterOperatorCharm)
