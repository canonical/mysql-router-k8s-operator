> Reference > Release Notes > [All releases] > Revision 154/155

# Revision 154/155 
<sub>September 2, 2024</sub>

Dear community,

Canonical's newest Charmed MySQL Router K8s operator has been published in the [8.0/stable channel].

Due to the newly added support for arm64 architecture, the MySQL Router K8s charm now releases two revisions simultaneously:
* Revision 155 is built for `amd64`
* Revision 154 is built for `arm64`

To make sure you deploy for the right architecture, we recommend setting an [architecture constraint](https://juju.is/docs/juju/constraint#heading--arch) for your entire Juju model.

Otherwise, you can specify the architecture at deploy time with the `--constraints` flag as follows:

```shell
juju deploy mysql-router-k8s --constraints arch=<arch> --trust
```
where `<arch>` can be `amd64` or `arm64`.

## Highlights

Below is an overview of the major highlights, enhancements, and bugfixes in this revision. For a detailed list of all commits since the last stable release, see the [GitHub release notes].

* Upgraded MySQL Router from `v8.0.36` -> `v8.0.37` (see [Packaging](#packaging))
* Added support for ARM architecture

### Bugfixes

* [[DPE-4173](https://warthogs.atlassian.net/browse/DPE-4173)] Stabilize exporter tests by using listen-port to avoid ephemeral ports in [#277](https://github.com/canonical/mysql-router-k8s-operator/pull/277)
* [[DPE-3881](https://warthogs.atlassian.net/browse/DPE-3881)] Use ruff as a linter and formatter in [#292](https://github.com/canonical/mysql-router-k8s-operator/pull/292)
* Use poetry package-mode=false in [#296](https://github.com/canonical/mysql-router-k8s-operator/pull/296)
* [[DPE-4739](https://warthogs.atlassian.net/browse/DPE-4739)] Avoid using time.sleep in rollback integration tests in [#298](https://github.com/canonical/mysql-router-k8s-operator/pull/298)
* [[DPE-4817](https://warthogs.atlassian.net/browse/DPE-4817)] Upgrade to use lok_push_api v1 and capture rotated log files in [#283](https://github.com/canonical/mysql-router-k8s-operator/pull/283)
* Update Python dependencies

## Technical details
This section contains some technical details about the charm's contents and dependencies. 

* The K8s NodePort used to expose the DB service will change after every refresh which might lead to disconnections of clients sitting outside Juju. Check more details in [DPE-5276](https://warthogs.atlassian.net/browse/DPE-5276).

If you are jumping over several stable revisions, check [previous release notes][All releases] before upgrading.

### Requirements
See the [system requirements][] page for more details about software and hardware prerequisites.

### Packaging
This charm is based on the [`charmed-mysql` rock] Revision TODO. It packages:
- mysql-router `v8.0.37`
  - [8.0.37-0ubuntu0.22.04.1]
- mysql-shell `v8.0.37`
  - [8.0.37+dfsg-0ubuntu0.22.04.1~ppa3]
- prometheus-mysqlrouter-exporter `v5.0.1`
  - [5.0.1-0ubuntu0.22.04.1~ppa1]

### Libraries and interfaces
* **mysql `v0`**
  * See the [Libraries tab] in MySQL VM for the API reference.
* **grafana_agent `v0`** for integration with Grafana 
    * Implements  `cos_agent` interface
* **rolling_ops `v0`** for rolling operations across units 
    * Implements `rolling_op` interface
* **tempo_k8s `v1`, `v2`** for integration with Tempo charm
    * Implements `tracing` interface
* **tls_certificates_interface `v2`** for integration with TLS charms
    * Implements `tls-certificates` interface

See the [`/lib/charms` directory on GitHub][] for a full list of supported libraries.

See the [Integrations tab][] for a full list of supported integrations/interfaces/endpoints

## Contact us
  
Charmed MySQL K8s is an open source project that warmly welcomes community contributions, suggestions, fixes, and constructive feedback.  
* Raise software issues or feature requests on [**GitHub**](https://github.com/canonical/mysql-k8s-operator/issues)  
*  Report security issues through [**Launchpad**](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File)  
* Contact the Canonical Data Platform team through our [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) channel.

<!-- LINKS -->
[8.0/stable channel]: https://charmhub.io/mysql-router-k8s?channel=8.0/stable
[GitHub release notes]: https://github.com/canonical/mysql-router-k8s-operator/releases/tag/rev155

[All releases]: /t/12201
[system requirements]: /t/12179

[Integrations tab]: https://charmhub.io/mysql-router-k8s/integrations
[Libraries tab]: https://charmhub.io/mysql-router-k8s/libraries

[`/lib/charms` directory on GitHub]: https://github.com/canonical/mysql-router-k8s-operator/tree/main/lib/charms

[`charmed-mysql` rock]: https://snapcraft.io/charmed-mysql
[8.0.37-0ubuntu0.22.04.1]: https://launchpad.net/ubuntu/+source/mysql-8.0/8.0.37-0ubuntu0.24.04.1
[8.0.37+dfsg-0ubuntu0.22.04.1~ppa3]: https://launchpad.net/~data-platform/+archive/ubuntu/mysql-shell
[0.14.0-0ubuntu0.22.04.1~ppa2]: https://launchpad.net/~data-platform/+archive/ubuntu/mysqld-exporter
[5.0.1-0ubuntu0.22.04.1~ppa1]: https://launchpad.net/~data-platform/+archive/ubuntu/mysqlrouter-exporter
[8.0.35-31-0ubuntu0.22.04.1~ppa3]: https://launchpad.net/~data-platform/+archive/ubuntu/xtrabackup