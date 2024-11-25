>Reference > Release Notes > [All revisions](/t/12201) > Revision 117  

# Revision 117

<sub>Aug 20, 2024</sub>

Dear community,

We'd like to announce that Canonical's newest Charmed MySQL Router K8s operator has been published in the '8.0/stable' [channel](https://charmhub.io/mysql-router-k8s/docs/r-releases?channel=8.0/stable) :tada:

[note]
If you are jumping over several stable revisions, make sure to check [previous release notes](/t/12201) before upgrading to this revision.
[/note]  

## Features you can start using today

* New workload version [MySQL Router 8.0.36](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-36.html) [[PR#209](https://github.com/canonical/mysql-router-k8s-operator/pull/209)]
* [K8s NodePort](https://kubernetes.io/docs/concepts/services-networking/service/#type-nodeport) support [[PR#211](https://github.com/canonical/mysql-router-k8s-operator/pull/211)]
* [Observability with COS](/t/14101) [[PR#210](https://github.com/canonical/mysql-router-k8s-operator/pull/210)]
* Introduced [COS Tracing support](/t/14553) [[PR#250](https://github.com/canonical/mysql-router-k8s-operator/pull/250)][[DPE-4615](https://warthogs.atlassian.net/browse/DPE-4615)]
* Router version displayed in upgrade status [[PR#230](https://github.com/canonical/mysql-router-k8s-operator/pull/230)]
* All the functionality from [previous revisions](/t/12201)

## Bugfixes

* Fix TLS configuration immediately deleted after enabling [[PR#249](https://github.com/canonical/mysql-router-k8s-operator/pull/249)]
* Clear connection pool before relating with COS to avoid TIME_WAIT connections + stabilize exporter tests [[PR#245](https://github.com/canonical/mysql-router-k8s-operator/pull/245)][[DPE-3899](https://warthogs.atlassian.net/browse/DPE-3899), [DPE-4173](https://warthogs.atlassian.net/browse/DPE-4173)]
* Updated charmed-mysql ROCK image to latest version [[PR#237](https://github.com/canonical/mysql-router-k8s-operator/pull/237)]
* Removed redundant upgrade check [[PR#234](https://github.com/canonical/mysql-router-k8s-operator/pull/234)]
* Ported over changes from VM operator related to external connectivity [[PR#225](https://github.com/canonical/mysql-router-k8s-operator/pull/225)]
* Updated `resume-upgrade` action `force` description [[PR#232](https://github.com/canonical/mysql-router-k8s-operator/pull/232)]
* Fixed issue if incompatible upgrade is forced [[PR#231](https://github.com/canonical/mysql-router-k8s-operator/pull/231)]

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/mysql-router-k8s-operator/issues) platforms.  
[GitHub Releases](https://github.com/canonical/mysql-router-k8s-operator/releases) provide a detailed list of bugfixes, PRs, and commits for each revision.  
  
## Inside the charms

* Charmed MySQL Router K8s ships MySQL Router `8.0.36-0ubuntu0.22.04.1`
* CLI mysql-shell version is `8.0.36+dfsg-0ubuntu0.22.04.1~ppa4`
* The Prometheus `mysql-router-exporter` is `5.0.1-0ubuntu0.22.04.1~ppa1`
* K8s charms based on our [ROCK OCI](https://github.com/canonical/charmed-mysql-rock) ([resource-revision 53](https://github.com/canonical/mysql-router-k8s-operator/releases/tag/rev117), based on Ubuntu LTS `22.04.4`), snap revision `103`
* Principal charms supports the latest LTS series 22.04 only

## Technical notes

* Upgrade (`juju refresh`) is possible from revision 69+
* Use this operator together with modern operator [Charmed MySQL K8s](https://charmhub.io/mysql-k8s)
* Please check restrictions from [previous release notes](https://charmhub.io/mysql-router-k8s/docs/r-releases)

## Contact us

Charmed MySQL Router K8s is an open source project that warmly welcomes community contributions, suggestions, fixes, and constructive feedback.  
* Raise software issues or feature requests on [**GitHub**](https://github.com/canonical/mysql-router-k8s-operator/issues)  
*  Report security issues through [**Launchpad**](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File)  
* Contact the Canonical Data Platform team through our [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) channel.