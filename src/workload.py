import dataclasses
import logging
import socket
import string
import typing

import ops
import tenacity

import mysql_shell
from constants import (
    MYSQL_ROUTER_USER_NAME,
    ROUTER_CONFIG_DIRECTORY,
    TLS_SSL_CERT_FILE,
    TLS_SSL_CONFIG_FILE,
    TLS_SSL_KEY_FILE,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Workload:
    _container: ops.Container
    _service_name: str

    @property
    def container_ready(self) -> bool:
        return self._container.can_connect()

    @property
    def _service(self) -> typing.Optional[ops.pebble.Service]:
        service = self._container.get_services(self._service_name).get(self._service_name)
        if service is not None:
            assert service.startup == "enabled"
        return service

    @property
    def version(self) -> str:
        process = self._container.exec(["mysqlrouter", "--version"])
        raw_version, _ = process.wait_output()
        for version in raw_version.split():
            if version.startswith("8"):
                return version
        return ""


@dataclasses.dataclass
class AuthenticatedWorkload(Workload):
    _admin_username: str
    _admin_password: str
    _host: str
    _port: str

    @staticmethod
    def _get_layer(services: dict) -> ops.pebble.Layer:
        return ops.pebble.Layer(
            {
                "summary": "mysql router layer",
                "description": "the pebble config layer for mysql router",
                "services": services,
            }
        )

    def _get_active_layer(self, password: str, tls: bool) -> ops.pebble.Layer:
        if tls:
            command = f"/run.sh mysqlrouter --extra-config {ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_CONFIG_FILE}"
        else:
            command = "/run.sh mysqlrouter"
        return self._get_layer(
            {
                self._service_name: {
                    "override": "replace",
                    "summary": "mysql router",
                    "command": command,
                    "startup": "enabled",
                    "environment": {
                        "MYSQL_HOST": self._host,
                        "MYSQL_PORT": self._port,
                        "MYSQL_USER": MYSQL_ROUTER_USER_NAME,
                        "MYSQL_PASSWORD": password,
                    },
                },
            }
        )

    @property
    def _inactive_layer(self) -> ops.pebble.Layer:
        return self._get_layer({})

    def _update_layer(self, layer: ops.pebble.Layer) -> None:
        self._container.add_layer(self._service_name, layer, combine=True)
        self._container.replan()

    @property
    def shell(self) -> mysql_shell.Shell:
        return mysql_shell.Shell(
            self._container, self._admin_username, self._admin_password, self._host, self._port
        )

    @staticmethod
    @tenacity.retry(reraise=True, stop=tenacity.stop_after_delay(360), wait=tenacity.wait_fixed(5))
    def _wait_until_mysql_router_ready() -> None:
        # TODO: add debug logging
        """Wait until a connection to MySQL router is possible.
        Retry every 5 seconds for 30 seconds if there is an issue obtaining a connection.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", 6446))
        if result != 0:
            raise BaseException()
        sock.close()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", 6447))
        if result != 0:
            raise BaseException()
        sock.close()

    def enable(self, tls: bool) -> None:
        if self._service is not None:
            # If the host or port changes, MySQL Router will receive topology change notifications from MySQL
            # Therefore, if the host or port changes, we do not need to restart MySQL Router
            return
        logger.debug(f"Enabling MySQL Router service {tls=}, {self._host=}, {self._port=}")
        router_password = self.shell.create_mysql_router_user(MYSQL_ROUTER_USER_NAME)
        self._update_layer(self._get_active_layer(router_password, tls))
        logger.debug(f"Enabled MySQL Router service {tls=}, {self._host=}, {self._port=}")
        self._wait_until_mysql_router_ready()
        # TODO: wait until mysql router ready? https://github.com/canonical/mysql-router-k8s-operator/blob/45cf3be44f27476a0371c67d50d7a0193c0fadc2/src/charm.py#L219

    def disable(self) -> None:
        if self._service is None:
            return
        logger.debug("Disabling MySQL Router service")
        self.shell.delete_user(MYSQL_ROUTER_USER_NAME)
        self._update_layer(self._inactive_layer)
        logger.debug("Disabled MySQL Router service")

    def _restart(self, tls: bool) -> None:
        """Restart MySQL Router to enable or disable TLS."""
        logger.debug("Restarting MySQL Router service")
        password = self._service.environment["MYSQL_PASSWORD"]
        self._update_layer(self._get_active_layer(password, tls))
        logger.debug("Restarted MySQL Router service")

    def _write_file(self, path: str, content: str) -> None:
        """Write content to file.

        Args:
            path: Full filesystem path (with filename)
            content: File content
        """
        self._container.push(
            path,
            content,
            permissions=0o600,
            user=MYSQL_ROUTER_USER_NAME,
            group=MYSQL_ROUTER_USER_NAME,
        )

    def _delete_file(self, path: str) -> None:
        """Delete file.

        Args:
            path: Full filesystem path (with filename)
        """
        if self._container.exists(path):
            self._container.remove_path(path)

    @property
    def _tls_config_file(self) -> str:
        """Render TLS template to string.

        Config file enables TLS on MySQL Router.
        """
        with open("templates/tls.cnf", "r") as template_file:
            template = string.Template(template_file.read())
        config_string = template.substitute(
            tls_ssl_key_file=f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_KEY_FILE}",
            tls_ssl_cert_file=f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_CERT_FILE}",
        )
        return config_string

    def enable_tls(self, key: str, certificate: str):
        logger.debug("Enabling TLS")
        self._write_file(f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_CONFIG_FILE}", self._tls_config_file)
        self._write_file(f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_KEY_FILE}", key)
        self._write_file(f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_CERT_FILE}", certificate)
        if self._service is not None:
            self._restart(True)
        logger.debug("Enabled TLS")

    def disable_tls(self) -> None:
        logger.debug("Disabling TLS")
        for file in [TLS_SSL_CONFIG_FILE, TLS_SSL_KEY_FILE, TLS_SSL_CERT_FILE]:
            self._delete_file(f"{ROUTER_CONFIG_DIRECTORY}/{file}")
        if self._service is not None:
            self._restart(False)
        logger.debug("Disabled TLS")
