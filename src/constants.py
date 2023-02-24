# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""File containing constants to be used in the charm."""

CREDENTIALS_SHARED = "credentials-shared"
DATABASE_REQUIRES_RELATION = "backend-database"
DATABASE_PROVIDES_RELATION = "database"
NUM_UNITS_BOOTSTRAPPED = "num-units-bootstrapped"
MYSQL_ROUTER_CONTAINER_NAME = "mysql-router"
MYSQL_DATABASE_CREATED = "database-created"
MYSQL_ROUTER_PROVIDES_DATA = "provides-data"
MYSQL_ROUTER_REQUIRES_DATA = "requires-data"
MYSQL_ROUTER_REQUIRES_APPLICATION_DATA = "requires-application-data"
MYSQL_ROUTER_SERVICE_NAME = "mysql_router"
MYSQL_ROUTER_USER_NAME = "mysqlrouter"
PASSWORD_LENGTH = 24
PEER = "mysql-router-peers"
ROUTER_CONFIG_DIRECTORY = "/tmp/mysqlrouter"
UNIT_BOOTSTRAPPED = "unit-bootstrapped"
TLS_RELATION = "certificates"
TLS_SSL_CONFIG_FILE = "tls.conf"
TLS_SSL_CERT_FILE = "router.crt"
TLS_SSL_KEY_FILE = "router.key"
