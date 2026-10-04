"""Capture the homepage's three feature windows from the isolated demo environment (no UI mocks).

  backend/.venv/bin/python website/scripts/capture-homepage.py --demo-dir /private/path/mosael-demo

Uses the same Playwright runtime and demo environment as record-doc-media.py (start it with
seed-doc-demo.py up). The token file is a local JSON string; never pass credentials on the command line
or point this at a personal workspace.
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / 'website/public/media'
VIEWPORT = {'width': 1440, 'height': 940}


def load_seed():
    spec = importlib.util.spec_from_file_location('seed_doc_demo', Path(__file__).with_name('seed-doc-demo.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    seed = load_seed()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--demo-dir', type=Path, required=True, help="the seed script's --dir")
    parser.add_argument('--app', default=f'http://127.0.0.1:{seed.APP_PORT}')
    parser.add_argument('--api', default=f'http://127.0.0.1:{seed.API_PORT}')
    args = parser.parse_args()
    if not shutil.which('pngquant'):
        parser.error('pngquant is required for the screenshots (brew install pngquant).')
    for url in [args.app, args.api]:
        if urlparse(url).hostname not in ['127.0.0.1', 'localhost'] or urlparse(url).port in (8800, 5173):
            parser.error('Capture only the isolated local demo environment.')
    token = json.loads((args.demo_dir / 'token.json').read_text())
    fixture = json.loads((args.demo_dir / 'fixture.json').read_text())
    manifest_path = PUBLIC / 'capture-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    version = json.loads((ROOT / 'package.json').read_text())['version']
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for locale in ['zh', 'en']:
            F = fixture['locales'][locale]
            for name, theme, font, route in [
                ('boards', 'light', 'caveat' if locale == 'en' else 'wenkai', 'boards?board=' + F['board']),
                ('editor', 'dark', 'newsreader', 'editor?p=' + F['project']),
                ('scenes', 'dark', 'space-grotesk', 'scenes?scene=' + F['scene']),
            ]:
                print(f'Capturing {locale}/{name} ({theme}, {font})', flush=True)
                context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2, color_scheme=theme)
                page = context.new_page()
                page.goto(args.app, wait_until='domcontentloaded')
                page.evaluate('''([api, token, theme, font, locale, workspace]) => {
                    localStorage.setItem('mosael.server.url', api);
                    localStorage.setItem('mosael.auth.token', token);
                    localStorage.setItem('mosael.preferences', JSON.stringify({theme, font, locale}));
                    localStorage.setItem('mosael:workspace', workspace);
                    localStorage.setItem('mosael.sidebar.collapsed', 'true');
                    localStorage.setItem('mosael.editor.panels.v2', JSON.stringify({left:{media:250},right:260,timeline:300}));
                }''', [args.api, token, theme, font, 'zh-CN' if locale == 'zh' else 'en-US', F['workspace']])
                page.goto(args.app + '/#/' + route, wait_until='networkidle')
                page.reload(wait_until='networkidle')
                if name == 'boards':
                    page.locator('.react-flow__node').first.wait_for()
                    page.wait_for_timeout(1500)
                    page.get_by_role('button', name='适应画布' if locale == 'zh' else 'Fit to view', exact=True).click()
                elif name == 'scenes':
                    page.get_by_role('button', name='俯瞰全场' if locale == 'zh' else 'Overview', exact=True).click()
                else:
                    page.get_by_role('button', name=seed.TEXT[locale]['title_text'], exact=True).wait_for()
                page.wait_for_timeout(2500)
                page.evaluate('document.fonts.ready')
                target = PUBLIC / 'homepage' / locale / (name + '.png')
                target.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(target))
                # Same quantization as the documentation screenshots (record-doc-media.py): resolution unchanged.
                result = subprocess.run(['pngquant', '--quality=80-100', '--speed', '1', '--skip-if-larger', '--strip',
                                         '--force', '--ext', '.png', str(target)], capture_output=True, text=True)
                if result.returncode not in (0, 98, 99):
                    raise RuntimeError(f'pngquant failed on {target}: {result.stderr.strip()}')
                manifest['captures'][str(target.relative_to(PUBLIC))] = {
                    'scene': name, 'locale': locale, 'theme': theme, 'font': font,
                    'version': version, 'sourceCommit': commit, 'capturedAt': datetime.now(timezone.utc).isoformat(),
                    'viewport': VIEWPORT, 'deviceScaleFactor': 2, 'bytes': target.stat().st_size,
                    'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                    'note': 'Live app screenshot from the isolated demo environment (seed-doc-demo.py) with a supported '
                            'appearance preference. No mocked UI.'}
                context.close()
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        browser.close()


if __name__ == '__main__':
    main()
