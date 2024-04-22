# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import itertools
import json
import subprocess
import tempfile
from typing import Dict, List, Optional

import mysql.connector
import yaml
from juju.unit import Unit
from mysql.connector.errors import (
    DatabaseError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, retry, stop_after_attempt, wait_fixed

from .connector import MySQLConnector

SERVER_CONFIG_USERNAME = "serverconfig"
CONTAINER_NAME = "mysql-router"
LOGROTATE_EXECUTOR_SERVICE = "logrotate_executor"


async def execute_queries_on_unit(
    unit_address: str,
    username: str,
    password: str,
    queries: List[str],
    commit: bool = False,
) -> List:
    """Execute given MySQL queries on a unit.

    Args:
        unit_address: The public IP address of the unit to execute the queries on
        username: The MySQL username
        password: The MySQL password
        queries: A list of queries to execute
        commit: A keyword arg indicating whether there are any writes queries

    Returns:
        A list of rows that were potentially queried
    """
    connection = mysql.connector.connect(
        host=unit_address,
        user=username,
        password=password,
    )
    cursor = connection.cursor()

    for query in queries:
        cursor.execute(query)

    if commit:
        connection.commit()

    output = list(itertools.chain(*cursor.fetchall()))

    cursor.close()
    connection.close()

    return output


async def get_server_config_credentials(unit: Unit) -> Dict:
    """Helper to run an action to retrieve server config credentials.

    Args:
        unit: The juju unit on which to run the get-password action for server-config credentials

    Returns:
        A dictionary with the server config username and password
    """
    action = await unit.run_action(action_name="get-password", username=SERVER_CONFIG_USERNAME)
    result = await action.wait()

    return result.results


async def get_inserted_data_by_application(unit: Unit) -> str:
    """Helper to run an action to retrieve inserted data by the application.

    Args:
        unit: The juju unit on which to run the get-inserted-data action

    Returns:
        A string representing the inserted data
    """
    action = await unit.run_action("get-inserted-data")
    result = await action.wait()

    return result.results.get("data")


async def get_unit_address(ops_test: OpsTest, unit_name: str) -> str:
    """Get unit IP address.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit

    Returns:
        IP address of the unit
    """
    status = await ops_test.model.get_status()
    return status["applications"][unit_name.split("/")[0]].units[unit_name]["address"]


async def scale_application(
    ops_test: OpsTest, application_name: str, desired_count: int, wait: bool = True
) -> None:
    """Scale a given application to the desired unit count.

    Args:
        ops_test: The ops test framework
        application_name: The name of the application
        desired_count: The number of units to scale to
        wait: Boolean indicating whether to wait until units
            reach desired count
    """
    await ops_test.model.applications[application_name].scale(desired_count)

    if desired_count > 0 and wait:
        await ops_test.model.wait_for_idle(
            apps=[application_name],
            status="active",
            timeout=(15 * 60),
            wait_for_exact_units=desired_count,
        )


async def delete_file_or_directory_in_unit(
    ops_test: OpsTest, unit_name: str, path: str, container_name: str = CONTAINER_NAME
) -> bool:
    """Delete a file in the provided unit.

    Args:
        ops_test: The ops test framework
        unit_name: The name unit on which to delete the file from
        container_name: The name of the container where the file or directory is
        path: The path of file or directory to delete

    Returns:
        boolean indicating success
    """
    if path.strip() in ["/", "."]:
        return

    return_code, _, _ = await ops_test.juju(
        "ssh",
        "--container",
        container_name,
        unit_name,
        "find",
        path,
        "-maxdepth",
        "1",
        "-delete",
    )


async def get_process_pid(
    ops_test: OpsTest, unit_name: str, container_name: str, process: str
) -> int:
    """Return the pid of a process running in a given unit.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit
        container_name: The name of the container to get the process pid from
        process: The process name to search for
    Returns:
        A integer for the process id
    """
    try:
        _, raw_pid, _ = await ops_test.juju("ssh", unit_name, "pgrep", "-x", process)
        pid = int(raw_pid.strip())

        return pid
    except Exception:
        return None


async def write_content_to_file_in_unit(
    ops_test: OpsTest, unit: Unit, path: str, content: str, container_name: str = CONTAINER_NAME
) -> None:
    """Write content to the file in the provided unit.

    Args:
        ops_test: The ops test framework
        unit: THe unit in which to write to file in
        path: The path at which to write the content to
        content: The content to write to the file
        container_name: The container where to write the file
    """
    pod_name = unit.name.replace("/", "-")

    with tempfile.NamedTemporaryFile(mode="w") as temp_file:
        temp_file.write(content)
        temp_file.flush()

        subprocess.run(
            [
                "kubectl",
                "cp",
                "-n",
                ops_test.model.info.name,
                "-c",
                container_name,
                temp_file.name,
                f"{pod_name}:{path}",
            ],
            check=True,
        )


async def read_contents_from_file_in_unit(
    ops_test: OpsTest, unit: Unit, path: str, container_name: str = CONTAINER_NAME
) -> str:
    """Read contents from file in the provided unit.

    Args:
        ops_test: The ops test framework
        unit: The unit in which to read file from
        path: The path from which to read content from
        container_name: The container where the file exists

    Returns:
        the contents of the file
    """
    pod_name = unit.name.replace("/", "-")

    with tempfile.NamedTemporaryFile(mode="r+") as temp_file:
        subprocess.run(
            [
                "kubectl",
                "cp",
                "-n",
                ops_test.model.info.name,
                "-c",
                container_name,
                f"{pod_name}:{path}",
                temp_file.name,
            ],
            check=True,
        )

        temp_file.seek(0)

        contents = ""
        for line in temp_file:
            contents += line
            contents += "\n"

    return contents


async def ls_la_in_unit(
    ops_test: OpsTest, unit_name: str, directory: str, container_name: str = CONTAINER_NAME
) -> list[str]:
    """Returns the output of ls -la in unit.

    Args:
        ops_test: The ops test framework
        unit_name: The name of unit in which to run ls -la
        path: The path from which to run ls -la
        container_name: The container where to run ls -la

    Returns:
        a list of files returned by ls -la
    """
    return_code, output, _ = await ops_test.juju(
        "ssh", "--container", container_name, unit_name, "ls", "-la", directory
    )
    assert return_code == 0

    ls_output = output.split("\n")[1:]

    return [
        line.strip("\r")
        for line in ls_output
        if len(line.strip()) > 0 and line.split()[-1] not in [".", ".."]
    ]


async def stop_running_log_rotate_executor(ops_test: OpsTest, unit_name: str):
    """Stop running the log rotate executor script.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to be tested
    """
    # send KILL signal to log rotate executor, which trigger shutdown process
    await ops_test.juju(
        "ssh",
        "--container",
        CONTAINER_NAME,
        unit_name,
        "pebble",
        "stop",
        LOGROTATE_EXECUTOR_SERVICE,
    )


async def stop_running_flush_mysqlrouter_job(ops_test: OpsTest, unit_name: str) -> None:
    """Stop running any logrotate jobs that may have been triggered by cron.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to be tested
    """
    # send KILL signal to log rotate process, which trigger shutdown process
    await ops_test.juju(
        "ssh",
        "--container",
        CONTAINER_NAME,
        unit_name,
        "pkill",
        "-9",
        "-f",
        "logrotate -f /etc/logrotate.d/flush_mysqlrouter_logs",
    )

    # hold execution until process is stopped
    for attempt in Retrying(reraise=True, stop=stop_after_attempt(45), wait=wait_fixed(2)):
        with attempt:
            if await get_process_pid(ops_test, unit_name, CONTAINER_NAME, "logrotate"):
                raise Exception("Failed to stop the flush_mysql_logs logrotate process.")


async def rotate_mysqlrouter_logs(ops_test: OpsTest, unit_name: str) -> None:
    """Dispatch the custom event to run logrotate.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to be tested
    """
    pod_label = unit_name.replace("/", "-")

    subprocess.run(
        [
            "kubectl",
            "exec",
            "-n",
            ops_test.model.info.name,
            "-it",
            pod_label,
            "--container",
            CONTAINER_NAME,
            "--",
            "su",
            "-",
            "mysql",
            "-c",
            "logrotate -f -s /tmp/logrotate.status /etc/logrotate.d/flush_mysqlrouter_logs",
        ],
        check=True,
    )


@retry(stop=stop_after_attempt(8), wait=wait_fixed(15), reraise=True)
def is_connection_possible(credentials: Dict, **extra_opts) -> bool:
    """Test a connection to a MySQL server.

    Args:
        credentials: A dictionary with the credentials to test
        extra_opts: extra options for mysql connection
    """
    config = {
        "user": credentials["username"],
        "password": credentials["password"],
        "host": credentials["host"],
        "raise_on_warnings": False,
        "connection_timeout": 10,
        **extra_opts,
    }
    try:
        with MySQLConnector(config) as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone()[0] == 1
    except (DatabaseError, InterfaceError, OperationalError, ProgrammingError):
        # Errors raised when the connection is not possible
        return False


async def get_tls_ca(
    ops_test: OpsTest,
    unit_name: str,
) -> str:
    """Returns the TLS CA used by the unit.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit

    Returns:
        TLS CA or an empty string if there is no CA.
    """
    raw_data = (await ops_test.juju("show-unit", unit_name))[1]
    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")
    data = yaml.safe_load(raw_data)
    # Filter the data based on the relation name.
    relation_data = [
        v for v in data[unit_name]["relation-info"] if v["endpoint"] == "certificates"
    ]
    if len(relation_data) == 0:
        return ""
    return json.loads(relation_data[0]["application-data"]["certificates"])[0].get("ca")


async def get_tls_certificate_issuer(
    ops_test: OpsTest,
    unit_name: str,
    socket: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> str:
    connect_args = f"-unix {socket}" if socket else f"-connect {host}:{port}"
    get_tls_certificate_issuer_commands = [
        "ssh",
        "--container",
        CONTAINER_NAME,
        unit_name,
        f"openssl s_client -showcerts -starttls mysql {connect_args} < /dev/null | openssl x509 -text | grep Issuer",
    ]
    return_code, issuer, _ = await ops_test.juju(*get_tls_certificate_issuer_commands)
    assert return_code == 0, f"failed to get TLS certificate issuer on {unit_name=}"
    return issuer
