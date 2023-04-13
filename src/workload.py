import dataclasses

import ops

from constants import MYSQL_ROUTER_SERVICE_NAME


@dataclasses.dataclass
class Workload:
    _container: ops.model.Container

    @property
    def container_ready(self) -> bool:
        return self._container.can_connect()

    @property
    def active(self) -> bool:
        return self._container.get_service(MYSQL_ROUTER_SERVICE_NAME).is_running()

    @property
    def version(self) -> str:
        process = self._container.exec(["mysqlrouter", "-V"])
        raw_version, _ = process.wait_output()
        for version in raw_version.strip().split():
            if version.startswith("8"):
                return version
        return ""

    def start(self, host, port, username, password) -> None:
        if self.active:
            # If the host or port changes, MySQL Router will receive topology change notifications from MySQL
            # Therefore, if the host or port changes, we do not need to restart MySQL Router
            # Assumption: username or password will not change while database requires relation is active
            # Therefore, MySQL Router does not need to be restarted if it is already running
            return
        self._container.add_layer(
            MYSQL_ROUTER_SERVICE_NAME,
            self._get_mysql_router_layer(host, port, username, password),
            combine=True,
        )
        self._container.start(MYSQL_ROUTER_SERVICE_NAME)
        # TODO: wait until mysql router ready? https://github.com/canonical/mysql-router-k8s-operator/blob/45cf3be44f27476a0371c67d50d7a0193c0fadc2/src/charm.py#L219

    def stop(self) -> None:
        self._container.stop(MYSQL_ROUTER_SERVICE_NAME)

    def enable_tls(self, layer: ops.pebble.Layer):
        self._container.add_layer(MYSQL_ROUTER_SERVICE_NAME, layer, combine=True)
        self._container.replan()

    def disable_tls(self) -> None:
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
                            "MYSQL_USER": username,
                            "MYSQL_PASSWORD": password,
                        },
                    },
                },
            }
        )
