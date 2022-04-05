# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import unittest

from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness

from charm import MySQLRouterOperatorCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(MySQLRouterOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.add_relation("mysql-router", "mysql-router")
        self.maxDiff = None
        self.name = "mysqlrouter"
        self.test_config = {
            "port": 3306,
            "host": "localhost",
            "user": "root",
            "password": "password",
        }

    def test_mysqlrouter_pebble_ready(self):
        # Check the initial Pebble plan is empty
        initial_plan = self.harness.get_container_pebble_plan(self.name)
        self.assertEqual(initial_plan.to_yaml(), "{}\n")

        container = self.harness.model.unit.get_container(self.name)
        # Emit the PebbleReadyEvent carrying the mysqlrouter container
        self.harness.charm.on.mysqlrouter_pebble_ready.emit(container)

        self.harness.set_leader(True)

        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("Waiting for database relation")
        )

    def test_config_changed_with_database_relation(self):

        # Expected plan after updated config
        expected_plan = {
            "services": {
                "mysqlrouter": {
                    "override": "replace",
                    "summary": "mysqlrouter",
                    "command": "/run.sh",
                    "startup": "enabled",
                    "environment": {
                        "MYSQL_PORT": 3306,
                        "MYSQL_HOST": "localhost",
                        "MYSQL_USER": "root",
                        "MYSQL_PASSWORD": "password",
                    },
                }
            },
        }

        self.harness.set_leader(True)
        relation_id = self.harness.add_relation("database", "mysql")
        self.harness.add_relation_unit(relation_id, "mysql/0")
        self.harness.update_relation_data(
            relation_id, "mysql", {"mysql": json.dumps(self.test_config)}
        )
        self.harness._emit_relation_created("database", relation_id, "mysql")

        updated_plan = self.harness.get_container_pebble_plan("mysqlrouter").to_dict()
        self.assertEqual(expected_plan, updated_plan)

        # Check the service was started
        service = self.harness.model.unit.get_container("mysqlrouter").get_service("mysqlrouter")
        self.assertTrue(service.is_running())
        # Ensure we set an ActiveStatus with no message
        self.assertEqual(self.harness.model.unit.status, ActiveStatus())
