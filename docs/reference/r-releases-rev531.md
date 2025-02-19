> Reference > Release Notes > [All revisions] > Revision 530/531

# Revision 530/531
<sub>January 6, 2025</sub>

Dear community,

Canonical's newest Charmed MySQL Router K8s operator has been published in the [8.0/stable channel]:
* Revision 531 is built for `amd64` on Ubuntu 22.04 LTS
* Revision 530 is built for `arm64` on Ubuntu 22.04 LTS

If you are jumping over several stable revisions, check [previous release notes][All revisions] before upgrading.

---

## Highlights 
* Updated MySQL Router to `v8.0.39` ([PR #308](https://github.com/canonical/mysql-router-k8s-operator/pull/308)) ([DPE-4573](https://warthogs.atlassian.net/browse/DPE-4573))
* Add K8s LoadBalancer support via [expose-external](https://charmhub.io/mysql-router-k8s/configurations?channel=8.0/candidate#expose-external) config option ([PR #328](https://github.com/canonical/mysql-router-k8s-operator/pull/328)) ([DPE-5637](https://warthogs.atlassian.net/browse/DPE-5637))

## Features and improvements
* Add [COS Tracing](/t/14553) support using [Tempo K8s coordinator](https://charmhub.io/tempo-coordinator-k8s) ([PR #324](https://github.com/canonical/mysql-router-k8s-operator/pull/324)) ([DPE-5312](https://warthogs.atlassian.net/browse/DPE-5312))
* Truncated TLS common name to 64 characters ([PR #318](https://github.com/canonical/mysql-router-k8s-operator/pull/318))
* Bumped supported juju versions ([PR #325](https://github.com/canonical/mysql-router-k8s-operator/pull/325)) ([DPE-5625](https://warthogs.atlassian.net/browse/DPE-5625))
  * `v2.9.50` → `v2.9.51`
  * `v3.4.5` → `v3.6.1`

<!--## Bugfixes and maintenance-->

[details=Libraries, testing, and CI]

* Switched from tox build wrapper to `charmcraft.yaml` overrides ([PR #319](https://github.com/canonical/mysql-router-k8s-operator/pull/319))
* Test against juju 3.6/candidate + upgrade dpw to v23.0.5 ([PR #335](https://github.com/canonical/mysql-router-k8s-operator/pull/335))
* Run juju 3.6 nightly tests against 3.6/stable ([PR #337](https://github.com/canonical/mysql-router-k8s-operator/pull/337))
* Run tests on juju 3.6 on a nightly schedule ([PR #311](https://github.com/canonical/mysql-router-k8s-operator/pull/311)) ([DPE-4976](https://warthogs.atlassian.net/browse/DPE-4976))
* Update canonical/charming-actions action to v2.6.3 ([PR #280](https://github.com/canonical/mysql-router-k8s-operator/pull/280))
* Update data-platform-workflows to v23 ([PR #326](https://github.com/canonical/mysql-router-k8s-operator/pull/326))
* Update dependency canonical/microk8s to v1.31 ([PR #316](https://github.com/canonical/mysql-router-k8s-operator/pull/316))
* Update dependency cryptography to v43 [SECURITY] ([PR #317](https://github.com/canonical/mysql-router-k8s-operator/pull/317))
* Update Juju agents (patch) ([PR #287](https://github.com/canonical/mysql-router-k8s-operator/pull/287))
[/details]

## Requirements and compatibility
* (increased) MySQL version: `v8.0.37` → `v8.0.39`
* (increased) Minimum Juju 2 version: `v2.9.50` → `v2.9.51`
* (increased) Minimum Juju 3 version: `v3.4.5` → `v3.6.1`

See the [system requirements] for more details about Juju versions and other software and hardware prerequisites.

### Packaging

This charm is based on the Charmed MySQL [rock image]. It packages:
* [mysql-router] `v8.0.39`
* [mysql-shell] `v8.0.38`
* [prometheus-mysqlrouter-exporter] `v5.0.1`

See the [`/lib/charms` directory on GitHub] for more details about all supported libraries.

See the [`metadata.yaml` file on GitHub] for a full list of supported interfaces.

<!-- Topics -->
[All revisions]: /t/12201
[system requirements]: /t/12179

<!-- GitHub -->
[`/lib/charms` directory on GitHub]: https://github.com/canonical/mysql-router-k8s-operator/tree/main/lib/charms
[`metadata.yaml` file on GitHub]: https://github.com/canonical/mysql-router-k8s-operator/blob/main/metadata.yaml

<!-- Charmhub -->
[8.0/stable channel]: https://charmhub.io/mysql-router?channel=8.0/stable

<!-- Snap/Rock -->
[`charmed-mysql-router` packaging]: https://github.com/canonical/charmed-mysql-router-rock

[MySQL Libraries tab]: https://charmhub.io/mysql/libraries

[snap]: https://github.com/canonical/charmed-mysql-snap/releases/tag/rev114
[rock image]: https://github.com/canonical/charmed-mysql-rock/pkgs/container/charmed-mysql

[mysql-router]: https://launchpad.net/ubuntu/+source/mysql-8.0/
[mysql-shell]: https://launchpad.net/~data-platform/+archive/ubuntu/mysql-shell
[prometheus-mysqlrouter-exporter]: https://launchpad.net/~data-platform/+archive/ubuntu/mysqlrouter-exporter