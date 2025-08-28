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
import tomli
import tomli_w
import yaml
from pytest_operator.plugin import OpsTest

from .helpers import (
    APPLICATION_DEFAULT_APP_NAME,
    MYSQL_DEFAULT_APP_NAME,
    MYSQL_ROUTER_DEFAULT_APP_NAME,
    ensure_all_units_continuous_writes_incrementing,
    get_leader_unit,
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
        ops_test.juju(
            "deploy",
            MYSQL_ROUTER_APP_NAME,
            "-n",
            3,
            "--channel",
            "8.0/edge/test-refresh-v3-8.0.42",  # TODO remove after refresh v3 merged
            "--trust",
            "--series",  # For juju 2 compatibility
            "jammy",
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

    logger.info("Refresh the charm")
    await mysql_router_application.refresh(path=charm)

    # Highest to lowest unit number
    refresh_order = sorted(
        mysql_router_application.units,
        key=lambda unit: int(unit.name.split("/")[1]),
        reverse=True,
    )

    logger.info("Wait for refresh to start")
    await ops_test.model.block_until(
        lambda: mysql_router_application.status == "blocked", timeout=3 * 60
    )
    assert "resume-refresh" in mysql_router_application.status_message, (
        "mysql router application status not indicating that user should resume refresh"
    )

    logger.info("Wait for first unit to restart")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            [MYSQL_ROUTER_APP_NAME],
            idle_period=30,
            timeout=5 * 60,
        )

    # Refresh will be incompatible on PR CI (not edge CI) since unreleased charm versions are
    # always marked as incompatible
    if (
        refresh_order[0].workload_status == "blocked"
        and "incompatible" in refresh_order[0].workload_status_message
    ):
        logger.info("Running force-refresh-start action with check-compatibility=false")
        await run_action(refresh_order[0], "force-refresh-start", **{"check-compatibility": False})

    logger.info("Wait for first unit to upgrade")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            [MYSQL_ROUTER_APP_NAME],
            idle_period=30,
            timeout=TIMEOUT,
        )

    mysql_router_leader_unit = await get_leader_unit(ops_test, MYSQL_ROUTER_APP_NAME)
    logger.info("Running resume-refresh on the mysql router leader unit")
    await run_action(
        mysql_router_leader_unit,
        "resume-refresh",
        # If leader is next to refresh, charm will be killed before action can succeed
        check_return_code=False,
    )

    logger.info("Waiting for upgrade to complete on all units")
    await ops_test.model.wait_for_idle(
        [MYSQL_ROUTER_APP_NAME],
        status="active",
        idle_period=30,
        timeout=UPGRADE_TIMEOUT,
    )

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

    # Highest to lowest unit number
    refresh_order = sorted(
        mysql_router_application.units,
        key=lambda unit: int(unit.name.split("/")[1]),
        reverse=True,
    )

    logger.info("Wait for refresh to block as incompatible")
    await ops_test.model.block_until(
        lambda: refresh_order[0].workload_status == "blocked", timeout=TIMEOUT
    )
    assert "incompatible" in refresh_order[0].workload_status_message, (
        "mysql router application status not indicating that refresh incompatible"
    )

    logger.info("Ensure continuous writes while in failure state")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    logger.info("Re-refresh the charm")
    await mysql_router_application.refresh(path=charm)

    # sleep to ensure that active status from before re-refresh does not affect below check
    time.sleep(15)

    await ops_test.model.block_until(
        lambda: all(unit.workload_status == "active" for unit in mysql_router_application.units)
        and all(unit.agent_status == "idle" for unit in mysql_router_application.units)
    )

    logger.info("Wait for blocked app status")
    await ops_test.model.block_until(
        lambda: mysql_router_application.status == "blocked", timeout=3 * 60
    )
    assert "resume-refresh" in mysql_router_application.status_message, (
        "mysql router application status not indicating that user should resume refresh"
    )

    logger.info("Wait for first unit to rollback")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            [MYSQL_ROUTER_APP_NAME],
            idle_period=30,
            timeout=TIMEOUT,
        )

    mysql_router_leader_unit = await get_leader_unit(ops_test, MYSQL_ROUTER_APP_NAME)
    logger.info("Running resume-refresh on the mysql router leader unit")
    await run_action(
        mysql_router_leader_unit,
        "resume-refresh",
        # If leader is next to refresh, charm will be killed before action can succeed
        check_return_code=False,
    )

    logger.info("Waiting for rollback to complete on all units")
    await ops_test.model.wait_for_idle(
        [MYSQL_ROUTER_APP_NAME],
        status="active",
        idle_period=30,
        timeout=UPGRADE_TIMEOUT,
    )

    logger.info("Ensure continuous writes after rollback procedure")
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    os.remove(fault_charm)


def create_invalid_upgrade_charm(charm_file: typing.Union[str, pathlib.Path]) -> None:
    """Create an invalid mysql router charm for upgrade."""
    with zipfile.ZipFile(charm_file, mode="r") as charm_zip:
        with zipfile.Path(charm_zip, "refresh_versions.toml").open("rb") as file:
            versions = tomli.load(file)

    versions["charm"] = "8.0/0.0.0"

    with zipfile.ZipFile(charm_file, mode="a") as charm_zip:
        # an invalid charm version because the major workload_version is one less than the current workload_version
        charm_zip.writestr("refresh_versions.toml", tomli_w.dumps(versions))
