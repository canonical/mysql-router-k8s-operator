# How to manage related applications

## Modern `mysql_client` interface:

Relations to new applications are supported via the "[mysql_client](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/mysql_client/v0/README.md)" interface. To create a relation:

```shell
juju relate mysql-router-k8s application
```

To remove a relation:

```shell
juju remove-relation mysql-router-k8s application
```

All listed on CharmHub applications are available [here](https://charmhub.io/mysql-router-k8s/integrations), e.g.:
 * [mysql-test-app](https://charmhub.io/mysql-test-app)
 * [wordpress-k8s](https://charmhub.io/wordpress-k8s)
 * [slurmdbd](https://charmhub.io/slurmdbd)

## Legacy `mysql` interface:

This charm does NOT support legacy `mysql` interface.

## Internal operator user

To rotate the internal router passwords, the relation with backend-database should be removed and related again. That process will generate a new user and password for the application, while retaining the requested database and data.

```shell
juju remove-relation mysql-k8s mysql-router-k8s

juju integrate mysql-k8s mysql-router-k8s
```