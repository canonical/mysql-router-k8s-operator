# MySQL Router K8s Documentation

The MySQL Router K8s Operator delivers automated operations management from [day 0 to day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [MySQL Router Community Edition](https://www.mysql.com/products/community/) lightweight middleware that provides transparent routing between your application and back-end MySQL Servers. It is an open source, end-to-end, production-ready data platform component [on top of Juju](https://juju.is/).

![image|690x424](upload://vpevillwv3S9C44LDFBxkGCxpGq.png)

MySQL Router is part of InnoDB Cluster, and is lightweight middleware that provides transparent routing between your application and back-end MySQL Servers. It can be used for a wide variety of use cases, such as providing high availability and scalability by effectively routing database traffic to appropriate back-end MySQL Servers. The pluggable architecture also enables developers to extend MySQL Router for custom use cases.

This MySQL Router K8s operator charm comes in two flavours to deploy and operate MySQL Router on [physical/virtual machines](https://github.com/canonical/mysql-router-operator) and [Kubernetes](https://github.com/canonical/mysql-router-k8s-operator). Both offer features identical set of features and simplifies deployment, scaling, configuration and management of MySQL Router in production at scale in a reliable way.

## Project and community

This MySQL Router K8s charm is an official distribution of MySQL Router. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.
- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/mysql-router)
- [Contribute](https://github.com/canonical/mysql-router-k8s-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/mysql-router-k8s-operator/issues/new/choose)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
-  [Contacts us](/t/12177) for all further questions

## In this documentation

| | |
|--|--|
|  [Tutorials](/t/12176)</br>  Get started - a hands-on introduction to using Charmed MySQL operator for new users </br> |  [How-to guides](/t/12233) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](/t/12201) </br> Technical information - specifications, APIs, architecture | [Explanation](/t/12223) </br> Concepts - discussion and clarification of key topics  |

# Contents

1. [Tutorial](tutorial)
  1. [1. Introduction](tutorial/t-overview.md)
  1. [2. Set up the environment](tutorial/t-setup-environment.md)
  1. [3. Deploy MySQL Router](tutorial/t-deploy-charm.md)
  1. [4. Manage units](tutorial/t-managing-units.md)
  1. [5. Enable security](tutorial/t-enable-security.md)
  1. [6. Cleanup environment](tutorial/t-cleanup-environment.md)
1. [How To](how-to)
  1. [Setup](how-to/h-setup)
    1. [Deploy on MicroK8s](how-to/h-setup/h-deploy-microk8s.md)
    1. [Manage units](how-to/h-setup/h-manage-units.md)
    1. [Enable encryption](how-to/h-setup/h-enable-encryption.md)
    1. [Manage applications](how-to/h-setup/h-manage-app.md)
  1. [Monitor (COS)](how-to/h-monitor)
    1. [Enable monitoring](how-to/h-monitor/h-enable-monitoring.md)
  1. [Upgrade](how-to/h-upgrade)
    1. [Intro](how-to/h-upgrade/h-upgrade-intro.md)
    1. [Major upgrade](how-to/h-upgrade/h-upgrade-major.md)
    1. [Major rollback](how-to/h-upgrade/h-rollback-major.md)
    1. [Minor upgrade](how-to/h-upgrade/h-upgrade-minor.md)
    1. [Minor rollback](how-to/h-upgrade/h-rollback-minor.md)
1. [Reference](reference)
  1. [Release Notes](reference/r-releases-group)
    1. [All releases](reference/r-releases-group/r-releases.md)
    1. [Revision 112](reference/r-releases-group/r-releases-rev112.md)
    1. [Revision 96](reference/r-releases-group/r-releases-rev96.md)
    1. [Revision 82](reference/r-releases-group/r-releases-rev82.md)
    1. [Revision 69](reference/r-releases-group/r-releases-rev69.md)
  1. [Requirements](reference/r-requirements.md)
  1. [Contributing](https://github.com/canonical/mysql-router-k8s-operator/blob/main/CONTRIBUTING.md)
  1. [Testing](reference/r-testing.md)
  1. [Actions](https://charmhub.io/mysql-router-k8s/actions)
  1. [Configurations](https://charmhub.io/mysql-router-k8s/configure)
  1. [Libraries](https://charmhub.io/mysql-router-k8s/libraries)
  1. [Integrations](https://charmhub.io/mysql-router-k8s/integrations)
  1. [Resources](https://charmhub.io/mysql-router-k8s/resources)
  1. [Contacts](reference/r-contacts.md)
1. [Explanation](explanation)
  1. [Interfaces/endpoints](explanation/e-interfaces.md)
  1. [Statuses](explanation/e-statuses.md)
  1. [Juju](explanation/e-juju-details.md)