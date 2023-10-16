# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""logrotate cron configuration"""

import logging
import pathlib

import jinja2

import container
import logrotate

logger = logging.getLogger(__name__)

SYSTEM_USER = "mysql"
ROOT_USER = "root"


class LogRotate(logrotate.LogRotate):
    """logrotate cron configuration"""

    def __init__(self, *, container_: container.Container):
        super().__init__(container_=container_)
        self._logrotate_config = self._container.path("/etc/logrotate.d/flush_mysqlrouter_logs")
        self._logrotate_dispatcher = self._container.path("/logrotate_dispatcher.py")

    def enable(self) -> None:
        logger.debug("Creating logrotate config file")

        template = jinja2.Template(pathlib.Path("templates/logrotate.j2").read_text())

        log_file_path = self._container.path("/var/log/mysqlrouter/mysqlrouter.log")
        rendered = template.render(
            log_file_path=str(log_file_path),
            system_user=SYSTEM_USER,
        )
        self._logrotate_config.write_text(rendered, user=ROOT_USER, group=ROOT_USER)

        logger.debug("Created logrotate config file")
        logger.debug("Copying log rotate dispatcher to workload container")

        self._logrotate_dispatcher.write_text(
            pathlib.Path("scripts/logrotate_dispatcher.py").read_text()
        )

        logger.debug("Copied log rotate dispatcher to workload container")
        logger.debug("Starting the logrotate dispatcher service")
        self._container.update_logrotate_dispatcher_service(enabled=True)
        logger.debug("Started the logrotate dispatcher service")

    def disable(self) -> None:
        logger.debug("Stopping the logrotate dispatcher service")
        self._container.update_logrotate_dispatcher_service(enabled=False)
        logger.debug("Stopped the logrotate dispatcher service")
        logger.debug("Removing logrotate config and dispatcher files")
        self._logrotate_config.unlink()
        self._logrotate_dispatcher.unlink()
        logger.debug("Removed logrotate config and dispatcher files")
