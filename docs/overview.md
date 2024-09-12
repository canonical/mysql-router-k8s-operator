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

# Navigation

[details=Navigation]

| Level | Path | Navlink |
|---------|---------|-------------|
| 1 | tutorial | [Tutorial]() |
| 2 | t-introduction | [1. Introduction](/t/12176) |
| 2 | t-set-up| [2. Set up the environment](/t/12178) |
| 2 | t-deploy | [3. Deploy MySQL Router](/t/12180) |
| 2 | t-manage-units | [4. Manage units](/t/12182) |
| 2 | t-enable-tls | [5. Enable TLS encryption](/t/12203) |
| 2 | t-clean-up | [6. Cleanup environment](/t/12204) |
| 1 | how-to | [How To]() |
| 2 | h-setup | [Setup]() |
| 3 | h-deploy-microk8s | [Deploy on MicroK8s](/t/12233) |
| 3 | h-manage-units | [Manage units](/t/12240) |
| 3 | h-enable-encryption | [Enable encryption](/t/12241) |
| 3 | h-manage-app | [Manage applications](/t/12242) |
| 2 | h-monitor | [Monitor (COS)]() |
| 3 | h-enable-monitoring | [Enable monitoring](/t/14101) |
| 3 | h-enable-tracing | [Enable tracing](/t/14553) |
| 2 | h-upgrade | [Upgrade]() |
| 3 | h-upgrade-intro | [Intro](/t/12235) |
| 3 | h-upgrade-major | [Major upgrade](/t/12236) |
| 3 | h-rollback-major | [Major rollback](/t/12237) |
| 3 | h-upgrade-minor | [Minor upgrade](/t/12238) |
| 3 | h-rollback-minor | [Minor rollback](/t/12239) |
| 2 | h-contribute | [Contribute](/t/14528) |
| 1 | reference | [Reference]() |
| 2 | r-releases-group | [Release Notes]() |
| 3 | r-releases | [All releases](/t/12201) |
| 3 | r-releases-rev155 | [Revision 154/155](/t/15354) |
| 3 | r-releases-rev117 | [Revision 117](/t/14074) |
| 3 | r-releases-rev96 | [Revision 96](/t/13523) |
| 3 | r-releases-rev82 | [Revision 82](/t/12796) |
| 3 | r-releases-rev69 | [Revision 69](/t/12202) |
| 2 | r-requirements | [Requirements](/t/12179) |
| 2 | r-testing | [Testing](/t/12234) |
| 2 | r-contacts | [Contacts](/t/12177) |
| 1 | explanation | [Explanation]() |
| 2 | e-interfaces | [Interfaces/endpoints](/t/12223) |
| 2 | e-statuses | [Statuses](/t/12231) |
| 2 | e-juju-details | [Juju](/t/12273) |

[/details]



# Redirects

[details=Mapping table]
| Path | Location |
| ---- | -------- |
[/details]