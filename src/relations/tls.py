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

import charm
import constants

logger = logging.getLogger(__name__)
# TODO: fix logging levels


class _PeerUnitDatabag:
    key: str
    requested_csr: str
    active_csr: str
    certificate: str
    ca: str
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
        """Delete all items in databag."""
        # Delete all type-annotated class attributes
        for name in self._attribute_names:
            delattr(self, name)


@dataclasses.dataclass
class _Relation:
    _charm: charm.MySQLRouterOperatorCharm
    _interface: tls_certificates.TLSCertificatesRequiresV1

    @property
    def _peer_relation(self) -> ops.Relation:
        return self._charm.model.get_relation(constants.PEER)

    @property
    def peer_unit_databag(self) -> _PeerUnitDatabag:
        return _PeerUnitDatabag(self._peer_relation.data[self._charm.unit])

    @property
    def certificate_saved(self) -> bool:
        for value in [self.peer_unit_databag.certificate, self.peer_unit_databag.ca]:
            if not value:
                return False
        return True

    def save_certificate(self, event: tls_certificates.CertificateAvailableEvent) -> None:
        if (
            event.certificate_signing_request.strip()
            != self.peer_unit_databag.requested_csr.strip()
        ):
            logger.warning("Unknown certificate received. Ignoring.")
            return
        if (
            self.certificate_saved
            and event.certificate_signing_request.strip()
            == self.peer_unit_databag.active_csr.strip()
        ):
            # Workaround for https://github.com/canonical/tls-certificates-operator/issues/34
            logger.debug("TLS certificate already saved.")
            return
        self.peer_unit_databag.certificate = event.certificate
        self.peer_unit_databag.ca = event.ca
        self.peer_unit_databag.chain = json.dumps(event.chain)
        self.peer_unit_databag.active_csr = self.peer_unit_databag.requested_csr
        self._charm.workload.enable_tls(
            self.peer_unit_databag.key, self.peer_unit_databag.certificate
        )

    @staticmethod
    def _parse_tls_key(raw_content: str) -> bytes:
        """Parse TLS key from plain text or base64 format."""
        if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", raw_content):
            return re.sub(
                r"(-+(BEGIN|END) [A-Z ]+-+)",
                "\n\\1\n",
                raw_content,
            ).encode("utf-8")
        return base64.b64decode(raw_content)

    @property
    def _unit_hostname(self) -> str:
        """Get the hostname.localdomain for a unit.
        Translate juju unit name to hostname.localdomain, necessary
        for correct name resolution under k8s.
        Returns:
            A string representing the hostname.localdomain of the unit.
        """
        return f"{self._charm.unit.name.replace('/', '-')}.{self._charm.app.name}-endpoints"

    def _generate_csr(self, key: bytes) -> bytes:
        return tls_certificates.generate_csr(
            private_key=key,
            subject=socket.getfqdn(),
            organization=self._charm.app.name,
            sans=[
                socket.gethostname(),
                self._unit_hostname,
                str(self._charm.model.get_binding(self._peer_relation).network.bind_address),
            ],
        )

    def request_certificate_creation(self, internal_key: str = None):
        if internal_key:
            key = self._parse_tls_key(internal_key)
        else:
            key = tls_certificates.generate_private_key()
        csr = self._generate_csr(key)
        self._interface.request_certificate_creation(certificate_signing_request=csr)
        self.peer_unit_databag.key = key.decode("utf-8")
        self.peer_unit_databag.requested_csr = csr.decode("utf-8")

    def request_certificate_renewal(self):
        old_csr = self.peer_unit_databag.active_csr.encode("utf-8")
        key = self.peer_unit_databag.key.encode("utf-8")
        new_csr = self._generate_csr(key)
        self._interface.request_certificate_renewal(
            old_certificate_signing_request=old_csr, new_certificate_signing_request=new_csr
        )
        self.peer_unit_databag.requested_csr = new_csr.decode("utf-8")


class RelationEndpoint(ops.Object):
    def __init__(self, charm_: charm.MySQLRouterOperatorCharm):
        super().__init__(charm_, constants.TLS_RELATION)
        self._charm = charm_
        self._interface = tls_certificates.TLSCertificatesRequiresV1(
            self._charm, constants.TLS_RELATION
        )

        self.framework.observe(
            self._charm.on.set_tls_private_key_action,
            self._on_set_tls_private_key,
        )
        self.framework.observe(
            self._charm.on[constants.TLS_RELATION].relation_joined, self._on_tls_relation_joined
        )
        self.framework.observe(
            self._charm.on[constants.TLS_RELATION].relation_broken, self._on_tls_relation_broken
        )

        self.framework.observe(
            self._interface.on.certificate_available, self._on_certificate_available
        )
        self.framework.observe(
            self._interface.on.certificate_expiring, self._on_certificate_expiring
        )

    @property
    def _relation(self) -> typing.Optional[_Relation]:
        if not self._charm.model.get_relation(constants.TLS_RELATION):
            return
        return _Relation(self._charm, self._interface)

    @property
    def certificate_saved(self) -> bool:
        if self._relation is None:
            return False
        return self._relation.certificate_saved

    def _on_set_tls_private_key(self, event: ops.ActionEvent) -> None:
        """Action for setting a TLS private key."""
        if self._relation is None:
            event.fail("No TLS relation available.")
            return
        try:
            self._relation.request_certificate_creation(event.params.get("internal-key"))
        except Exception as e:
            event.fail(f"Failed to request certificate: {e}")

    def _on_tls_relation_joined(self, _) -> None:
        """Request certificate when TLS relation joined."""
        self._relation.request_certificate_creation()

    def _on_tls_relation_broken(self, _) -> None:
        """Delete TLS certificate."""
        self._relation.peer_unit_databag.clear()
        self._charm.workload.disable_tls()

    def _on_certificate_available(self, event: tls_certificates.CertificateAvailableEvent) -> None:
        """Save TLS certificate."""
        self._relation.save_certificate(event)

    def _on_certificate_expiring(self, event: tls_certificates.CertificateExpiringEvent) -> None:
        """Request the new certificate when old certificate is expiring."""
        if event.certificate != self._relation.peer_unit_databag.certificate:
            logger.error("An unknown certificate expiring.")
            return

        self._relation.request_certificate_renewal()
