# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Workload rock or OCI container"""

import logging
import typing

import ops
import tenacity

import container

if typing.TYPE_CHECKING:
    import relations.cos

logger = logging.getLogger(__name__)

CONTAINER_NAME = "mysql-router"
_UNIX_USERNAME = "mysql"


class _Path(container.Path):
    """Rock filesystem path"""

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

    def open(self, mode="r") -> typing.TextIO:
        super().open(mode)
        return self._container.pull(self, encoding="utf-8")

    def read_text(self) -> str:
        with self.open("r") as file:
            return file.read()

    def write_text(self, data: str):
        self._container.push(
            self,
            data,
            encoding="utf-8",
            permissions=0o600,
            user=_UNIX_USERNAME,
            group=_UNIX_USERNAME,
        )

    def unlink(self, missing_ok=False):
        if missing_ok and not self._container.exists(self):
            return
        self._container.remove_path(self)
        logger.debug(f"Deleted file {self=}")

    def mkdir(self):
        self._container.make_dir(self, user=_UNIX_USERNAME, group=_UNIX_USERNAME)

    def rmtree(self):
        self._container.remove_path(self, recursive=True)

    def exists(self) -> bool:
        return self._container.exists(self)


class Rock(container.Container):
    """Workload rock or OCI container"""

    _SERVICE_NAME = "mysql_router"
    _EXPORTER_SERVICE_NAME = "mysql_router_exporter"
    _LOGROTATE_EXECUTOR_SERVICE_NAME = "logrotate_executor"

    def __init__(self, *, unit: ops.Unit) -> None:
        super().__init__(
            mysql_router_command="mysqlrouter",
            mysql_shell_command="mysqlsh",
            mysql_router_password_command="mysqlrouter_passwd",
            unit_name=unit.name,
        )
        self._container = unit.get_container(CONTAINER_NAME)

    @property
    def ready(self) -> bool:
        return self._container.can_connect()

    @property
    def mysql_router_service_enabled(self) -> bool:
        service = self._container.get_services(self._SERVICE_NAME).get(self._SERVICE_NAME)
        if service is None:
            return False
        return service.startup == ops.pebble.ServiceStartup.ENABLED

    @property
    def mysql_router_exporter_service_enabled(self) -> bool:
        service = self._container.get_services(self._EXPORTER_SERVICE_NAME).get(
            self._EXPORTER_SERVICE_NAME
        )
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
        # `self._container.replan()` does not stop services that have been disabled
        # Use `restart()` and `stop()` instead
        if enabled:
            self._container.restart(self._SERVICE_NAME)
        else:
            self._container.stop(self._SERVICE_NAME)

    def update_mysql_router_exporter_service(
        self,
        *,
        enabled: bool,
        config: "relations.cos.ExporterConfig" = None,
        tls: bool = None,
        key_filename: str = None,
        certificate_filename: str = None,
        certificate_authority_filename: str = None,
    ) -> None:
        super().update_mysql_router_exporter_service(
            enabled=enabled,
            config=config,
            tls=tls,
            key_filename=key_filename,
            certificate_filename=certificate_filename,
            certificate_authority_filename=certificate_authority_filename,
        )

        if enabled:
            startup = ops.pebble.ServiceStartup.ENABLED.value

            environment = {
                "MYSQLROUTER_EXPORTER_USER": config.username,
                "MYSQLROUTER_EXPORTER_PASS": config.password,
                "MYSQLROUTER_EXPORTER_URL": config.url,
                "MYSQLROUTER_EXPORTER_SERVICE_NAME": self._unit_name.replace("/", "-"),
            }
            if tls:
                environment.update(
                    {
                        "MYSQLROUTER_TLS_CACERT_PATH": certificate_authority_filename,
                        "MYSQLROUTER_TLS_CERT_PATH": certificate_filename,
                        "MYSQLROUTER_TLS_KEY_PATH": key_filename,
                    }
                )
        else:
            startup = ops.pebble.ServiceStartup.DISABLED.value
            environment = {}

        layer = ops.pebble.Layer(
            {
                "services": {
                    self._EXPORTER_SERVICE_NAME: {
                        "override": "replace",
                        "summary": "MySQL Router Exporter",
                        "command": "/start-mysql-router-exporter.sh",
                        "startup": startup,
                        "user": _UNIX_USERNAME,
                        "group": _UNIX_USERNAME,
                        "environment": environment,
                    },
                },
            }
        )
        self._container.add_layer(self._EXPORTER_SERVICE_NAME, layer, combine=True)
        # `self._container.replan()` does not stop services that have been disabled
        # Explicitly use `stop()` instead
        if enabled:
            for attempt in tenacity.Retrying(
                retry=tenacity.retry_if_exception_type(ops.pebble.ChangeError),
                reraise=True,
                stop=tenacity.stop_after_attempt(3),
                wait=tenacity.wait_fixed(65),
            ):
                with attempt:
                    self._container.replan()
        else:
            self._container.stop(self._EXPORTER_SERVICE_NAME)

    def upgrade(self, unit: ops.Unit) -> None:
        raise Exception("Not supported on Kubernetes")

    def update_logrotate_executor_service(self, *, enabled: bool) -> None:
        """Update and restart log rotate executor service.

        Args:
            enabled: Whether log rotate executor service is enabled
        """
        startup = (
            ops.pebble.ServiceStartup.ENABLED.value
            if enabled
            else ops.pebble.ServiceStartup.DISABLED.value
        )
        layer = ops.pebble.Layer(
            {
                "services": {
                    self._LOGROTATE_EXECUTOR_SERVICE_NAME: {
                        "override": "replace",
                        "summary": "Logrotate executor",
                        "command": "python3 /logrotate_executor.py",
                        "startup": startup,
                        "user": _UNIX_USERNAME,
                        "group": _UNIX_USERNAME,
                    },
                },
            }
        )
        self._container.add_layer(self._LOGROTATE_EXECUTOR_SERVICE_NAME, layer, combine=True)
        # `self._container.replan()` does not stop services that have been disabled
        # Use `restart()` and `stop()` instead
        if enabled:
            self._container.restart(self._LOGROTATE_EXECUTOR_SERVICE_NAME)
        else:
            self._container.stop(self._LOGROTATE_EXECUTOR_SERVICE_NAME)

    # TODO python3.10 min version: Use `list` instead of `typing.List`
    def _run_command(
        self, command: typing.List[str], *, timeout: typing.Optional[int], input: str = None
    ) -> str:
        try:
            process = self._container.exec(
                command, user=_UNIX_USERNAME, group=_UNIX_USERNAME, timeout=timeout, stdin=input
            )
            output, _ = process.wait_output()
        except ops.pebble.ExecError as e:
            raise container.CalledProcessError(
                returncode=e.exit_code, cmd=e.command, output=e.stdout, stderr=e.stderr
            )
        return output

    def path(self, *args) -> _Path:
        return _Path(*args, container_=self._container)
