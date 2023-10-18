#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from .helpers import (
    delete_file_or_directory_in_unit,
    ls_la_in_unit,
    read_contents_from_file_in_unit,
    rotate_mysqlrouter_logs,
    stop_running_flush_mysqlrouter_job,
    stop_running_log_rotate_dispatcher,
    write_content_to_file_in_unit,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_ROUTER_APP_NAME = "mysql-router-k8s"
APPLICATION_APP_NAME = "mysql-test-app"
SLOW_TIMEOUT = 15 * 60
MODEL_CONFIG = {"logging-config": "<root>=INFO;unit=DEBUG"}


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_log_rotation(ops_test: OpsTest):
    """Test log rotation."""
    # Build and deploy applications
    mysqlrouter_charm = await ops_test.build_charm(".")
    await ops_test.model.set_config(MODEL_CONFIG)

    mysqlrouter_resources = {
        "mysql-router-image": METADATA["resources"]["mysql-router-image"]["upstream-source"]
    }

    logger.info("Deploying mysql, mysqlrouter and application")
    applications = await asyncio.gather(
        ops_test.model.deploy(
            MYSQL_APP_NAME,
            channel="8.0/edge",
            application_name=MYSQL_APP_NAME,
            config={"profile": "testing"},
            series="jammy",
            num_units=3,
            trust=True,  # Necessary after a6f1f01: Fix/endpoints as k8s services (#142)
        ),
        ops_test.model.deploy(
            mysqlrouter_charm,
            application_name=MYSQL_ROUTER_APP_NAME,
            series="jammy",
            resources=mysqlrouter_resources,
            num_units=1,
            trust=True,
        ),
        ops_test.model.deploy(
            APPLICATION_APP_NAME,
            channel="latest/edge",
            application_name=APPLICATION_APP_NAME,
            series="jammy",
            num_units=1,
        ),
    )

    mysql_app, mysql_router_app, application_app = applications
    unit = mysql_router_app.units[0]

    async with ops_test.fast_forward():
        logger.info("Waiting for mysqlrouter to be in BlockedStatus")
        await ops_test.model.block_until(
            lambda: ops_test.model.applications[MYSQL_ROUTER_APP_NAME].status == "blocked",
            timeout=SLOW_TIMEOUT,
        )

        logger.info("Relating mysql, mysqlrouter and application")
        # Relate the database with mysqlrouter
        await ops_test.model.relate(
            f"{MYSQL_ROUTER_APP_NAME}:backend-database", f"{MYSQL_APP_NAME}:database"
        )
        # Relate mysqlrouter with application next
        await ops_test.model.relate(
            f"{APPLICATION_APP_NAME}:database", f"{MYSQL_ROUTER_APP_NAME}:database"
        )

        await asyncio.gather(
            ops_test.model.block_until(lambda: mysql_app.status == "active", timeout=SLOW_TIMEOUT),
            ops_test.model.block_until(
                lambda: mysql_router_app.status == "active", timeout=SLOW_TIMEOUT
            ),
            ops_test.model.block_until(
                lambda: application_app.status == "active", timeout=SLOW_TIMEOUT
            ),
        )

    logger.info("Stopping the logrotate dispatcher pebble service")
    await stop_running_log_rotate_dispatcher(ops_test, unit.name)

    logger.info("Stopping any running logrotate jobs")
    await stop_running_flush_mysqlrouter_job(ops_test, unit.name)

    logger.info("Removing existing archive directory")
    await delete_file_or_directory_in_unit(
        ops_test,
        unit.name,
        "/var/log/mysqlrouter/archive_mysqlrouter/",
    )

    logger.info("Writing some data mysqlrouter log file")
    log_path = "/var/log/mysqlrouter/mysqlrouter.log"
    await write_content_to_file_in_unit(ops_test, unit, log_path, "test mysqlrouter content\n")

    logger.info("Ensuring only log files exist")
    ls_la_output = await ls_la_in_unit(ops_test, unit.name, "/var/log/mysqlrouter/")

    assert len(ls_la_output) == 1, f"❌ files other than log files exist {ls_la_output}"
    directories = [line.split()[-1] for line in ls_la_output]
    assert directories == [
        "mysqlrouter.log"
    ], f"❌ file other than logs files exist: {ls_la_output}"

    logger.info("Executing logrotate")
    await rotate_mysqlrouter_logs(ops_test, unit.name)

    logger.info("Ensuring log files and archive directories exist")
    ls_la_output = await ls_la_in_unit(ops_test, unit.name, "/var/log/mysqlrouter/")

    assert (
        len(ls_la_output) == 2
    ), f"❌ unexpected files/directories in log directory: {ls_la_output}"
    directories = [line.split()[-1] for line in ls_la_output]
    assert sorted(directories) == sorted(
        ["mysqlrouter.log", "archive_mysqlrouter"]
    ), f"❌ unexpected files/directories in log directory: {ls_la_output}"

    logger.info("Ensuring log files was rotated")
    file_contents = await read_contents_from_file_in_unit(
        ops_test, unit, "/var/log/mysqlrouter/mysqlrouter.log"
    )
    assert (
        "test mysqlrouter content" not in file_contents
    ), "❌ log file mysqlrouter.log not rotated"

    ls_la_output = await ls_la_in_unit(
        ops_test,
        unit.name,
        "/var/log/mysqlrouter/archive_mysqlrouter/",
    )
    assert len(ls_la_output) == 1, f"❌ more than 1 file in archive directory: {ls_la_output}"

    filename = ls_la_output[0].split()[-1]
    file_contents = await read_contents_from_file_in_unit(
        ops_test,
        unit,
        f"/var/log/mysqlrouter/archive_mysqlrouter/{filename}",
    )
    assert "test mysqlrouter content" in file_contents, "❌ log file mysqlrouter.log not rotated"
