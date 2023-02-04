# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the database requires relation."""

import json
import logging
from typing import Dict

from charms.data_platform_libs.v0.database_requires import (
    DatabaseCreatedEvent,
    DatabaseEndpointsChangedEvent,
    DatabaseRequires,
)
from ops.framework import Object
from ops.model import BlockedStatus

from constants import (
    DATABASE_PROVIDES_RELATION,
    DATABASE_REQUIRES_RELATION,
    MYSQL_DATABASE_CREATED,
    MYSQL_ROUTER_PROVIDES_DATA,
    MYSQL_ROUTER_REQUIRES_APPLICATION_DATA,
    MYSQL_ROUTER_REQUIRES_DATA,
    PASSWORD_LENGTH,
)
from mysql_router_helpers import (
    MySQLRouter,
    MySQLRouterCreateUserWithDatabasePrivilegesError,
)
from utils import generate_random_password

logger = logging.getLogger(__name__)


class DatabaseRequiresRelation(Object):
    """Encapsulation of the relation between mysqlrouter and mysql database."""

    def __init__(self, charm):
        super().__init__(charm, {DATABASE_REQUIRES_RELATION})

        self.charm = charm

        self.framework.observe(
            self.charm.on[DATABASE_REQUIRES_RELATION].relation_joined,
            self._on_database_requires_relation_joined,
        )

        provides_data = self._get_provides_data()
        if not provides_data:
            return

        self.database_requires_relation = DatabaseRequires(
            self.charm,
            relation_name=DATABASE_REQUIRES_RELATION,
            database_name=provides_data["database"],
            extra_user_roles="mysqlrouter",
        )

        self.framework.observe(
            self.database_requires_relation.on.database_created, self._on_database_created
        )
        self.framework.observe(
            self.database_requires_relation.on.endpoints_changed, self._on_endpoints_changed
        )

    # =======================
    #  Helpers
    # =======================

    def _get_provides_data(self) -> Dict:
        """Helper to get the `provides` relation data from the app peer databag."""
        provides_data = self.charm.app_peer_data.get(MYSQL_ROUTER_PROVIDES_DATA)
        if not provides_data:
            return None

        return json.loads(provides_data)

    # =======================
    #  Handlers
    # =======================

    def _on_database_requires_relation_joined(self, event) -> None:
        """Handle the backend-database relation joined event.

        Waits until the database relation with the application is formed before
        triggering the database_requires relation joined event (which will
        request the database).
        """
        provides_data = self._get_provides_data()
        if not provides_data:
            event.defer()
            return

        self.database_requires_relation._on_relation_joined_event(event)

    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Handle the database created event."""
        if not self.charm.unit.is_leader():
            return

        if self.charm.app_peer_data.get(MYSQL_DATABASE_CREATED):
            return

        self.charm.app_peer_data[MYSQL_ROUTER_REQUIRES_DATA] = json.dumps(
            {
                "username": event.username,
                "endpoints": event.endpoints,
            }
        )

        self.charm._set_secret("app", "database-password", event.password)

        provides_data = self._get_provides_data()
        provides_relation_id = self.charm.model.relations[DATABASE_PROVIDES_RELATION][0].id

        username = f"application-user-{provides_relation_id}"
        password = generate_random_password(PASSWORD_LENGTH)

        try:
            MySQLRouter.create_user_with_database_privileges(
                username,
                password,
                "%",
                provides_data["database"],
                event.username,
                event.password,
                event.endpoints.split(",")[0].split(":")[0],
                "3306",
            )
        except MySQLRouterCreateUserWithDatabasePrivilegesError as e:
            logger.exception("Failed to create a database scoped user", exc_info=e)
            self.charm.unit.status = BlockedStatus("Failed to create a database scoped user")
            return

        self.charm.app_peer_data[MYSQL_ROUTER_REQUIRES_APPLICATION_DATA] = json.dumps(
            {
                "username": username,
            }
        )

        self.charm._set_secret("app", "application-password", password)

        self.charm.app_peer_data[MYSQL_DATABASE_CREATED] = "true"

    def _on_endpoints_changed(self, event: DatabaseEndpointsChangedEvent) -> None:
        """Handle the endpoints changed event.

        Update the endpoint in the MYSQL_ROUTER_REQUIRES_DATA so that future
        bootstrapping units will not fail.
        """
        if not self.charm.unit.is_leader():
            return

        if self.charm.app_peer_data.get(MYSQL_ROUTER_REQUIRES_DATA):
            requires_data = json.loads(self.charm.app_peer_data[MYSQL_ROUTER_REQUIRES_DATA])

            requires_data["endpoints"] = event.endpoints

            self.charm.app_peer_data[MYSQL_ROUTER_REQUIRES_DATA] = json.dumps(requires_data)
