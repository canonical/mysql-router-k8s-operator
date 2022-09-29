# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the MySQL Router lifecycle."""

import logging
import socket

import mysql.connector
from tenacity import retry, stop_after_delay, wait_fixed

logger = logging.getLogger(__name__)


class Error(Exception):
    """Base class for exceptions in this module."""

    def __repr__(self):
        """String representation of the Error class."""
        return "<{}.{} {}>".format(type(self).__module__, type(self).__name__, self.args)

    @property
    def name(self):
        """Return a string representation of the model plus class."""
        return "<{}.{}>".format(type(self).__module__, type(self).__name__)

    @property
    def message(self):
        """Return the message passed as an argument."""
        return self.args[0]


class MySQLRouterCreateUserWithDatabasePrivilegesError(Error):
    """Exception raised when there is an issue creating a database scoped user."""


class MySQLRouterPortsNotOpenError(Error):
    """Exception raised when mysqlrouter is not bootstrapped and started."""


class MySQL:
    """Encapsulates all operations related to MySQL and MySQLRouter."""

    @staticmethod
    def create_user_with_database_privileges(
        username, password, hostname, database, db_username, db_password, db_host, db_port
    ) -> None:
        """Create a database scope mysql user.

        Args:
            username: Username of the user to create
            password: Password of the user to create
            hostname: Hostname of the user to create
            database: Database that the user should be restricted to
            db_username: The user to connect to the database with
            db_password: The password to use to connect to the database
            db_host: The host name of the database
            db_port: The port for the database

        Raises:
            MySQLRouterCreateUserWithDatabasePrivilegesError -
            when there is an issue creating a database scoped user
        """
        try:
            connection = mysql.connector.connect(
                user=db_username, password=db_password, host=db_host, port=db_port
            )
            cursor = connection.cursor()

            cursor.execute(f"CREATE USER '{username}'@'{hostname}' IDENTIFIED BY '{password}'")
            cursor.execute(f"GRANT ALL PRIVILEGES ON {database}.* TO '{username}'@'{hostname}'")

            cursor.close()
            connection.close()
        except mysql.connector.Error as e:
            logger.exception("Failed to create user scoped to a database", exc_info=e)
            raise MySQLRouterCreateUserWithDatabasePrivilegesError(e.msg)

    @staticmethod
    @retry(reraise=True, stop=stop_after_delay(30), wait=wait_fixed(5))
    def wait_until_mysql_router_ready(container) -> None:
        """Wait until a connection to MySQL router is possible.

        Retry every 5 seconds for 30 seconds if there is an issue obtaining a connection.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", 6446))
        if result != 0:
            raise MySQLRouterPortsNotOpenError()
        sock.close()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", 6447))
        if result != 0:
            raise MySQLRouterPortsNotOpenError()
        sock.close()
