# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the database requires relation."""

import base64
import logging
import re
import socket
from string import Template
from typing import List, Optional

from charms.tls_certificates_interface.v1.tls_certificates import (
    CertificateAvailableEvent,
    CertificateExpiringEvent,
    TLSCertificatesRequiresV1,
    generate_csr,
    generate_private_key,
)
from ops.charm import ActionEvent, CharmBase
from ops.framework import Object
from ops.pebble import Layer, PathError

from constants import (
    MYSQL_ROUTER_CONTAINER_NAME,
    MYSQL_ROUTER_SERVICE_NAME,
    MYSQL_ROUTER_USER_NAME,
    ROUTER_CONFIG_DIRECTORY,
    TLS_RELATION,
    TLS_SSL_CERT_FILE,
    TLS_SSL_CONFIG_FILE,
    TLS_SSL_KEY_FILE,
    UNIT_BOOTSTRAPPED,
)

SCOPE = "unit"

logger = logging.getLogger(__name__)


class MySQLRouterTLS(Object):
    """TLS Management class for MySQL Router Operator."""

    def __init__(self, charm: CharmBase):
        super().__init__(charm, "mysql-router-tls")
        self.charm = charm
        self.certs = TLSCertificatesRequiresV1(self.charm, TLS_RELATION)

        self.framework.observe(
            self.charm.on.set_tls_private_key_action,
            self._on_set_tls_private_key,
        )
        self.framework.observe(
            self.charm.on[TLS_RELATION].relation_joined, self._on_tls_relation_joined
        )
        self.framework.observe(
            self.charm.on[TLS_RELATION].relation_broken, self._on_tls_relation_broken
        )

        self.framework.observe(self.certs.on.certificate_available, self._on_certificate_available)
        self.framework.observe(self.certs.on.certificate_expiring, self._on_certificate_expiring)

    @property
    def container(self):
        """Map to the MySQL Router container."""
        return self.charm.unit.get_container(MYSQL_ROUTER_CONTAINER_NAME)

    @property
    def hostname(self):
        """Return the hostname of the MySQL Router container."""
        return socket.gethostname()

    # Handlers

    def _on_set_tls_private_key(self, event: ActionEvent) -> None:
        """Action for setting a TLS private key."""
        if not self.charm.model.get_relation(TLS_RELATION):
            event.fail("No TLS relation available.")
            return
        try:
            self._request_certificate(event.params.get("internal-key", None))
        except Exception as e:
            event.fail(f"Failed to request certificate: {e}")

    def _on_tls_relation_joined(self, _) -> None:
        """Request certificate when TLS relation joined."""
        self._request_certificate(None)

    def _on_tls_relation_broken(self, _) -> None:
        """Disable TLS when TLS relation broken."""
        for secret in ["cert", "chain", "ca"]:
            try:
                self.charm.set_secret(SCOPE, secret, None)
            except KeyError:
                # ignore key error for unit teardown
                pass
        # unset tls flag
        self.charm.unit_peer_data.pop("tls")
        self._unset_tls()

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Enable TLS when TLS certificate available."""
        if self.charm.unit_peer_data.get(UNIT_BOOTSTRAPPED) != "true":
            logger.debug("Unit not bootstrapped, defer TLS setup")
            event.defer()
            return

        if (
            event.certificate_signing_request.strip()
            != self.charm.get_secret(SCOPE, "csr").strip()
        ):
            logger.warning("Unknown certificate received. Ignoring.")
            return

        if self.charm.unit_peer_data.get("tls") == "enabled":
            logger.debug("TLS is already enabled.")
            return

        self.charm.set_secret(
            SCOPE, "chain", "\n".join(event.chain) if event.chain is not None else None
        )
        self.charm.set_secret(SCOPE, "cert", event.certificate)
        self.charm.set_secret(SCOPE, "ca", event.ca)

        # set member-state to avoid unwanted health-check actions
        self.charm.unit_peer_data.update({"tls": "enabled"})
        self._set_tls()

    def _on_certificate_expiring(self, event: CertificateExpiringEvent) -> None:
        """Request the new certificate when old certificate is expiring."""
        if event.certificate != self.charm.get_secret(SCOPE, "cert"):
            logger.error("An unknown certificate expiring.")
            return

        key = self.charm.get_secret(SCOPE, "key").encode("utf-8")
        old_csr = self.charm.get_secret(SCOPE, "csr").encode("utf-8")
        new_csr = generate_csr(
            private_key=key,
            subject=self.charm.unit_hostname,
            organization=self.charm.app.name,
            sans=self._get_sans(),
        )
        self.certs.request_certificate_renewal(
            old_certificate_signing_request=old_csr,
            new_certificate_signing_request=new_csr,
        )

    # Helpers
    def _request_certificate(self, internal_key: Optional[str] = None) -> None:
        """Request a certificate from the TLS relation."""
        if internal_key:
            key = self._parse_tls_file(internal_key)
        else:
            key = generate_private_key()

        csr = generate_csr(
            private_key=key,
            subject=self.hostname,
            organization=self.charm.app.name,
            sans=self._get_sans(),
        )

        # store secrets
        self.charm.set_secret(SCOPE, "key", key.decode("utf-8"))
        self.charm.set_secret(SCOPE, "csr", csr.decode("utf-8"))
        # set control flag
        self.charm.unit_peer_data.update({"tls": "requested"})
        self.certs.request_certificate_creation(certificate_signing_request=csr)

    def _get_sans(self) -> List[str]:
        """Create a list of DNS names for a unit.

        Returns:
            A list representing the hostnames of the unit.
        """
        return [
            self.hostname,
            socket.getfqdn(),
            str(self.charm.model.get_binding(self.charm.peers).network.bind_address),
        ]

    @staticmethod
    def _parse_tls_file(raw_content: str) -> bytes:
        """Parse TLS files from both plain text or base64 format."""
        if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", raw_content):
            return re.sub(
                r"(-+(BEGIN|END) [A-Z ]+-+)",
                "\n\\1\n",
                raw_content,
            ).encode("utf-8")
        return base64.b64decode(raw_content)

    def _remove_file(self, path: str) -> None:
        """Remove a file from container workload.

        Args:
            path: Full filesystem path to remove
        """
        try:
            self.container.remove_path(path)
        except PathError:
            # ignore file not found
            pass

    def _set_tls(self) -> None:
        """Enable TLS."""
        self._create_tls_config_file()
        self._push_tls_files_to_workload()
        # add tls layer merging with mysql-router layer
        self.container.add_layer(MYSQL_ROUTER_SERVICE_NAME, self._tls_layer(), combine=True)
        self.container.replan()
        logger.info("TLS enabled.")

    def _unset_tls(self) -> None:
        """Disable TLS."""
        for file in [TLS_SSL_KEY_FILE, TLS_SSL_CERT_FILE, TLS_SSL_CONFIG_FILE]:
            self._remove_file(f"{ROUTER_CONFIG_DIRECTORY}/{file}")
        # remove tls layer overriding with original layer
        self.container.add_layer(
            MYSQL_ROUTER_SERVICE_NAME, self.charm.mysql_router_layer, combine=True
        )
        self.container.replan()
        logger.info("TLS disabled.")

    def _write_content_to_file(
        self,
        path: str,
        content: str,
        owner: str,
        group: str,
        permission: int = 0o640,
    ) -> None:
        """Write content to file.

        Args:
            path: filesystem full path (with filename)
            content: string content to write
            owner: file owner
            group: file group
            permission: file permission
        """
        self.container.push(path, content, permissions=permission, user=owner, group=group)

    def _create_tls_config_file(self) -> None:
        """Render TLS template directly to file.

        Render and write TLS enabling config file from template.
        """
        with open("templates/tls.cnf", "r") as template_file:
            template = Template(template_file.read())
            config_string = template.substitute(
                tls_ssl_key_file=f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_KEY_FILE}",
                tls_ssl_cert_file=f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_CERT_FILE}",
            )

        self._write_content_to_file(
            f"{ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_CONFIG_FILE}",
            config_string,
            owner=MYSQL_ROUTER_USER_NAME,
            group=MYSQL_ROUTER_USER_NAME,
            permission=0o600,
        )

    def _push_tls_files_to_workload(self) -> None:
        """Push TLS files to unit."""
        tls_file = {"key": TLS_SSL_KEY_FILE, "cert": TLS_SSL_CERT_FILE}
        for key, value in tls_file.items():
            self._write_content_to_file(
                f"{ROUTER_CONFIG_DIRECTORY}/{value}",
                self.charm.get_secret(SCOPE, key),
                owner=MYSQL_ROUTER_USER_NAME,
                group=MYSQL_ROUTER_USER_NAME,
                permission=0o600,
            )

    @staticmethod
    def _tls_layer() -> Layer:
        """Create a Pebble layer for TLS.

        Returns:
            A Pebble layer object.
        """
        return Layer(
            {
                "services": {
                    MYSQL_ROUTER_SERVICE_NAME: {
                        "override": "merge",
                        "command": f"/run.sh mysqlrouter --extra-config {ROUTER_CONFIG_DIRECTORY}/{TLS_SSL_CONFIG_FILE}",
                    },
                },
            },
        )
