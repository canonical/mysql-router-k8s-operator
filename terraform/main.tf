resource "juju_application" "mysql_router" {
  model_uuid = var.model
  name       = var.app_name
  trust      = true

  charm {
    name     = "mysql-router-k8s"
    base     = var.base
    channel  = var.channel
    revision = var.revision
  }

  config      = var.config
  constraints = var.constraints
  units       = var.units
}
