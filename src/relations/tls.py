# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation to TLS certificate provider"""

import base64
import dataclasses
import inspect
import json
import logging
import re
import socket
import typing

import charms.tls_certificates_interface.v1.tls_certificates as tls_certificates
import ops

if typing.TYPE_CHECKING:
    import charm

_PEER_RELATION_ENDPOINT_NAME = "mysql-router-peers"
logger = logging.getLogger(__name__)


class _PeerUnitDatabag:
    """Peer relation unit databag"""

    private_key: str
    # CSR stands for certificate signing request
    requested_csr: str
    active_csr: str
    certificate: str
    ca: str  # Certificate authority
    chain: str

    def __init__(self, databag: ops.RelationDataContent) -> None:
        # Cannot use `self._databag =` since this class overrides `__setattr__()`
        super().__setattr__("_databag", databag)

    @staticmethod
    def _get_key(key: str) -> str:
        """Create databag key by adding a 'tls_' prefix."""
        return f"tls_{key}"

    @property
    def _attribute_names(self) -> list[str]:
        """Class attributes with type annotation"""
        return [name for name in inspect.get_annotations(type(self))]

    def __getattr__(self, name: str) -> typing.Optional[str]:
        assert name in self._attribute_names, f"Invalid attribute {name=}"
        return self._databag.get(self._get_key(name))

    def __setattr__(self, name: str, value: str) -> None:
        assert name in self._attribute_names, f"Invalid attribute {name=}"
        self._databag[self._get_key(name)] = value

    def __delattr__(self, name: str) -> None:
        assert name in self._attribute_names, f"Invalid attribute {name=}"
        self._databag.pop(self._get_key(name), None)

    def clear(self) -> None:
        """Delete all items in databag except for private key."""
        del self.requested_csr
        del self.active_csr
        del self.certificate
        del self.ca
        del self.chain


@dataclasses.dataclass(kw_only=True)
class _Relation:
    """Relation to TLS certificate provider"""

    _charm: "charm.MySQLRouterOperatorCharm"
    _interface: tls_certificates.TLSCertificatesRequiresV1
    _peer_unit_databag: _PeerUnitDatabag

    @property
    def certificate_saved(self) -> bool:
        """Whether a TLS certificate is available to use"""
        for value in [self._peer_unit_databag.certificate, self._peer_unit_databag.ca]:
            if not value:
                return False
        return True

    def save_certificate(self, event: tls_certificates.CertificateAvailableEvent) -> None:
        """Save TLS certificate in peer relation unit databag."""
        if (
            event.certificate_signing_request.strip()
            != self._peer_unit_databag.requested_csr.strip()
        ):
            logger.warning("Unknown certificate received. Ignoring.")
            return
        if (
            self.certificate_saved
            and event.certificate_signing_request.strip()
            == self._peer_unit_databag.active_csr.strip()
        ):
            # Workaround for https://github.com/canonical/tls-certificates-operator/issues/34
            logger.debug("TLS certificate already saved.")
            return
        logger.debug(f"Saving TLS certificate {event=}")
        self._peer_unit_databag.certificate = event.certificate
        self._peer_unit_databag.ca = event.ca
        self._peer_unit_databag.chain = json.dumps(event.chain)
        self._peer_unit_databag.active_csr = self._peer_unit_databag.requested_csr
        logger.debug(f"Saved TLS certificate {event=}")
        self._charm.workload.enable_tls(
            key=self._peer_unit_databag.private_key,
            certificate=self._peer_unit_databag.certificate,
        )

    def _generate_csr(self, key: bytes) -> bytes:
        """Generate certificate signing request (CSR)."""
        unit_name = self._charm.unit.name.replace("/", "-")
        return tls_certificates.generate_csr(
            private_key=key,
            subject=socket.getfqdn(),
            organization=self._charm.app.name,
            sans_dns=[
                unit_name,
                f"{unit_name}.{self._charm.app.name}-endpoints",
                f"{unit_name}.{self._charm.app.name}-endpoints.{self._charm.model_service_domain}",
                f"{self._charm.app.name}-endpoints",
                f"{self._charm.app.name}-endpoints.{self._charm.model_service_domain}",
                f"{unit_name}.{self._charm.app.name}",
                f"{unit_name}.{self._charm.app.name}.{self._charm.model_service_domain}",
                self._charm.app.name,
                f"{self._charm.app.name}.{self._charm.model_service_domain}",
            ],
            sans_ip=[
                str(self._charm.model.get_binding("juju-info").network.bind_address),
            ],
        )

    def request_certificate_creation(self):
        """Request new TLS certificate from related provider charm."""
        logger.debug("Requesting TLS certificate creation")
        if key := self._peer_unit_databag.private_key:
            key = key.encode("utf-8")
        else:
            key = tls_certificates.generate_private_key()
            self._peer_unit_databag.private_key = key.decode("utf-8")
        csr = self._generate_csr(key)
        self._interface.request_certificate_creation(certificate_signing_request=csr)
        self._peer_unit_databag.requested_csr = csr.decode("utf-8")
        logger.debug(
            f"Requested TLS certificate creation {self._peer_unit_databag.requested_csr=}"
        )

    def request_certificate_renewal(self):
        """Request TLS certificate renewal from related provider charm."""
        logger.debug(f"Requesting TLS certificate renewal {self._peer_unit_databag.active_csr=}")
        old_csr = self._peer_unit_databag.active_csr.encode("utf-8")
        key = self._peer_unit_databag.private_key.encode("utf-8")
        new_csr = self._generate_csr(key)
        self._interface.request_certificate_renewal(
            old_certificate_signing_request=old_csr, new_certificate_signing_request=new_csr
        )
        self._peer_unit_databag.requested_csr = new_csr.decode("utf-8")
        logger.debug(f"Requested TLS certificate renewal {self._peer_unit_databag.requested_csr=}")


class RelationEndpoint(ops.Object):
    """Relation endpoint and handlers for TLS certificate provider"""

    NAME = "certificates"

    def __init__(self, charm_: "charm.MySQLRouterOperatorCharm"):
        super().__init__(charm_, self.NAME)
        self._charm = charm_
        self._interface = tls_certificates.TLSCertificatesRequiresV1(self._charm, self.NAME)

        self.framework.observe(
            self._charm.on.set_tls_private_key_action,
            self._on_set_tls_private_key,
        )
        self.framework.observe(
            self._charm.on[self.NAME].relation_joined, self._on_tls_relation_joined
        )
        self.framework.observe(
            self._charm.on[self.NAME].relation_broken, self._on_tls_relation_broken
        )

        self.framework.observe(
            self._interface.on.certificate_available, self._on_certificate_available
        )
        self.framework.observe(
            self._interface.on.certificate_expiring, self._on_certificate_expiring
        )

    @property
    def peer_unit_databag(self) -> _PeerUnitDatabag:
        """MySQL Router charm peer relation unit databag"""
        peer_relation = self._charm.model.get_relation(_PEER_RELATION_ENDPOINT_NAME)
        return _PeerUnitDatabag(peer_relation.data[self._charm.unit])

    @property
    def _relation(self) -> typing.Optional[_Relation]:
        if not self._charm.model.get_relation(self.NAME):
            return
        return _Relation(
            _charm=self._charm,
            _interface=self._interface,
            _peer_unit_databag=self.peer_unit_databag,
        )

    @property
    def certificate_saved(self) -> bool:
        """Whether a TLS certificate is available to use"""
        if self._relation is None:
            return False
        return self._relation.certificate_saved

    @staticmethod
    def _parse_tls_key(raw_content: str) -> str:
        """Parse TLS key from plain text or base64 format."""
        if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", raw_content):
            return re.sub(
                r"(-+(BEGIN|END) [A-Z ]+-+)",
                "\n\\1\n",
                raw_content,
            )
        return base64.b64decode(raw_content).decode("utf-8")

    def _on_set_tls_private_key(self, event: ops.ActionEvent) -> None:
        """Handle action to set unit TLS private key."""
        logger.debug("Handling set TLS private key action")
        if self.peer_unit_databag.private_key:
            event.log("Warning: Deleted existing TLS private key")
            logger.warning("Deleted existing TLS private key")
        self.peer_unit_databag.private_key = self._parse_tls_key(event.params.get("internal-key"))
        event.log("Saved TLS private key")
        logger.debug("Saved TLS private key")
        if self._relation is None:
            event.log("No TLS relation active. Relate TLS provider to create certificate.")
            logger.debug("No TLS relation active. Skipped certificate request")
        else:
            try:
                self._relation.request_certificate_creation()
            except Exception as e:
                event.fail(f"Failed to request certificate: {e}")
                logger.exception(
                    "Failed to request certificate after TLS private key set via action"
                )
                raise
        logger.debug("Handled set TLS private key action")

    def _on_tls_relation_joined(self, _) -> None:
        """Request certificate when TLS relation joined."""
        self._relation.request_certificate_creation()

    def _on_tls_relation_broken(self, _) -> None:
        """Delete TLS certificate."""
        logger.debug("Deleting TLS certificate")
        self.peer_unit_databag.clear()
        self._charm.workload.disable_tls()
        logger.debug("Deleted TLS certificate")

    def _on_certificate_available(self, event: tls_certificates.CertificateAvailableEvent) -> None:
        """Save TLS certificate."""
        self._relation.save_certificate(event)

    def _on_certificate_expiring(self, event: tls_certificates.CertificateExpiringEvent) -> None:
        """Request the new certificate when old certificate is expiring."""
        if event.certificate != self.peer_unit_databag.certificate:
            logger.warning("Unknown certificate expiring")
            return

        self._relation.request_certificate_renewal()
