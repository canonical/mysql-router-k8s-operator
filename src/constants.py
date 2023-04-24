# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""File containing constants to be used in the charm."""

DATABASE_REQUIRES_RELATION = "backend-database"
DATABASE_PROVIDES_RELATION = "database"
MYSQL_ROUTER_CONTAINER_NAME = "mysql-router"
MYSQL_ROUTER_SERVICE_NAME = "mysql_router"
MYSQL_ROUTER_USER_NAME = "mysqlrouter"
PASSWORD_LENGTH = 24
PEER_RELATION = "mysql-router-peers"
ROUTER_CONFIG_DIRECTORY = "/tmp/mysqlrouter"
TLS_RELATION = "certificates"
TLS_SSL_CONFIG_FILE = "tls.conf"
TLS_SSL_CERT_FILE = "custom-cert.pem"
TLS_SSL_KEY_FILE = "custom-key.pem"
