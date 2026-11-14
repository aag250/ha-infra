import json, subprocess, base64, sys
"""Apply per-client "Kids" restrictions in AdGuard Home (blocked services, parental control, bypass rules).
Settings come from the environment (nothing site-specific is stored in this repo):
  KIDS_CIDR      required, e.g. the kids subnet in CIDR form
  ADGUARD_URL    default http://127.0.0.1:8081
  ADGUARD_CRED   default ~/.adguard-cred (line 1 user, line 2 password)
The persistent client named "Kids" must already exist."""
import os
cred = open(os.path.expanduser(os.environ.get('ADGUARD_CRED', '~/.adguard-cred'))).read().split('\n')
U, P = cred[0], cred[1]
B = os.environ.get('ADGUARD_URL', 'http://127.0.0.1:8081') + '/control'
def call(path, body=None):
    cmd = ['curl','-s','-u',f'{U}:{P}','-H','Content-Type: application/json']
    if body is not None: cmd += ['-d', json.dumps(body)]
    cmd.append(B+'/'+path)
    return subprocess.check_output(cmd).decode()

svc = [s['id'] for s in json.loads(call('blocked_services/all'))['blocked_services']]
# Left allowed on purpose: infrastructure / app store / school-work collaboration / shopping with shared AWS domains
keep = {'cloudflare','playstore','microsoft_teams','slack','box','dropbox','amazon'}
blocked = [s for s in svc if s not in keep]

client = json.loads(call('clients'))['clients'][0]
assert client['name'] == 'Kids'
client.update(blocked_services=blocked, parental_enabled=True, safebrowsing_enabled=True, filtering_enabled=True)
client['safe_search'] = {k: True for k in ('enabled','bing','duckduckgo','ecosia','google','pixabay','yandex','youtube')}
print('update client:', call('clients/update', {'name':'Kids','data':client}) or 'ok', '|', len(blocked), 'services blocked, kept:', sorted(keep))

CIDR = os.environ['KIDS_CIDR']
CL = f"$client='{CIDR}'"
bypass = """dns.google dns.google.com cloudflare-dns.com one.one.one.one dns.cloudflare.com mozilla.cloudflare-dns.com
dns.quad9.net dns9.quad9.net dns10.quad9.net doh.opendns.com dns.nextdns.io dns.adguard-dns.com dns.adguard.com
doh.cleanbrowsing.org dns.sb doh.dns.sb doh.pub dns.alidns.com doh.libredns.gr dns.twnic.tw doh.mullvad.net
use-application-dns.net
nordvpn.com nordvpn.net expressvpn.com protonvpn.com windscribe.com surfshark.com hide.me tunnelbear.com
hotspotshield.com privateinternetaccess.com cyberghostvpn.com ipvanish.com mullvad.net psiphon.ca psiphon3.com
torproject.org hidemy.name hide.me proxysite.com croxyproxy.com kproxy.com hidester.com vpnbook.com""".split()
rules = ['||cats.com^'] + [f'||{d}^{CL}' for d in dict.fromkeys(bypass)]
print('set_rules:', call('filtering/set_rules', {'rules': rules}) or 'ok', len(rules), 'rules')
