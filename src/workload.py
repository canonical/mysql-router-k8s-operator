import dataclasses
import logging
import socket

import ops
import tenacity

from constants import (
    MYSQL_ROUTER_SERVICE_NAME,
    MYSQL_ROUTER_USER_NAME,
    ROUTER_CONFIG_DIRECTORY,
    TLS_SSL_CERT_FILE,
    TLS_SSL_CONFIG_FILE,
    TLS_SSL_KEY_FILE,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Workload:
    _container: ops.model.Container

    @property
    def container_ready(self) -> bool:
        return self._container.can_connect()

    @property
    def running(self) -> bool:
        service = self._container.get_services(MYSQL_ROUTER_SERVICE_NAME).get(
            MYSQL_ROUTER_SERVICE_NAME
        )
        if service is None:
            return False
        return service.is_running()

    @property
    def version(self) -> str:
        process = self._container.exec(["mysqlrouter", "--version"])
        raw_version, _ = process.wait_output()
        for version in raw_version.split():
            if version.startswith("8"):
                return version
        return ""

    def start(self, host, port, username, password) -> None:
        if self.running:
            # If the host or port changes, MySQL Router will receive topology change notifications from MySQL
            # Therefore, if the host or port changes, we do not need to restart MySQL Router
            # TODO: update comment
            # Assumption: username or password will not change while database requires relation is active
            # Therefore, MySQL Router does not need to be restarted if it is already running
            return
        logger.debug(f"Starting MySQL Router service {host=}, {port=}, {username=}")
        self._container.add_layer(
            MYSQL_ROUTER_SERVICE_NAME,
            self._get_mysql_router_layer(host, port, username, password),
            combine=True,
        )
        self._container.start(MYSQL_ROUTER_SERVICE_NAME)
        logger.debug(f"Started MySQL Router service {host=}, {port=}, {username=}")
        self._wait_until_mysql_router_ready()
        # TODO: wait until mysql router ready? https://github.com/canonical/mysql-router-k8s-operator/blob/45cf3be44f27476a0371c67d50d7a0193c0fadc2/src/charm.py#L219

    def stop(self) -> None:
        if not self.running:
            return
        logger.debug("Stopping MySQL Router service")
        self._container.stop(MYSQL_ROUTER_SERVICE_NAME)
        logger.debug("Stopped MySQL Router service")

    def enable_tls(
        self, layer: ops.pebble.Layer, config_file_content: str, key: str, certificate: str
    ):
        logger.debug("Enabling TLS")
        self._write_file(f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_CONFIG_FILE}", config_file_content)
        self._write_file(f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_KEY_FILE}", key)
        self._write_file(f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_CERT_FILE}", certificate)
        self._container.add_layer(MYSQL_ROUTER_SERVICE_NAME, layer, combine=True)
        self._container.replan()
        logger.debug("Enabled TLS")

    def disable_tls(self) -> None:
        logger.debug("Disabling TLS")
        for file in [TLS_SSL_CONFIG_FILE, TLS_SSL_KEY_FILE, TLS_SSL_CERT_FILE]:
            self._delete_file(f"{ROUTER_CONFIG_DIRECTORY}/{file}")
        layer = ops.pebble.Layer(
            {
                "services": {
                    MYSQL_ROUTER_SERVICE_NAME: {
                        "override": "merge",
                        "command": "/run.sh mysqlrouter",
                    },
                },
            },
        )
        self._container.add_layer(MYSQL_ROUTER_SERVICE_NAME, layer, combine=True)
        self._container.replan()
        logger.debug("Disabled TLS")

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

    @staticmethod
    def _get_mysql_router_layer(
        host: str, port: str, username: str, password: str
    ) -> ops.pebble.Layer:
        return ops.pebble.Layer(
            {
                "summary": "mysql router layer",
                "description": "the pebble config layer for mysql router",
                "services": {
                    MYSQL_ROUTER_SERVICE_NAME: {
                        "override": "replace",
                        "summary": "mysql router",
                        "command": "/run.sh mysqlrouter",
                        "startup": "enabled",
                        "environment": {
                            "MYSQL_HOST": host,
                            "MYSQL_PORT": port,
                            "MYSQL_USER": username,  # TODO switch to limited permissions user
                            "MYSQL_PASSWORD": password,
                        },
                    },
                },
            }
        )

    @staticmethod
    @tenacity.retry(
        reraise=True, stop=tenacity.stop_after_delay(360), wait=tenacity.wait_fixed(5)
    )
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
