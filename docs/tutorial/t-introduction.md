# MySQL Router K8s tutorial

The MySQL Router K8s Operator delivers automated operations management from [day 0 to day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [MySQL Router Community Edition](https://www.mysql.com/products/community/) lightweight middleware that provides transparent routing between your application and back-end MySQL Servers. It is an open source, end-to-end, production-ready data platform component [on top of Juju](https://juju.is/). As a first step this tutorial shows you how to get MySQL Router K8s up and running, but the tutorial does not stop there. Through this tutorial you will learn a variety of operations, everything from adding replicas to advanced operations such as enabling Transport Layer Security (TLS). In this tutorial we will walk through how to:
- Set up an environment using [Multipass](https://multipass.run/) with [Microk8s](https://microk8s.io/) and [Juju](https://juju.is/).
- Deploy MySQL Router K8s using a single command.
- Configure TLS certificate in one command.

While this tutorial intends to guide and teach you as you deploy MySQL Router K8s, it will be most beneficial if you already have a familiarity with:
- Basic terminal commands.
- MySQL and MySQL Router concepts.
- [Charmed MySQL K8s operator](https://charmhub.io/mysql-k8s)

## Step-by-step guide

Here’s an overview of the steps required with links to our separate tutorials that deal with each individual step:
* [Set up the environment](/t/12178)
* [Deploy MySQL Router](/t/12180)
* [Managing your units](/t/12182)
* [Enable security](/t/12203)
* [Cleanup your environment](/t/12204)