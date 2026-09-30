"""Proxmox LXC containers for the Stock Market Analyser.

Replaces infra/proxmox/main.tf. Two containers on the Proxmox node:

  stockmarket     VMID 200  192.168.2.200  Django API, Celery, Nginx, Redis, webhook
  stockmarket-db  VMID 201  192.168.2.201  PostgreSQL 16 + pgvector
  stockmarket-obs VMID 208  192.168.2.208  Grafana + Prometheus + Loki (see issue #2)

(192.168.2.202 is the Ollama host and .203 a Frigate NVR; neither is managed here.)

Config (see README.md):
  proxmoxve:endpoint / proxmoxve:apiToken / proxmoxve:insecure   provider auth
  node / containerDatastore / containerPassword / sshPublicKey   this program
"""

import pulumi

from containers import ContainerSpec, make_container

config = pulumi.Config()

# The provider itself is configured entirely from `proxmoxve:*` stack config
# (endpoint / apiToken / insecure) via Pulumi's default provider - see README.md.
node_name = config.require("node")
datastore = config.require("containerDatastore")
container_password = config.require_secret("containerPassword")
ssh_public_key = config.get("sshPublicKey") or ""

app_spec = ContainerSpec(
    resource_name="stockmarket",
    vm_id=200,
    hostname="stockmarket",
    ipv4="192.168.2.200",
    description="Stock Market Analyser",
    cores=2,
    memory_mb=4096,
    swap_mb=2048,
    disk_gb=40,
    startup_order=3,
)

db_spec = ContainerSpec(
    resource_name="stockmarketDb",
    vm_id=201,
    hostname="stockmarket-db",
    ipv4="192.168.2.201",
    description="Stock Market Database",
    cores=2,
    memory_mb=2048,
    swap_mb=512,
    disk_gb=20,
    startup_order=2,
    extra_tags=("database",),
)

# Observability server: Grafana + Prometheus + Loki in Docker (nesting is on for every
# container here). Deliberately NOT colocated on the app container - that box has 4 GB
# and the browser agent already budgets ~400 MB of it, and a monitoring stack that dies
# with the thing it monitors is worth little. Disk is the sizing constraint rather than
# CPU: it holds 15 days of Prometheus TSDB plus 30 days of Loki chunks.
obs_spec = ContainerSpec(
    resource_name="stockmarketObs",
    vm_id=208,
    hostname="stockmarket-obs",
    ipv4="192.168.2.208",
    description="Stock Market Observability (Grafana/Prometheus/Loki)",
    cores=2,
    memory_mb=4096,
    swap_mb=2048,
    disk_gb=100,
    # Starts before the app and db so their first metrics and logs have somewhere to go.
    startup_order=1,
    extra_tags=("observability",),
)

common = {
    "node_name": node_name,
    "datastore": datastore,
    "password": container_password,
    "ssh_public_key": ssh_public_key,
}

app = make_container(app_spec, **common)
db = make_container(db_spec, **common)
obs = make_container(obs_spec, **common)

# Same four values infra/proxmox/outputs.tf exported. The hostnames come from the
# specs rather than `container.initialization`, which carries the secret root
# password and so would mark the whole output secret.
pulumi.export("container_id", app.vm_id)
pulumi.export("container_name", app_spec.hostname)
pulumi.export("db_container_id", db.vm_id)
pulumi.export("db_container_name", db_spec.hostname)
pulumi.export("obs_container_id", obs.vm_id)
pulumi.export("obs_container_name", obs_spec.hostname)
