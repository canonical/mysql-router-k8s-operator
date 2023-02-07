# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, patch

import lightkube
from ops.model import BlockedStatus, MaintenanceStatus
from ops.testing import Harness

from charm import MySQLRouterOperatorCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(MySQLRouterOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.peer_relation_id = self.harness.add_relation(
            "mysql-router-peers", "mysql-router-peers"
        )
        self.harness.add_relation_unit(self.peer_relation_id, "mysql-router-k8s/1")
        self.harness.begin()
        self.charm = self.harness.charm

    @patch("charm.Client", return_value=MagicMock())
    def test_on_peer_relation_created(self, _lightkube_client):
        self.charm.on.leader_elected.emit()

        self.assertEqual(_lightkube_client.return_value.apply.call_count, 2)

        self.assertTrue(isinstance(self.harness.model.unit.status, MaintenanceStatus))

    @patch("charm.Client", return_value=MagicMock())
    def test_on_peer_relation_created_delete_exception(self, _lightkube_client):
        response = MagicMock()
        response.json.return_value = {"status": "Bad Request", "code": 400}
        api_error = lightkube.ApiError(request=MagicMock(), response=response)
        _lightkube_client.return_value.apply.side_effect = api_error

        self.charm.on.leader_elected.emit()

        self.assertTrue(isinstance(self.harness.model.unit.status, BlockedStatus))

    @patch("charm.Client", return_value=MagicMock())
    def test_on_peer_relation_created_delete_nothing(self, _lightkube_client):
        response = MagicMock()
        response.json.return_value = {"status": "Not Found", "code": 404}
        api_error = lightkube.ApiError(request=MagicMock(), response=response)
        _lightkube_client.return_value.delete.side_effect = api_error

        self.charm.on.leader_elected.emit()

        self.assertTrue(isinstance(self.harness.model.unit.status, MaintenanceStatus))

    @patch("charm.Client", return_value=MagicMock())
    def test_on_leader_elected_create_exception(self, _lightkube_client):
        response = MagicMock()
        response.json.return_value = {"status": "Bad Request", "code": 400}
        api_error = lightkube.ApiError(request=MagicMock(), response=response)
        _lightkube_client.return_value.apply.side_effect = api_error

        self.charm.on.leader_elected.emit()

        self.assertTrue(isinstance(self.harness.model.unit.status, BlockedStatus))

    @patch("charm.Client", return_value=MagicMock())
    def test_on_leader_elected_create_existing_service(self, _lightkube_client):
        response = MagicMock()
        response.json.return_value = {"status": "Conflict", "code": 409}
        api_error = lightkube.ApiError(request=MagicMock(), response=response)
        _lightkube_client.return_value.create.side_effect = api_error

        self.charm.on.leader_elected.emit()

        self.assertTrue(isinstance(self.harness.model.unit.status, MaintenanceStatus))
