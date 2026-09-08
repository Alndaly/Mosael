"""Capture real, isolated demo windows for the homepage (no UI mocks).

Uses the same Playwright runtime as record-doc-media.py. Token files are local
JSON strings. Demo fixtures contain the scene, board and project IDs; never
pass credentials on the command line or use a personal workspace.
"""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'website/public/media'
VIEWPORT = {'width': 1440, 'height': 940}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', default='http://127.0.0.1:5173')
    parser.add_argument('--scene-api', required=True)
    parser.add_argument('--scene-token', type=Path, required=True)
    parser.add_argument('--editor-api', required=True)
    parser.add_argument('--editor-token', type=Path, required=True)
    parser.add_argument('--editor-fixture', type=Path, required=True)
    args = parser.parse_args()
    for url in [args.app, args.scene_api, args.editor_api]:
        if urlparse(url).hostname not in ['127.0.0.1', 'localhost']:
            parser.error('Capture only isolated local demo servers.')
    editor = json.loads(args.editor_fixture.read_text())
    manifest_path = PUBLIC / 'capture-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    version = json.loads((ROOT / 'package.json').read_text())['version']
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for locale in ['zh', 'en']:
            for name, theme, font, api, token_path, route in [
                ('boards', 'light', 'caveat' if locale == 'en' else 'wenkai', args.editor_api, args.editor_token, 'boards'),
                ('editor', 'dark', 'newsreader', args.editor_api, args.editor_token, 'editor?p=' + editor['project']),
                ('scenes', 'dark', 'space-grotesk', args.scene_api, args.scene_token, 'scenes'),
            ]:
                print(f'Capturing {locale}/{name} ({theme}, {font})', flush=True)
                context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2, color_scheme=theme)
                page = context.new_page()
                page.goto(args.app, wait_until='domcontentloaded')
                page.evaluate('''([api, token, theme, font, locale]) => {
                    localStorage.setItem('mosael.server.url', api);
                    localStorage.setItem('mosael.auth.token', token);
                    localStorage.setItem('mosael.preferences', JSON.stringify({theme, font, locale}));
                    localStorage.setItem('mosael.sidebar.collapsed', 'true');
                    localStorage.setItem('mosael.editor.panels.v2', JSON.stringify({left:{media:250},right:260,timeline:260}));
                }''', [api, json.loads(token_path.read_text()), theme, font, 'zh-CN' if locale == 'zh' else 'en-US'])
                page.reload(wait_until='networkidle')
                page.goto(args.app + '/#/' + route, wait_until='networkidle')
                if name == 'boards':
                    page.get_by_text('镜头与灵感 · Story study', exact=True).click()
                    page.wait_for_timeout(1500)
                    page.get_by_role('button', name='适应画布' if locale == 'zh' else 'Fit to view', exact=True).click()
                elif name == 'scenes':
                    page.get_by_text('三间展厅 · Camera study', exact=True).click()
                    page.get_by_role('button', name='俯瞰全场', exact=True).click()
                else:
                    page.locator('[data-tool] [role=button][title="林间光影 · Forest"]').first.wait_for()
                page.wait_for_timeout(2000)
                page.evaluate('document.fonts.ready')
                target = PUBLIC / 'homepage' / locale / (name + '.png')
                target.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(target))
                manifest['captures'][str(target.relative_to(PUBLIC))] = {
                    'scene':name,'locale':locale,'theme':theme,'font':font,
                    'version':version,'sourceCommit':commit,'capturedAt':datetime.now(timezone.utc).isoformat(),
                    'viewport':VIEWPORT,'deviceScaleFactor':2,'bytes':target.stat().st_size,
                    'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                    'note':'Live app screenshot using isolated demo data and supported appearance preferences. No mocked UI.'}
                context.close()
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
        browser.close()

if __name__ == '__main__':
    main()
