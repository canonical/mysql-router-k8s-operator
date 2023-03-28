# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the database provides relation."""

import json
import logging

from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseProvides,
    DatabaseRequestedEvent,
)
from ops.framework import Object
from ops.model import WaitingStatus

from constants import (
    CREDENTIALS_SHARED,
    DATABASE_PROVIDES_RELATION,
    DATABASE_REQUIRES_RELATION,
    MYSQL_DATABASE_CREATED,
    MYSQL_ROUTER_PROVIDES_DATA,
    MYSQL_ROUTER_REQUIRES_APPLICATION_DATA,
    PEER,
    UNIT_BOOTSTRAPPED,
)
from mysql_router_helpers import MySQLRouter

logger = logging.getLogger(__name__)


class DatabaseProvidesRelation(Object):
    """Encapsulation of the relation between mysqlrouter and the consumer application."""

    def __init__(self, charm):
        super().__init__(charm, DATABASE_PROVIDES_RELATION)

        self.charm = charm
        self.database_provides_relation = DatabaseProvides(
            self.charm, relation_name=DATABASE_PROVIDES_RELATION
        )

        self.framework.observe(
            self.database_provides_relation.on.database_requested, self._on_database_requested
        )
        self.framework.observe(
            self.charm.on[PEER].relation_changed, self._on_peer_relation_changed
        )

        self.framework.observe(
            self.charm.on[DATABASE_PROVIDES_RELATION].relation_broken, self._on_database_broken
        )

    # =======================
    #  Handlers
    # =======================

    def _on_database_requested(self, event: DatabaseRequestedEvent) -> None:
        """Handle the database requested event."""
        if not self.charm.unit.is_leader():
            return

        # Store data in databag to trigger DatabaseRequires initialization in database_requires.py
        self.charm.app_peer_data[MYSQL_ROUTER_PROVIDES_DATA] = json.dumps(
            {"database": event.database, "extra_user_roles": event.extra_user_roles}
        )

    def _on_peer_relation_changed(self, _) -> None:
        """Handle the peer relation changed event."""
        if not self.charm.unit.is_leader():
            return

        if self.charm.app_peer_data.get(CREDENTIALS_SHARED):
            logger.debug("Credentials already shared")
            return

        if not self.charm.app_peer_data.get(MYSQL_DATABASE_CREATED):
            logger.debug("Database not created yet")
            return

        if not self.charm.unit_peer_data.get(UNIT_BOOTSTRAPPED):
            logger.debug("Unit not bootstrapped yet")
            return

        if not self.charm.app_peer_data.get(MYSQL_ROUTER_REQUIRES_APPLICATION_DATA):
            logger.debug("No requires application data found")
            return

        database_provides_relations = self.charm.model.relations.get(DATABASE_PROVIDES_RELATION)

        requires_application_data = json.loads(
            self.charm.app_peer_data[MYSQL_ROUTER_REQUIRES_APPLICATION_DATA]
        )
        provides_relation_id = database_provides_relations[0].id

        self.database_provides_relation.set_credentials(
            provides_relation_id,
            requires_application_data["username"],
            self.charm.get_secret("app", "application-password"),
        )

        self.database_provides_relation.set_endpoints(
            provides_relation_id, f"{self.charm.endpoint}:6446"
        )

        self.database_provides_relation.set_read_only_endpoints(
            provides_relation_id, f"{self.charm.endpoint}:6447"
        )

        self.charm.app_peer_data[CREDENTIALS_SHARED] = "true"

    def _on_database_broken(self, _) -> None:
        """Handle the database relation broken event."""
        self.charm.unit.status = WaitingStatus(
            f"Waiting for relations: {DATABASE_PROVIDES_RELATION}"
        )
        if not self.charm.unit.is_leader():
            return

        # application user cleanup when backend relation still in place
        if backend_relation := self.charm.model.get_relation(DATABASE_REQUIRES_RELATION):
            if app_data := self.charm.app_peer_data.get(MYSQL_ROUTER_REQUIRES_APPLICATION_DATA):
                username = json.loads(app_data)["username"]

                db_username = backend_relation.data[backend_relation.app]["username"]
                db_password = backend_relation.data[backend_relation.app]["password"]
                db_host, db_port = backend_relation.data[backend_relation.app]["endpoints"].split(
                    ":"
                )

                MySQLRouter.delete_application_user(
                    username=username,
                    hostname="%",
                    db_username=db_username,
                    db_password=db_password,
                    db_host=db_host,
                    db_port=db_port,
                )
        # clean up departing app data
        self.charm.app_peer_data.pop(MYSQL_ROUTER_REQUIRES_APPLICATION_DATA, None)
        self.charm.app_peer_data.pop(MYSQL_ROUTER_PROVIDES_DATA, None)
        self.charm.app_peer_data.pop(CREDENTIALS_SHARED, None)
        self.charm.set_secret("app", "application-password", None)
