#!/usr/bin/env python3
"""Build a small TiviMate guide (custom.xml.gz) for channels the provider's own guide misses
(US locals and cable, Canada, Australia, UK regional/extra, adult).
Downloads the epgshare01 guides, keeps only the channels in targets.json and renames them
to the provider's channel names, so TiviMate matches them automatically.
Run: python3 build.py [cache_dir]
"""
import copy, gzip, json, os, subprocess, sys, time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'cache')
OUT = os.path.join(HERE, 'public', 'custom.xml.gz')
URL = 'https://epgshare01.online/epgshare01/epg_ripper_{}.xml.gz'
SUFFIX = {'us_locals1': 'US_LOCALS1', 'us2': 'US2', 'uk': 'UK1', 'cz': 'CZ1', 'gr': 'GR1', 'es': 'ES1',
          'be': 'BE2', 'de': 'DE1', 'at': 'AT1', 'hr': 'HR1', 'dk': 'DK1', 'al': 'AL1', 'br': 'BR1',
          'us': 'FANDUEL1', 'ca2': 'CA2', 'au': 'AU1', 'ie': 'IE1', 'in': 'IN1'}


# A source is "channel.id" (file picked from its suffix) or "FILE|channel.id" when the suffix is shared.
def src_file(s):
    return s.split('|', 1)[0] if '|' in s else SUFFIX[s.rsplit('.', 1)[1]]


def src_id(s):
    return s.split('|', 1)[-1]


# --- English translation for foreign channels that broadcast in English (targets with "translate": true) ---
# All offline, no accounts or limits: Argos Translate for most languages, and the Helsinki-NLP
# South Slavic model (opus-mt-zls-en) for Croatian, Serbian (incl. Cyrillic) and Bosnian, which Argos lacks.
# Results are cached between runs (tcache/translations.json), so each day only new programmes are translated;
# anything left untranslated keeps its original text and is tried again the next day.
LANG = {'NL1': 'nl', 'BE2': 'fr', 'PT1': 'pt', 'RO1': 'ro', 'RO2': 'ro', 'HR1': 'hr', 'RS1': 'sr',
        'BA1': 'bs', 'AL1': 'sq', 'PL1': 'pl', 'BG1': 'bg', 'ES1': 'es'}
ARGOS = {'nl', 'fr', 'pt', 'ro', 'sq', 'pl', 'bg', 'es'}
TCACHE = os.environ.get('TRANSLATION_CACHE', os.path.join(HERE, 'tcache', 'translations.json'))
TIME_LIMIT = 40 * 60  # stop translating after this long; the rest waits for the next run


def south_slavic():
    """Return a function translating a list of hr/sr/bs texts to English (None if unavailable)."""
    try:
        from transformers import MarianMTModel, MarianTokenizer
        name = 'Helsinki-NLP/opus-mt-zls-en'
        tok, model = MarianTokenizer.from_pretrained(name), MarianMTModel.from_pretrained(name)
    except Exception as e:
        print('south slavic model unavailable', e)
        return None

    def run(texts):
        enc = tok(texts, return_tensors='pt', padding=True, truncation=True, max_length=512)
        return tok.batch_decode(model.generate(**enc, max_new_tokens=400), skip_special_tokens=True)
    return run


def argos(lang):
    """Return an Argos translator lang -> English, downloading the model if needed (None if unavailable)."""
    try:
        import argostranslate.package as pkg
        import argostranslate.translate as tr
        if not any(p.from_code == lang and p.to_code == 'en' for p in pkg.get_installed_packages()):
            pkg.update_package_index()
            p = next(p for p in pkg.get_available_packages() if p.from_code == lang and p.to_code == 'en')
            pkg.install_from_path(p.download())
        return tr.get_translation_from_codes(lang, 'en')
    except Exception as e:
        print('argos unavailable for', lang, e)
        return None


def translate_guide(items):
    if not items:
        return
    known = json.load(open(os.path.join(HERE, 'known_titles.json'), encoding='utf-8'))
    try:
        old = json.load(open(TCACHE, encoding='utf-8'))
    except Exception:
        old = {}
    used, todo = {}, {}
    for lang, p in items:
        for el in p:
            if el.tag in ('title', 'sub-title', 'desc') and el.text and el.text.strip():
                text = ' '.join(el.text.split())
                key = lang + '|' + text
                if el.tag == 'title' and text in known:
                    continue
                if key in old:
                    used[key] = old[key]
                else:
                    todo.setdefault(lang, set()).add(text)
    print('translation: %d cached, %d new' % (len(used), sum(map(len, todo.values()))))
    start = time.time()

    def out_of_time():
        return time.time() - start > TIME_LIMIT

    for lang, texts in todo.items():
        if lang in ARGOS:
            tr = argos(lang)
            for text in sorted(texts):
                if tr is None or out_of_time():
                    break
                try:
                    used[lang + '|' + text] = tr.translate(text)
                except Exception as e:
                    print('argos failed on a line:', e)
            continue
        tr = south_slavic()
        texts = sorted(texts)
        for i in range(0, len(texts), 16):
            if tr is None or out_of_time():
                break
            try:
                for a, b in zip(texts[i:i + 16], tr(texts[i:i + 16])):
                    used[lang + '|' + a] = b
            except Exception as e:
                print('south slavic model failed on a batch:', e)
    for lang, p in items:
        for el in p:
            if el.tag in ('title', 'sub-title', 'desc') and el.text and el.text.strip():
                text = ' '.join(el.text.split())
                new = known.get(text) if el.tag == 'title' else None
                new = new or used.get(lang + '|' + text)
                if new:
                    el.text = new
                    el.set('lang', 'en')
    os.makedirs(os.path.dirname(TCACHE), exist_ok=True)
    with open(TCACHE, 'w', encoding='utf-8') as f:
        json.dump(used, f, ensure_ascii=False, indent=0)  # keeps only what's still in use
    print('translation: %d strings in English (%d min)' % (len(used), (time.time() - start) // 60))


targets = json.load(open(os.path.join(HERE, 'targets.json'), encoding='utf-8'))
wanted = {}  # source id -> list of target indexes
for n, t in enumerate(targets):
    for s in t['sources']:
        wanted.setdefault(src_id(s), []).append(n)


def fetch(name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name + '.xml.gz')
    # curl uses the Mac's own certificates (python.org Python often has none).
    subprocess.run(['curl', '-sSfL', '-m', '600', '-A', 'Mozilla/5.0', '-o', path + '.part', URL.format(name)], check=True)
    os.replace(path + '.part', path)
    return path


# Read every needed programme, grouped by source channel id.
progs = {}
for name in sorted({src_file(s) for t in targets for s in t['sources']}):
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
to_translate = []  # (language, programme) for channels marked "translate"
for t in targets:
    best = max(t['sources'], key=lambda s: len(progs.get(src_id(s), [])))
    src = src_id(best)
    if len(progs.get(src, [])) < 3:
        print('no real listings for', t['name'])
        continue
    c = ET.Element('channel', {'id': t['id']})
    ET.SubElement(c, 'display-name').text = t['name']
    chans.append(c)
    for p in progs[src]:
        q = ET.Element('programme', dict(p.attrib, channel=t['id']))
        if t.get('translate'):
            q.extend(copy.deepcopy(list(p)))  # own copy, so other channels keep the original text
            to_translate.append((LANG.get(src_file(best), 'auto'), q))
        else:
            q.extend(list(p))
        body.append(q)

translate_guide(to_translate)
root.extend(chans + body)
with gzip.open(OUT + '.part', 'wb') as f:
    ET.ElementTree(root).write(f, encoding='utf-8', xml_declaration=True)
os.replace(OUT + '.part', OUT)
print(f'{len(chans)} of {len(targets)} channels, {len(body)} programmes -> {OUT}')
