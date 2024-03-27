# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation to TLS certificate provider"""

import base64
import dataclasses
import json
import logging
import re
import socket
import typing

import charms.tls_certificates_interface.v1.tls_certificates as tls_certificates
import ops

import relations.secrets

if typing.TYPE_CHECKING:
    import kubernetes_charm

logger = logging.getLogger(__name__)

_PEER_RELATION_ENDPOINT_NAME = "mysql-router-peers"


def _generate_private_key() -> str:
    """Generate TLS private key."""
    return tls_certificates.generate_private_key().decode("utf-8")


@dataclasses.dataclass(kw_only=True)
class _Relation:
    """Relation to TLS certificate provider"""

    _charm: "kubernetes_charm.KubernetesRouterCharm"
    _interface: tls_certificates.TLSCertificatesRequiresV1
    _secrets: relations.secrets.RelationSecrets

    @property
    def certificate_saved(self) -> bool:
        """Whether a TLS certificate is available to use"""
        for value in (
            self._secrets.get_value(relations.secrets.UNIT_SCOPE, "tls-certificate"),
            self._secrets.get_value(relations.secrets.UNIT_SCOPE, "tls-ca"),
        ):
            if not value:
                return False
        return True

    @property
    def key(self) -> str:
        """The TLS private key"""
        private_key = self._secrets.get_value(relations.secrets.UNIT_SCOPE, "tls-private-key")
        if not private_key:
            private_key = _generate_private_key()
            self._secrets.set_value(relations.secrets.UNIT_SCOPE, "tls-private-key", private_key)
        return private_key

    @property
    def certificate(self) -> str:
        """The TLS certificate"""
        return self._secrets.get_value(relations.secrets.UNIT_SCOPE, "tls-certificate")

    @property
    def certificate_authority(self) -> str:
        """The TLS certificate authority"""
        return self._secrets.get_value(relations.secrets.UNIT_SCOPE, "tls-ca")

    def save_certificate(self, event: tls_certificates.CertificateAvailableEvent) -> None:
        """Save TLS certificate in peer relation unit databag."""
        if (
            event.certificate_signing_request.strip()
            != self._secrets.get_value(relations.secrets.UNIT_SCOPE, "tls-requested-csr").strip()
        ):
            logger.warning("Unknown certificate received. Ignoring.")
            return
        if (
            self.certificate_saved
            and event.certificate_signing_request.strip()
            == self._secrets.get_value(relations.secrets.UNIT_SCOPE, "tls-active-csr")
        ):
            # Workaround for https://github.com/canonical/tls-certificates-operator/issues/34
            logger.debug("TLS certificate already saved.")
            return
        logger.debug(f"Saving TLS certificate {event=}")
        self._secrets.set_value(relations.secrets.UNIT_SCOPE, "tls-certificate", event.certificate)
        self._secrets.set_value(relations.secrets.UNIT_SCOPE, "tls-ca", event.ca)
        self._secrets.set_value(relations.secrets.UNIT_SCOPE, "tls-chain", json.dumps(event.chain))
        self._secrets.set_value(
            relations.secrets.UNIT_SCOPE,
            "tls-active-csr",
            self._secrets.get_value(relations.secrets.UNIT_SCOPE, "tls-requested-csr"),
        )
        logger.debug(f"Saved TLS certificate {event=}")
        self._charm.reconcile(event=None)

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
                "127.0.0.1",
            ],
        )

    def request_certificate_creation(self):
        """Request new TLS certificate from related provider charm."""
        logger.debug("Requesting TLS certificate creation")
        csr = self._generate_csr(self.key.encode("utf-8"))
        self._interface.request_certificate_creation(certificate_signing_request=csr)
        self._secrets.set_value(
            relations.secrets.UNIT_SCOPE, "tls-requested-csr", csr.decode("utf-8")
        )
        logger.debug("Requested TLS certificate creation")

    def request_certificate_renewal(self):
        """Request TLS certificate renewal from related provider charm."""
        logger.debug("Requesting TLS certificate renewal")
        old_csr = self._secrets.get_value(relations.secrets.UNIT_SCOPE, "tls-active-csr").encode(
            "utf-8"
        )
        new_csr = self._generate_csr(self.key.encode("utf-8"))
        self._interface.request_certificate_renewal(
            old_certificate_signing_request=old_csr, new_certificate_signing_request=new_csr
        )
        self._secrets.set_value(
            relations.secrets.UNIT_SCOPE, "tls-requested-csr", new_csr.decode("utf-8")
        )
        logger.debug("Requested TLS certificate renewal")


class RelationEndpoint(ops.Object):
    """Relation endpoint and handlers for TLS certificate provider"""

    NAME = "certificates"

    def __init__(self, charm_: "kubernetes_charm.KubernetesRouterCharm") -> None:
        super().__init__(charm_, self.NAME)
        self._charm = charm_
        self._interface = tls_certificates.TLSCertificatesRequiresV1(self._charm, self.NAME)

        self._secret_fields = [
            "tls-requested-csr",
            "tls-active-csr",
            "tls-certificate",
            "tls-ca",
            "tls-chain",
            "tls-private-key",
        ]
        self._secrets = relations.secrets.RelationSecrets(
            charm_, self._interface.relationship_name, unit_secret_fields=self._secret_fields
        )

        self.framework.observe(
            self._charm.on["set-tls-private-key"].action,
            self._on_set_tls_private_key,
        )
        self.framework.observe(
            self._charm.on[self.NAME].relation_created, self._on_tls_relation_created
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
    def _relation(self) -> typing.Optional[_Relation]:
        if not self._charm.model.get_relation(self.NAME):
            return
        return _Relation(
            charm_=self._charm,
            interface=self._interface,
            secrets=self._secrets,
        )

    @property
    def certificate_saved(self) -> bool:
        """Whether a TLS certificate is available to use"""
        if self._relation is None:
            return False
        return self._relation.certificate_saved

    @property
    def key(self) -> typing.Optional[str]:
        """The TLS private key"""
        if self._relation is None:
            return None
        return self._relation.key

    @property
    def certificate(self) -> typing.Optional[str]:
        """The TLS certificate"""
        if self._relation is None:
            return None
        return self._relation.certificate

    @property
    def certificate_authority(self) -> typing.Optional[str]:
        """The TLS certificate authority"""
        if self._relation is None:
            return None
        return self._relation.certificate_authority

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
        if key := event.params.get("internal-key"):
            key = self._parse_tls_key(key)
        else:
            key = _generate_private_key()
            event.log("No key provided. Generated new key.")
            logger.debug("No TLS key provided via action. Generated new key.")
        self._secrets.set_value(relations.secrets.UNIT_SCOPE, "tls-private-key", key)
        event.log("Saved TLS private key")
        logger.debug("Saved TLS private key")
        if self._relation is None:
            event.log(
                "No TLS certificate relation active. Relate a certificate provider charm to enable TLS."
            )
            logger.debug("No TLS certificate relation active. Skipped certificate request")
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

    def _on_tls_relation_created(self, _) -> None:
        """Request certificate when TLS relation created."""
        self._relation.request_certificate_creation()

    def _on_tls_relation_broken(self, _) -> None:
        """Delete TLS certificate."""
        logger.debug("Deleting TLS certificate")
        for secret_field in self._secret_fields:
            self._secrets.set_value(relations.secrets.UNIT_SCOPE, secret_field, None)
        self._charm.reconcile(event=None)
        logger.debug("Deleted TLS certificate")

    def _on_certificate_available(self, event: tls_certificates.CertificateAvailableEvent) -> None:
        """Save TLS certificate."""
        self._relation.save_certificate(event)

    def _on_certificate_expiring(self, event: tls_certificates.CertificateExpiringEvent) -> None:
        """Request the new certificate when old certificate is expiring."""
        if event.certificate != self.certificate:
            logger.warning("Unknown certificate expiring")
            return

        self._relation.request_certificate_renewal()
