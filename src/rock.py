# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Workload ROCK or OCI container"""

import io
import logging
import typing

import ops

import container

logger = logging.getLogger(__name__)

_UNIX_USERNAME = "mysql"


class _Path(container.Path):
    """ROCK filesystem path"""

    def __new__(cls, *args, container_: ops.Container):
        path = super().__new__(cls, *args)
        path._container = container_
        return path

    def __truediv__(self, other):
        return type(self)(self, other, container_=self._container)

    def __rtruediv__(self, other):
        return type(self)(other, self, container_=self._container)

    @property
    def relative_to_container(self) -> "_Path":
        return self

    def read_text(self) -> str:
        with self._container.pull(self, encoding="utf-8") as file:
            file: io.TextIOWrapper
            return file.read()

    def write_text(self, data: str):
        self._container.push(
            self, data, permissions=0o600, user=_UNIX_USERNAME, group=_UNIX_USERNAME
        )

    def unlink(self, missing_ok=False):
        # TODO: use `self` instead of `str(self)` after next ops release
        path = str(self)
        if missing_ok and not self._container.exists(path):
            return
        self._container.remove_path(path)
        logger.debug(f"Deleted file {path=}")

    def mkdir(self):
        # TODO: use `self` instead of `str(self)` after next ops release
        self._container.make_dir(str(self), user=_UNIX_USERNAME, group=_UNIX_USERNAME)

    def rmtree(self):
        # TODO: use `self` instead of `str(self)` after next ops release
        self._container.remove_path(str(self), recursive=True)


class Rock(container.Container):
    """Workload ROCK or OCI container"""

    _SERVICE_NAME = "mysql_router"

    def __init__(self, *, unit: ops.Unit) -> None:
        super().__init__(mysql_router_command="mysqlrouter", mysql_shell_command="mysqlsh")
        self._container = unit.get_container("mysql-router")

    @property
    def ready(self) -> bool:
        return self._container.can_connect()

    @property
    def mysql_router_service_enabled(self) -> bool:
        service = self._container.get_services(self._SERVICE_NAME).get(self._SERVICE_NAME)
        if service is None:
            return False
        return service.startup == ops.pebble.ServiceStartup.ENABLED

    def update_mysql_router_service(self, *, enabled: bool, tls: bool = None) -> None:
        super().update_mysql_router_service(enabled=enabled, tls=tls)
        command = f"mysqlrouter --config {self.router_config_file}"
        if tls:
            command = f"{command} --extra-config {self.tls_config_file}"
        if enabled:
            startup = ops.pebble.ServiceStartup.ENABLED.value
        else:
            startup = ops.pebble.ServiceStartup.DISABLED.value
        layer = ops.pebble.Layer(
            {
                "summary": "MySQL Router layer",
                "services": {
                    self._SERVICE_NAME: {
                        "override": "replace",
                        "summary": "MySQL Router",
                        "command": command,
                        "startup": startup,
                        "user": _UNIX_USERNAME,
                        "group": _UNIX_USERNAME,
                    },
                },
            }
        )
        self._container.add_layer(self._SERVICE_NAME, layer, combine=True)
        self._container.replan()

    def _run_command(self, command: list[str], *, timeout: typing.Optional[int]) -> str:
        try:
            process = self._container.exec(
                command, user=_UNIX_USERNAME, group=_UNIX_USERNAME, timeout=timeout
            )
            output, _ = process.wait_output()
        except ops.pebble.ExecError as e:
            raise container.CalledProcessError(
                returncode=e.exit_code, cmd=e.command, output=e.stdout, stderr=e.stderr
            )
        return output

    def path(self, *args) -> _Path:
        return _Path(*args, container_=self._container)
