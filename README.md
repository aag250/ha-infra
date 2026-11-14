# ha-infra

Home Assistant configuration and related infrastructure for the home network.

## Layout

`homeassistant/config/` mirrors the Home Assistant `/config` directory on the NUC
(`~/homeassistant/config`). Copy files to the same relative path to deploy.

| Path | Purpose |
|---|---|
| `packages/network.yaml` | DNS filtering control: pause-length helper, pause timer, pause/resume scripts, automations |
| `packages/kids.yaml` | not stored here: generated per site by `adguard/gen_kids_package.py` (see below) |
| `dashboards/network.yaml` | "Network" dashboard (YAML mode): DNS filtering and Kids network views |

No secrets belong in this repo. Keep them in `secrets.yaml` on the host and reference them with `!secret`.

## Network dashboard (AdGuard Home)

Requires the built-in **AdGuard Home** integration (Settings → Devices & services),
which provides `switch.adguard_home_protection`.

`configuration.yaml` must load packages and register the dashboard:

```yaml
homeassistant:
  packages: !include_dir_named packages

lovelace:
  dashboards:
    dashboard-network:
      mode: yaml
      title: Network
      icon: mdi:lan
      show_in_sidebar: true
      require_admin: false
      filename: dashboards/network.yaml
```

Behaviour: an on/off toggle for DNS filtering, plus "turn off for N minutes"
(default 15, adjustable 1-240). The pause timer restores across restarts and
re-enables filtering when it ends. A plain "off" stays off until turned back on.

Deploying changes: validate with
`docker exec homeassistant python -m homeassistant --script check_config -c /config`,
then restart Home Assistant (a new dashboard registration needs a restart).

## Generic tools

`homelab/` holds reusable host scripts with no site-specific settings:
- `host-health.py`: writes a small JSON health feed (updates, kernel, SSH failures, containers, DNS checks).
  Run it from cron; set `HOST_HEALTH_OUT` to choose the output path.
- `install-root-extras.sh`: optional root job that adds disk/backup health to the feed.

`.gitignore` keeps secrets, env files, backups and databases out of the repo.

## Kids network controls (AdGuard Home)

Per-client "Kids" restrictions and the matching Home Assistant switches. No addresses are stored in this repo;
supply them when you run the scripts (on the host that can reach AdGuard):

```
export KIDS_CIDR=<kids subnet in CIDR form>
export HA_ADGUARD_URL=http://<adguard host>:<admin port>   # as Home Assistant reaches it
python3 adguard/apply-kids-restrictions.py                 # blocked services, parental control, bypass rules
python3 adguard/gen_kids_package.py > <ha config>/packages/kids.yaml
```

Needs a persistent AdGuard client named `Kids`, an AdGuard login in `~/.adguard-cred` (two lines),
and `adguard_user` / `adguard_password` in Home Assistant's `secrets.yaml`. The dashboard in
`homeassistant/config/dashboards/network.yaml` expects the entities these scripts create.
