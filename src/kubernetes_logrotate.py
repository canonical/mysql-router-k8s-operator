# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""logrotate implementation for k8s"""

import logging
import pathlib

import container
import logrotate

logger = logging.getLogger(__name__)


class LogRotate(logrotate.LogRotate):
    """logrotate implementation for k8s"""

    _SYSTEM_USER = "mysql"

    def __init__(self, *, container_: container.Container):
        super().__init__(container_=container_)
        self._logrotate_executor = self._container.path("/logrotate_executor.py")

    def enable(self) -> None:
        super().enable()

        logger.debug("Copying log rotate executor script to workload container")
        self._logrotate_executor.write_text(
            pathlib.Path("scripts/logrotate_executor.py").read_text()
        )
        logger.debug("Copied log rotate executor to workload container")

        logger.debug("Starting the logrotate executor service")
        self._container.update_logrotate_executor_service(enabled=True)
        logger.debug("Started the logrotate executor service")

    def disable(self) -> None:
        logger.debug("Stopping the logrotate executor service")
        self._container.update_logrotate_executor_service(enabled=False)
        logger.debug("Stopped the logrotate executor service")

        logger.debug("Removing logrotate config and executor files")
        super().disable()
        self._logrotate_executor.unlink()
        logger.debug("Removed logrotate config and executor files")
