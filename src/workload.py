# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQL Router workload"""

import configparser
import dataclasses
import logging
import pathlib
import string
import typing

import ops

import mysql_shell

if typing.TYPE_CHECKING:
    import charm
logger = logging.getLogger(__name__)


@dataclasses.dataclass(kw_only=True)
class Workload:
    """MySQL Router workload"""

    _container: ops.Container

    CONTAINER_NAME = "mysql-router"
    _SERVICE_NAME = "mysql_router"

    @property
    def container_ready(self) -> bool:
        """Whether container is ready"""
        return self._container.can_connect()

    @property
    def _enabled(self) -> bool:
        """Service status"""
        service = self._container.get_services(self._SERVICE_NAME).get(self._SERVICE_NAME)
        if service is None:
            return False
        return service.startup == ops.pebble.ServiceStartup.ENABLED

    @property
    def version(self) -> str:
        """MySQL Router version"""
        process = self._container.exec(["mysqlrouter", "--version"])
        raw_version, _ = process.wait_output()
        for version in raw_version.split():
            if version.startswith("8"):
                return version
        return ""


@dataclasses.dataclass(kw_only=True)
class AuthenticatedWorkload(Workload):
    """Workload with connection to MySQL cluster"""

    # Admin user with permission to:
    # - Create databases & users
    # - Grant all privileges on a database to a user
    # (Different from user that MySQL Router runs with after bootstrap.)
    _admin_username: str
    _admin_password: str
    _host: str
    _port: str
    _charm: "charm.MySQLRouterOperatorCharm"

    _UNIX_USERNAME = "mysql"
    _ROUTER_CONFIG_DIRECTORY = pathlib.Path("/etc/mysqlrouter")
    _ROUTER_CONFIG_FILE = "mysqlrouter.conf"
    _TLS_CONFIG_FILE = "tls.conf"
    _TLS_KEY_FILE = "custom-key.pem"
    _TLS_CERTIFICATE_FILE = "custom-certificate.pem"

    def _update_layer(self, *, enabled: bool, tls: bool = None) -> None:
        """Update and restart services.

        Args:
            enabled: Whether MySQL Router service is enabled
            tls: Whether TLS is enabled. Required if enabled=True
        """
        if enabled:
            assert tls is not None, "`tls` argument required when enabled=True"
        command = (
            f"mysqlrouter --config {self._ROUTER_CONFIG_DIRECTORY / self._ROUTER_CONFIG_FILE}"
        )
        if tls:
            command = (
                f"{command} --extra-config {self._ROUTER_CONFIG_DIRECTORY / self._TLS_CONFIG_FILE}"
            )
        if enabled:
            startup = ops.pebble.ServiceStartup.ENABLED.value
        else:
            startup = ops.pebble.ServiceStartup.DISABLED.value
        layer = ops.pebble.Layer(
            {
                "summary": "mysql router layer",
                "description": "the pebble config layer for mysql router",
                "services": {
                    self._SERVICE_NAME: {
                        "override": "replace",
                        "summary": "mysql router",
                        "command": command,
                        "startup": startup,
                        "user": self._UNIX_USERNAME,
                        "group": self._UNIX_USERNAME,
                    },
                },
            }
        )
        self._container.add_layer(self._SERVICE_NAME, layer, combine=True)
        self._container.replan()

    @property
    def shell(self) -> mysql_shell.Shell:
        """MySQL Shell"""
        return mysql_shell.Shell(
            _container=self._container,
            _username=self._admin_username,
            _password=self._admin_password,
            _host=self._host,
            _port=self._port,
        )

    def _bootstrap_router(self, *, tls: bool) -> None:
        """Bootstrap MySQL Router and enable service."""
        logger.debug(f"Bootstrapping router {tls=}, {self._host=}, {self._port=}")
        try:
            # Bootstrap MySQL Router
            process = self._container.exec(
                [
                    "mysqlrouter",
                    "--bootstrap",
                    f"{self._admin_username}:{self._admin_password}@{self._host}:{self._port}",
                    "--strict",
                    "--user",
                    self._UNIX_USERNAME,
                    "--conf-set-option",
                    "http_server.bind_address=127.0.0.1",
                ],
                timeout=30,
            )
            process.wait_output()
        except ops.pebble.ExecError as e:
            logger.exception(f"Failed to bootstrap router\nstderr:\n{e.stderr}\n")
            raise
        # Enable service
        self._update_layer(enabled=True, tls=tls)

        logger.debug(f"Bootstrapped router {tls=}, {self._host=}, {self._port=}")

    def enable(self, *, tls: bool) -> None:
        """Start and enable MySQL Router service."""
        if self._enabled:
            # If the host or port changes, MySQL Router will receive topology change
            # notifications from MySQL.
            # Therefore, if the host or port changes, we do not need to restart MySQL Router.
            return
        logger.debug("Enabling MySQL Router service")
        self._bootstrap_router(tls=tls)
        logger.debug("Enabled MySQL Router service")
        self._charm.wait_until_mysql_router_ready()

    def _restart(self, *, tls: bool) -> None:
        """Restart MySQL Router to enable or disable TLS."""
        logger.debug("Restarting MySQL Router")
        assert self._enabled is True
        self._bootstrap_router(tls=tls)
        logger.debug("Restarted MySQL Router")
        self._charm.wait_until_mysql_router_ready()

    @property
    def _router_username(self) -> str:
        """Read MySQL Router username from config file.

        During bootstrap, MySQL Router creates a config file at
        `/etc/mysqlrouter/mysqlrouter.conf`. This file contains the username that was created
        during bootstrap.
        """
        config = configparser.ConfigParser()
        config.read_file(self._container.pull("/etc/mysqlrouter/mysqlrouter.conf"))
        return config["metadata_cache:bootstrap"]["user"]

    def disable(self) -> None:
        """Stop and disable MySQL Router service."""
        if not self._enabled:
            return
        logger.debug("Disabling MySQL Router service")
        self._update_layer(enabled=False)
        self.shell.delete_user(self._router_username)
        logger.debug("Disabled MySQL Router service")

    def _write_file(self, path: pathlib.Path, content: str) -> None:
        """Write content to file.

        Args:
            path: Full filesystem path (with filename)
            content: File content
        """
        self._container.push(
            str(path),
            content,
            permissions=0o600,
            user=self._UNIX_USERNAME,
            group=self._UNIX_USERNAME,
        )
        logger.debug(f"Wrote file {path=}")

    def _delete_file(self, path: pathlib.Path) -> None:
        """Delete file.

        Args:
            path: Full filesystem path (with filename)
        """
        path = str(path)
        if self._container.exists(path):
            self._container.remove_path(path)
            logger.debug(f"Deleted file {path=}")

    @property
    def _tls_config_file(self) -> str:
        """Render config file template to string.

        Config file enables TLS on MySQL Router.
        """
        with open("templates/tls.cnf", "r") as template_file:
            template = string.Template(template_file.read())
        config_string = template.substitute(
            tls_ssl_key_file=self._ROUTER_CONFIG_DIRECTORY / self._TLS_KEY_FILE,
            tls_ssl_cert_file=self._ROUTER_CONFIG_DIRECTORY / self._TLS_CERTIFICATE_FILE,
        )
        return config_string

    def enable_tls(self, *, key: str, certificate: str):
        """Enable TLS and restart MySQL Router."""
        logger.debug("Enabling TLS")
        self._write_file(
            self._ROUTER_CONFIG_DIRECTORY / self._TLS_CONFIG_FILE, self._tls_config_file
        )
        self._write_file(self._ROUTER_CONFIG_DIRECTORY / self._TLS_KEY_FILE, key)
        self._write_file(self._ROUTER_CONFIG_DIRECTORY / self._TLS_CERTIFICATE_FILE, certificate)
        if self._enabled:
            self._restart(tls=True)
        logger.debug("Enabled TLS")

    def disable_tls(self) -> None:
        """Disable TLS and restart MySQL Router."""
        logger.debug("Disabling TLS")
        for file in [self._TLS_CONFIG_FILE, self._TLS_KEY_FILE, self._TLS_CERTIFICATE_FILE]:
            self._delete_file(self._ROUTER_CONFIG_DIRECTORY / file)
        if self._enabled:
            self._restart(tls=False)
        logger.debug("Disabled TLS")
