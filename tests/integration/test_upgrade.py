# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import os
import pathlib
import shutil
import time
import typing
import zipfile
from pathlib import Path

import pytest
import tenacity
import yaml
from pytest_operator.plugin import OpsTest

from .helpers import (
    APPLICATION_DEFAULT_APP_NAME,
    MYSQL_DEFAULT_APP_NAME,
    MYSQL_ROUTER_DEFAULT_APP_NAME,
    ensure_all_units_continuous_writes_incrementing,
    get_juju_status,
    get_leader_unit,
    get_workload_version,
)
from .juju_ import run_action

logger = logging.getLogger(__name__)

TIMEOUT = 20 * 60
UPGRADE_TIMEOUT = 15 * 60
SMALL_TIMEOUT = 5 * 60

MYSQL_APP_NAME = MYSQL_DEFAULT_APP_NAME
MYSQL_ROUTER_APP_NAME = MYSQL_ROUTER_DEFAULT_APP_NAME
APPLICATION_APP_NAME = APPLICATION_DEFAULT_APP_NAME

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_deploy_edge(ops_test: OpsTest) -> None:
    """Simple test to ensure that mysql, mysqlrouter and application charms deploy."""
    logger.info("Deploying all applications")

    await asyncio.gather(
        ops_test.model.deploy(
            MYSQL_APP_NAME,
            channel="8.0/edge",
            application_name=MYSQL_APP_NAME,
            config={"profile": "testing"},
            base="ubuntu@22.04",
            num_units=1,
            trust=True,  # Necessary after a6f1f01: Fix/endpoints as k8s services (#142)
        ),
        ops_test.model.deploy(
            MYSQL_ROUTER_APP_NAME,
            channel="8.0/edge",
            application_name=MYSQL_ROUTER_APP_NAME,
            base="ubuntu@22.04",
            num_units=3,
            trust=True,
        ),
        ops_test.model.deploy(
            APPLICATION_APP_NAME,
            channel="latest/edge",
            application_name=APPLICATION_APP_NAME,
            base="ubuntu@22.04",
            num_units=1,
        ),
    )

    logger.info(f"Relating {MYSQL_ROUTER_APP_NAME} to {MYSQL_APP_NAME} and {APPLICATION_APP_NAME}")

    await ops_test.model.relate(
        f"{MYSQL_ROUTER_APP_NAME}:backend-database", f"{MYSQL_APP_NAME}:database"
    )
    await ops_test.model.relate(
        f"{APPLICATION_APP_NAME}:database", f"{MYSQL_ROUTER_APP_NAME}:database"
    )

    logger.info("Waiting for applications to become active")
    await ops_test.model.wait_for_idle(
        [MYSQL_APP_NAME, MYSQL_ROUTER_APP_NAME, APPLICATION_APP_NAME],
        status="active",
        timeout=TIMEOUT,
    )


@pytest.mark.abort_on_fail
async def test_upgrade_from_edge(ops_test: OpsTest, charm) -> None:
    """Upgrade mysqlrouter while ensuring continuous writes incrementing."""
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_router_application = ops_test.model.applications[MYSQL_ROUTER_APP_NAME]
    mysql_router_unit = mysql_router_application.units[0]

    old_workload_version = await get_workload_version(ops_test, mysql_router_unit.name)

    global temporary_charm
    temporary_charm = "./upgrade.charm"
    shutil.copy(charm, temporary_charm)

    logger.info("Update workload version and snap revision in the charm")
    create_valid_upgrade_charm(temporary_charm)

    logger.info("Refresh the charm")
    await mysql_router_application.refresh(path=temporary_charm)

    logger.info("Wait for the first unit to be refreshed and the app to move to blocked status")
    await ops_test.model.block_until(
        lambda: mysql_router_application.status == "blocked", timeout=TIMEOUT
    )
    assert (
        "resume-upgrade" in mysql_router_application.status_message
    ), "mysql router application status not indicating that user should resume upgrade"

    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(SMALL_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            assert "+testupgrade" in get_juju_status(
                ops_test.model.name
            ), "None of the units are upgraded"

    mysql_router_leader_unit = await get_leader_unit(ops_test, MYSQL_ROUTER_APP_NAME)

    logger.info("Running resume-upgrade on the mysql router leader unit")
    await run_action(mysql_router_leader_unit, "resume-upgrade")

    logger.info("Waiting for upgrade to complete on all units")
    await ops_test.model.wait_for_idle(
        [MYSQL_ROUTER_APP_NAME],
        status="active",
        idle_period=30,
        timeout=UPGRADE_TIMEOUT,
    )

    workload_version_file = pathlib.Path("workload_version")
    repo_workload_version = workload_version_file.read_text().strip()

    for unit in mysql_router_application.units:
        workload_version = await get_workload_version(ops_test, unit.name)
        assert workload_version == f"{repo_workload_version}+testupgrade"
        assert old_workload_version != workload_version

    await ensure_all_units_continuous_writes_incrementing(ops_test)

    await ops_test.model.wait_for_idle(
        [MYSQL_ROUTER_APP_NAME], idle_period=30, status="active", timeout=TIMEOUT
    )


@pytest.mark.abort_on_fail
async def test_fail_and_rollback(ops_test: OpsTest, charm, continuous_writes) -> None:
    """Upgrade to an invalid version and test rollback.

    Relies on the charm built in the previous test (test_upgrade_from_edge).
    """
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_router_application = ops_test.model.applications[MYSQL_ROUTER_APP_NAME]

    fault_charm = "./faulty.charm"
    shutil.copy(charm, fault_charm)

    logger.info("Creating invalid upgrade charm")
    create_invalid_upgrade_charm(fault_charm)

    logger.info("Refreshing mysql router with an invalid charm")
    await mysql_router_application.refresh(path=fault_charm)

    logger.info("Wait for upgrade to fail")
    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(UPGRADE_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            assert "Upgrade incompatible" in get_juju_status(
                ops_test.model.name
            ), "mysql router application status not indicating faulty charm incompatible"

    logger.info("Ensure continuous writes while in failure state")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    logger.info("Re-refresh the charm")
    await mysql_router_application.refresh(path="./upgrade.charm")

    # sleep to ensure that active status from before re-refresh does not affect below check
    time.sleep(15)

    await ops_test.model.block_until(
        lambda: all(unit.workload_status == "active" for unit in mysql_router_application.units)
        and all(unit.agent_status == "idle" for unit in mysql_router_application.units)
    )

    logger.info("Running resume-upgrade on the mysql router leader unit")
    mysql_router_leader_unit = await get_leader_unit(ops_test, MYSQL_ROUTER_APP_NAME)
    await run_action(mysql_router_leader_unit, "resume-upgrade")

    logger.info("Wait for the charm to be rolled back")
    await ops_test.model.wait_for_idle(
        apps=[MYSQL_ROUTER_APP_NAME],
        status="active",
        timeout=TIMEOUT,
        idle_period=30,
    )

    workload_version_file = pathlib.Path("workload_version")
    repo_workload_version = workload_version_file.read_text().strip()

    for unit in mysql_router_application.units:
        charm_workload_version = await get_workload_version(ops_test, unit.name)
        assert charm_workload_version == f"{repo_workload_version}+testupgrade"

    await ops_test.model.wait_for_idle(
        apps=[MYSQL_ROUTER_APP_NAME], status="active", timeout=TIMEOUT
    )

    logger.info("Ensure continuous writes after rollback procedure")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    os.remove(fault_charm)
    os.remove(temporary_charm)


def create_valid_upgrade_charm(charm_file: typing.Union[str, pathlib.Path]) -> None:
    """Create a valid mysql router charm for upgrade."""
    workload_version_file = pathlib.Path("workload_version")
    workload_version = workload_version_file.read_text().strip()

    with zipfile.ZipFile(charm_file, mode="a") as charm_zip:
        charm_zip.writestr("workload_version", f"{workload_version}+testupgrade\n")


def create_invalid_upgrade_charm(charm_file: typing.Union[str, pathlib.Path]) -> None:
    """Create an invalid mysql router charm for upgrade."""
    workload_version_file = pathlib.Path("workload_version")
    old_workload_version = workload_version_file.read_text().strip()
    [major, minor, patch] = old_workload_version.split(".")

    with zipfile.ZipFile(charm_file, mode="a") as charm_zip:
        # an invalid charm version because the major workload_version is one less than the current workload_version
        charm_zip.writestr("workload_version", f"{int(major) - 1}.{minor}.{patch}+testrollback\n")
