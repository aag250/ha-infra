#!/usr/bin/env python3
"""Write a small JSON health summary of this server for Home Assistant.

Runs as an unprivileged user from cron (every 5 minutes). Home Assistant reads
the file through a command_line sensor (see config/packages/homelab.yaml).
Root-only facts (NVMe SMART, snapshot age) are picked up from
/var/lib/homelab/host-extra.json if a root job writes it; otherwise omitted.
Added 2026-11-11.
"""
import datetime
import json
import os
import platform
import re
import socket
import struct
import subprocess
import time

# Where Home Assistant reads the feed (its /config is mounted from here). Override with HOST_HEALTH_OUT.
OUT = os.environ.get("HOST_HEALTH_OUT", os.path.expanduser("~/homeassistant/config/host_health.json"))
EXTRA = "/var/lib/homelab/host-extra.json"
EXPECTED = ["homeassistant", "adguardhome", "unifi", "unifi-db"]
DNS_TEST = "example.com"
DNS_BLOCKED_TEST = "googleads.g.doubleclick.net"


def run(cmd, timeout=25):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def apt_info():
    names = []
    for line in run(["/usr/bin/apt", "list", "--upgradable"]).splitlines():
        if "upgradable from" in line:
            names.append(line.split("/")[0])
    return len(names), names[:15]


def kernels():
    vers = []
    for f in os.listdir("/boot"):
        m = re.match(r"vmlinuz-(\d+\.\d+\.\d+-\d+)-generic$", f)
        if m:
            vers.append(m.group(1))
    key = lambda v: [int(x) for x in re.split(r"[.-]", v)]
    newest = max(vers, key=key) if vers else ""
    running = platform.release().replace("-generic", "")
    return running, newest


def failed_units():
    out = run(["/usr/bin/systemctl", "--failed", "--no-legend", "--plain"])
    names = [l.split()[0] for l in out.splitlines() if l.strip()]
    return names


def ssh_failures():
    out = run(["/usr/bin/journalctl", "-u", "ssh", "--since", "-24h", "--no-pager", "-q"])
    srcs = {}
    n = 0
    for line in out.splitlines():
        # Count each attempt once: an unknown user logs "Invalid user ..."; a known user with a
        # wrong password logs "Failed password for <user>" (the "for invalid user" duplicate is skipped).
        if "sshd" in line and (("Invalid user" in line and "Failed password" not in line)
                               or ("Failed password for" in line and "for invalid user" not in line)):
            n += 1
            m = re.search(r"from ([0-9a-fA-F.:]+)", line)
            if m:
                srcs[m.group(1)] = srcs.get(m.group(1), 0) + 1
    top = sorted(srcs.items(), key=lambda kv: -kv[1])[:5]
    return n, [f"{ip} ({c})" for ip, c in top]


def chrony():
    out = run(["/usr/bin/chronyc", "tracking"])
    stratum = offset_ms = None
    leap = ""
    m = re.search(r"Stratum\s*:\s*(\d+)", out)
    if m:
        stratum = int(m.group(1))
    m = re.search(r"System time\s*:\s*([0-9.]+) seconds (fast|slow)", out)
    if m:
        offset_ms = float(m.group(1)) * 1000 * (1 if m.group(2) == "fast" else -1)
    m = re.search(r"Leap status\s*:\s*(.+)", out)
    if m:
        leap = m.group(1).strip()
    synced = leap == "Normal" and stratum is not None and stratum < 16
    return stratum, offset_ms, synced


def containers():
    res = {n: "missing" for n in EXPECTED}
    for line in run(["/usr/bin/docker", "ps", "-a", "--format", "{{.Names}}|{{.State}}"]).splitlines():
        if "|" in line:
            name, state = line.split("|", 1)
            res[name] = state
    return res


def dns_query(name, server="127.0.0.1", timeout=3):
    """Minimal DNS A query. Returns (ok, ms, first_ipv4 or None)."""
    qid = os.getpid() & 0xFFFF
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    q = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    t0 = time.monotonic()
    try:
        s.sendto(header + q, (server, 53))
        data, _ = s.recvfrom(1500)
    except Exception:
        return False, None, None
    finally:
        s.close()
    ms = round((time.monotonic() - t0) * 1000, 1)
    if len(data) < 12 or struct.unpack(">H", data[:2])[0] != qid:
        return False, ms, None
    rcode = data[3] & 0x0F
    ancount = struct.unpack(">H", data[6:8])[0]
    ip = None
    if ancount and len(data) >= 4:
        ip = ".".join(str(b) for b in data[-4:])
    return rcode == 0 and ancount > 0, ms, ip


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    n_upg, upg_names = apt_info()
    running, newest = kernels()
    failed = failed_units()
    ssh_n, ssh_src = ssh_failures()
    stratum, offset_ms, synced = chrony()
    dns_ok, dns_ms, _ = dns_query(DNS_TEST)
    _, _, blocked_ip = dns_query(DNS_BLOCKED_TEST)
    data = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "epoch": int(now.timestamp()),
        "apt_upgradable": n_upg,
        "apt_upgradable_names": upg_names,
        "reboot_required": os.path.exists("/var/run/reboot-required"),
        "running_kernel": running,
        "newest_kernel": newest,
        "failed_units": len(failed),
        "failed_unit_names": failed,
        "ssh_failed_24h": ssh_n,
        "ssh_failed_sources": ssh_src,
        "time_stratum": stratum,
        "time_offset_ms": offset_ms,
        "time_synced": synced,
        "containers": containers(),
        "dns_ok": dns_ok,
        "dns_ms": dns_ms,
        "dns_blocking_ok": blocked_ip == "0.0.0.0",
    }
    try:
        with open(EXTRA) as f:
            data.update({k: v for k, v in json.load(f).items() if k in ("nvme", "backup")})
    except Exception:
        pass
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, OUT)


if __name__ == "__main__":
    main()
