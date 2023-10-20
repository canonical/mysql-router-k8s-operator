# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""logrotate implementation for k8s"""

import logging
import pathlib

import jinja2

import container
import logrotate

logger = logging.getLogger(__name__)

SYSTEM_USER = "mysql"
ROOT_USER = "root"


class LogRotate(logrotate.LogRotate):
    """logrotate implementation for k8s"""

    def __init__(self, *, container_: container.Container):
        super().__init__(container_=container_)
        self._logrotate_config = self._container.path("/etc/logrotate.d/flush_mysqlrouter_logs")
        self._logrotate_executor = self._container.path("/logrotate_executor.py")

    def enable(self) -> None:
        logger.debug("Creating logrotate config file")

        template = jinja2.Template(pathlib.Path("templates/logrotate.j2").read_text())

        log_file_path = self._container.path("/var/log/mysqlrouter/mysqlrouter.log")
        rendered = template.render(
            log_file_path=str(log_file_path),
            system_user=SYSTEM_USER,
        )
        self._logrotate_config.write_text(rendered)

        logger.debug("Created logrotate config file")
        logger.debug("Copying log rotate executor script to workload container")

        self._logrotate_executor.write_text(
            pathlib.Path("scripts/logrotate_executor.py").read_text()
        )

        logger.debug("Copied log rotate executor to workload container")
        logger.debug("Starting the logrotate executor service")
        self._container.update_logrotate_executor_service(enabled=True)
        logger.debug("Started the logrotate executro service")

    def disable(self) -> None:
        logger.debug("Stopping the logrotate executor service")
        self._container.update_logrotate_executor_service(enabled=False)
        logger.debug("Stopped the logrotate executor service")
        logger.debug("Removing logrotate config and executor files")
        self._logrotate_config.unlink()
        self._logrotate_executor.unlink()
        logger.debug("Removed logrotate config and executor files")
