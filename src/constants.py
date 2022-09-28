# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""File containing constants to be used in the charm."""

CREDENTIALS_SHARED = "credentials-shared"
DATABASE_REQUIRES_RELATION = "backend-database"
DATABASE_PROVIDES_RELATION = "database"
MYSQL_ROUTER_CONTAINER_NAME = "mysql-router"
MYSQL_DATABASE_CREATED = "database-created"
MYSQL_ROUTER_PROVIDES_DATA = "provides-data"
MYSQL_ROUTER_REQUIRES_DATA = "requires-data"
MYSQL_ROUTER_REQUIRES_APPLICATION_DATA = "requires-application-data"
MYSQL_ROUTER_SERVICE_NAME = "mysql_router"
PASSWORD_LENGTH = 24
PEER = "mysql-router"
UNIT_BOOTSTRAPPED = "unit-bootstrapped"
