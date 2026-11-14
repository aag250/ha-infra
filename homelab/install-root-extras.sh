#!/bin/bash
# Optional root job for the Home Assistant health feed. Review, then run:
#   sudo bash ~/homelab/install-root-extras.sh
# It does three things:
#   1. installs /usr/local/sbin/homelab-extra.sh, which every 10 minutes writes NVMe SMART health and the
#      age of the newest config snapshot to /var/lib/homelab/host-extra.json (world-readable, no secrets);
#   2. adds /etc/cron.d/homelab-extra to run it;
#   3. adds ~/homelab and ~/uptime-kuma/docker-compose.yml to the nightly config snapshot.
# Safe to run more than once. Undo: delete the two files above and the cron file.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
command -v jq >/dev/null && command -v smartctl >/dev/null || { echo "jq and smartctl are required."; exit 1; }

install -d -m 755 /var/lib/homelab

cat > /usr/local/sbin/homelab-extra.sh <<'EOF'
#!/bin/bash
# Root-only facts for the Home Assistant health feed (written every 10 minutes by cron).
set -u
OUT=/var/lib/homelab/host-extra.json
NV='{}'
J=$(/usr/sbin/smartctl -j -a /dev/nvme0 2>/dev/null || true)
if [ -n "$J" ]; then
  NV=$(echo "$J" | jq -c '{passed: (.smart_status.passed // false),
    critical_warning: (.nvme_smart_health_information_log.critical_warning // 0),
    percentage_used: (.nvme_smart_health_information_log.percentage_used // 0),
    unsafe_shutdowns: (.nvme_smart_health_information_log.unsafe_shutdowns // 0),
    media_errors: (.nvme_smart_health_information_log.media_errors // 0),
    power_on_hours: (.nvme_smart_health_information_log.power_on_hours // 0)}')
fi
BK='{}'
F=$(ls -t /var/backups/homelab/homelab-*.tar.gz 2>/dev/null | head -1 || true)
if [ -n "$F" ]; then
  BK=$(jq -nc --arg f "$(basename "$F")" --argjson m "$(stat -c %Y "$F")" --argjson n "$(date +%s)" --argjson s "$(stat -c %s "$F")" \
    '{file: $f, size_mb: ($s / 1048576 | floor), age_hours: ((($n - $m) / 360 | floor) / 10)}')
fi
jq -nc --argjson nvme "$NV" --argjson backup "$BK" '{nvme: $nvme, backup: $backup}' > "$OUT.tmp" \
  && mv "$OUT.tmp" "$OUT" && chmod 644 "$OUT"
EOF
chmod 755 /usr/local/sbin/homelab-extra.sh

printf '%s\n' '# Root-only health facts for Home Assistant (NVMe SMART, snapshot age)' \
  '*/10 * * * * root /usr/local/sbin/homelab-extra.sh' > /etc/cron.d/homelab-extra
chmod 644 /etc/cron.d/homelab-extra

/usr/local/sbin/homelab-extra.sh
echo "Wrote /var/lib/homelab/host-extra.json:"; cat /var/lib/homelab/host-extra.json

python3 - <<'PY'
p = "/usr/local/sbin/homelab-backup.sh"
s = open(p).read()
if "uptime-kuma/docker-compose.yml" in s:
    print("Snapshot script already includes the new folders.")
else:
    old = "unifi/docker-compose.yml unifi/init-mongo.sh unifi/.env"
    if old not in s:
        print("Could not find the expected line in the snapshot script; left unchanged.")
    else:
        open(p, "w").write(s.replace(old, old + " \\\n  uptime-kuma/docker-compose.yml homelab"))
        print("Snapshot script updated.")
PY
bash -n /usr/local/sbin/homelab-backup.sh && echo "Snapshot script syntax OK."
echo "Done. Home Assistant picks up the new values within about 7 minutes."
