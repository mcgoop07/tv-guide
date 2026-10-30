#!/usr/bin/env python3
"""Build a small TiviMate guide (custom.xml.gz) for US local stations and adult channels.
Downloads the epgshare01 guides, keeps only the channels in targets.json and renames them
to the provider's channel names, so TiviMate matches them automatically.
Run: python3 build.py [cache_dir]
"""
import gzip, json, os, subprocess, sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'cache')
OUT = os.path.join(HERE, 'public', 'custom.xml.gz')
URL = 'https://epgshare01.online/epgshare01/epg_ripper_{}.xml.gz'
SUFFIX = {'us_locals1': 'US_LOCALS1', 'us2': 'US2', 'uk': 'UK1', 'cz': 'CZ1', 'gr': 'GR1', 'es': 'ES1',
          'be': 'BE2', 'de': 'DE1', 'at': 'AT1', 'hr': 'HR1', 'dk': 'DK1', 'al': 'AL1', 'br': 'BR1'}

targets = json.load(open(os.path.join(HERE, 'targets.json'), encoding='utf-8'))
wanted = {}  # source id -> list of target indexes
for n, t in enumerate(targets):
    for s in t['sources']:
        wanted.setdefault(s, []).append(n)


def fetch(name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name + '.xml.gz')
    # curl uses the Mac's own certificates (python.org Python often has none).
    subprocess.run(['curl', '-sSfL', '-m', '600', '-A', 'Mozilla/5.0', '-o', path + '.part', URL.format(name)], check=True)
    os.replace(path + '.part', path)
    return path


# Read every needed programme, grouped by source channel id.
progs = {}
for name in sorted({SUFFIX[s.rsplit('.', 1)[1]] for s in wanted}):
    try:
        path = fetch(name)
    except Exception as e:
        print('could not download', name, e)
        path = os.path.join(CACHE, name + '.xml.gz')
        if not os.path.exists(path):
            continue
    for _, el in ET.iterparse(gzip.open(path), events=('end',)):
        if el.tag == 'programme':
            ch = el.get('channel')
            if ch in wanted:
                progs.setdefault(ch, []).append(el)
            else:
                el.clear()

# Each target takes the source with the most listings (some only carry a placeholder).
root = ET.Element('tv', {'generator-info-name': 'home custom guide'})
chans, body = [], []
for t in targets:
    src = max(t['sources'], key=lambda s: len(progs.get(s, [])))
    if len(progs.get(src, [])) < 3:
        print('no real listings for', t['name'])
        continue
    c = ET.Element('channel', {'id': t['id']})
    ET.SubElement(c, 'display-name').text = t['name']
    chans.append(c)
    for p in progs[src]:
        q = ET.Element('programme', dict(p.attrib, channel=t['id']))
        q.extend(list(p))
        body.append(q)
root.extend(chans + body)
with gzip.open(OUT + '.part', 'wb') as f:
    ET.ElementTree(root).write(f, encoding='utf-8', xml_declaration=True)
os.replace(OUT + '.part', OUT)
print(f'{len(chans)} of {len(targets)} channels, {len(body)} programmes -> {OUT}')
