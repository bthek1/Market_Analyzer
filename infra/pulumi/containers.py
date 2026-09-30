"""Shared LXC container definition.

The two Proxmox containers differ only in id, hostname, IP and sizing, so they
are built from one helper rather than the two near-identical HCL blocks this
replaces (infra/proxmox/main.tf).

Every value here must stay byte-for-byte equivalent to what Terraform applied -
a drifting field shows up as a replacement in `pulumi preview`, and replacing a
container destroys production.
"""

from dataclasses import dataclass

import pulumi
import pulumi_proxmoxve as proxmoxve

GATEWAY = "192.168.2.1"
DNS_SERVERS = ["8.8.8.8", "1.1.1.1"]
NETWORK_BRIDGE = "vmbr0"
OS_TEMPLATE = "local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
OS_TYPE = "ubuntu"


@dataclass(frozen=True)
class ContainerSpec:
    """Everything that differs between the app and db containers."""

    resource_name: str
    vm_id: int
    hostname: str
    ipv4: str
    description: str
    cores: int
    memory_mb: int
    swap_mb: int
    disk_gb: int
    startup_order: int
    extra_tags: tuple[str, ...] = ()


def make_container(
    spec: ContainerSpec,
    *,
    node_name: str,
    datastore: str,
    password: pulumi.Output[str] | str,
    ssh_public_key: str,
) -> proxmoxve.ct.Container:
    """Create one unprivileged Ubuntu LXC container with nesting enabled."""
    return proxmoxve.ct.Container(
        spec.resource_name,
        node_name=node_name,
        vm_id=spec.vm_id,
        description=spec.description,
        tags=sorted(["stockmarket", "pulumi", *spec.extra_tags]),
        initialization=proxmoxve.ct.ContainerInitializationArgs(
            hostname=spec.hostname,
            dns=proxmoxve.ct.ContainerInitializationDnsArgs(servers=DNS_SERVERS),
            ip_configs=[
                proxmoxve.ct.ContainerInitializationIpConfigArgs(
                    ipv4=proxmoxve.ct.ContainerInitializationIpConfigIpv4Args(
                        address=f"{spec.ipv4}/24",
                        gateway=GATEWAY,
                    ),
                ),
            ],
            user_account=proxmoxve.ct.ContainerInitializationUserAccountArgs(
                password=password,
                keys=[ssh_public_key] if ssh_public_key else [],
            ),
        ),
        cpu=proxmoxve.ct.ContainerCpuArgs(cores=spec.cores),
        memory=proxmoxve.ct.ContainerMemoryArgs(
            dedicated=spec.memory_mb,
            swap=spec.swap_mb,
        ),
        disk=proxmoxve.ct.ContainerDiskArgs(
            datastore_id=datastore,
            size=spec.disk_gb,
        ),
        network_interfaces=[
            proxmoxve.ct.ContainerNetworkInterfaceArgs(
                name="eth0",
                bridge=NETWORK_BRIDGE,
            ),
        ],
        operating_system=proxmoxve.ct.ContainerOperatingSystemArgs(
            template_file_id=OS_TEMPLATE,
            type=OS_TYPE,
        ),
        features=proxmoxve.ct.ContainerFeaturesArgs(nesting=True),
        unprivileged=True,
        started=True,
        startup=proxmoxve.ct.ContainerStartupArgs(
            order=spec.startup_order,
            up_delay=10,
            down_delay=10,
        ),
        opts=pulumi.ResourceOptions(
            # These are live production containers. protect turns an accidental
            # destroy or replace into a hard error instead of a wiped machine.
            protect=True,
            # Dropping a container from this program must never delete the
            # machine off Proxmox - removal is a deliberate, manual act.
            retain_on_delete=True,
            # Create-time-only fields the Proxmox API cannot read back. After an
            # import they read as empty, so every preview would want to REPLACE
            # the container - i.e. destroy production - to "restore" them.
            # All three are ForceNew fields we never want changed in place
            # anyway, so pinning them to state is the correct answer, not a
            # workaround: to change any of them you rebuild the container.
            #   initialization.userAccount - root password + SSH keys, write-only
            #   operatingSystem            - template_file_id, not returned
            #   features                   - returned as "" by the provider read
            ignore_changes=[
                "initialization.userAccount",
                "operatingSystem",
                "features",
            ],
        ),
    )
