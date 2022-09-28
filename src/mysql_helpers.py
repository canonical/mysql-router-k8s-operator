# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the MySQL Router lifecycle."""

import logging

import mysql.connector

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
