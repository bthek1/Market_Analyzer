# Pulumi — Proxmox container provisioning

Provisions the two production LXC containers (app VMID 200, db VMID 201) on the
Proxmox node `bthek1`. Replaced the Terraform program that lived in
`infra/proxmox/` (removed).

Ansible (machine bootstrap) and CI/CD (app deploys) are separate layers and are
not affected by anything here — see `docs/project_docs/prod-infrastructure.md`.

## One-time setup

```bash
# 1. CLI
curl -fsSL https://get.pulumi.com | sh          # installs to ~/.pulumi/bin

# 2. Python deps (uv creates .venv from pyproject.toml)
cd infra/pulumi && uv sync

# 3. Local file backend - the equivalent of terraform.tfstate. state/ is gitignored.
pulumi login file://$(pwd)/state

# 4. Passphrase that encrypts secrets in Pulumi.prod.yaml.
#    Mirrors infra/ansible/.vault_password; gitignored.
echo '<choose-a-passphrase>' > .passphrase
chmod 600 .passphrase
export PULUMI_CONFIG_PASSPHRASE_FILE=$(pwd)/.passphrase

# 5. Stack + config (already done for the `prod` stack; this is for a rebuild)
pulumi stack init prod
pulumi config set          proxmoxve:endpoint https://192.0.2.70:8006
pulumi config set          proxmoxve:insecure true
pulumi config set --secret proxmoxve:apiToken 'terraform@pve!terraform=<token-secret>'
pulumi config set          node bthek1
pulumi config set          containerDatastore nvme4tb-lvm
pulumi config set --secret containerPassword '<root-password>'
pulumi config set          sshPublicKey 'ssh-ed25519 AAAA... rag'
```

Every shell that runs Pulumi needs `PULUMI_CONFIG_PASSPHRASE_FILE` exported (the
`just pu-*` recipes do this for you).

## Adopting the already-running containers

The containers exist and are serving production. Import them so Pulumi manages
them **in place** — never let it create new ones.

```bash
pulumi import proxmoxve:CT/container:Container stockmarket   bthek1/200 --yes
pulumi import proxmoxve:CT/container:Container stockmarketDb bthek1/201 --yes
pulumi preview          # must report: no changes, and NO replacements
```

Confirm the exact resource token first with
`pulumi package get-schema proxmoxve | grep -i container` rather than trusting
the string above.

## Day to day

```bash
just pu-preview    # what would change
just pu-up         # apply
just pu-refresh    # record out-of-band Proxmox changes (see warning below)
just pu-stack      # stack outputs
```

> **`pulumi up` can REBOOT the containers.** Measured during the migration: the
> apply touching `console` / `startOnBoot` restarted both containers (~10-15 s of
> API and database downtime) even though every value it wrote already matched the
> live config. A later tags-only apply did **not** restart anything. So the reboot
> depends on which fields change, and a value-neutral diff is not automatically a
> no-op - check `pu-preview`'s field list and treat anything beyond tags/metadata
> as a brief prod outage.

> **Moved a disk by hand in the Proxmox UI?** Update `containerDatastore` and run
> `just pu-refresh` **before** any `pu-up`. A plain apply against a stale
> `datastore_id` would try to replace both containers. `protect=True` on both
> resources turns that into a hard error rather than a wiped machine — leave it on.

There is deliberately no `pu-destroy` recipe. Deleting production containers
should require typing `pulumi destroy` by hand and removing `protect`.
