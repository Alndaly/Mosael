"""Verify docs navigation against a running website; save real browser screenshots.

Run from the repository root with backend/.venv/bin/python scripts/verify-docs-navigation.py.
Start a production website first (pnpm --dir website start --port 3002).
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-url', default='http://127.0.0.1:3002')
parser.add_argument('--output', type=Path, default=ROOT / 'output/playwright')
args = parser.parse_args()
OUT = args.output
OUT.mkdir(parents=True, exist_ok=True)
expected_pages = len(list((ROOT / 'website/content/docs/en').rglob('*.mdx')))
results=[]
with sync_playwright() as p:
 b=p.chromium.launch()
 for locale in ['en','zh']:
  for theme in ['light','dark']:
   for width in [390,768,1100,1440]:
    print(locale,theme,width,flush=True)
    c=b.new_context(viewport={'width':width,'height':900},color_scheme=theme)
    c.add_init_script("localStorage.setItem('theme', " + json.dumps(theme) + ")")
    page=c.new_page();errors=[];page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto(f'{args.base_url.rstrip("/")}/{locale}/docs/start/intro',wait_until='domcontentloaded')
    page.wait_for_function("document.readyState === 'complete'")
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert page.locator('h1').bounding_box()['y'] < 250
    if width<1280:
     label='All docs' if locale=='en' else '文档目录'
     toc='On this page' if locale=='en' else '本页目录'
     if width<1024:
      button=page.get_by_role('button',name=label,exact=True);button.click()
      dialog=page.get_by_role('dialog');expect(dialog).to_be_visible()
      assert dialog.get_by_role('link').count()==expected_pages
      assert dialog.locator('a[aria-current=page]').count()==1
      page.screenshot(path=str(OUT/f'docs-menu-{locale}-{theme}-{width}.png'))
      page.keyboard.press('Escape');expect(dialog).not_to_be_visible();expect(button).to_be_focused()
      button.click();page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");page.mouse.click(1,1);expect(dialog).not_to_be_visible()
      button.click();dialog.get_by_role('link',name='3D scenes & animation' if locale=='en' else '3D 场景与动画',exact=True).click()
      page.wait_for_url('**/guides/scenes');expect(dialog).not_to_be_visible()
     btn=page.get_by_role('button',name=toc,exact=True);btn.click();dialog=page.get_by_role('dialog');expect(dialog).to_be_visible()
     anchor=dialog.get_by_role('link').last;href=anchor.get_attribute('href');anchor.click();expect(dialog).not_to_be_visible()
     assert page.evaluate('decodeURIComponent(location.hash)')==href
     assert page.evaluate('(id)=>document.getElementById(decodeURIComponent(id.slice(1))).getBoundingClientRect().top',href)>0
     btn.click();page.set_viewport_size({'width':1440,'height':900});expect(dialog).not_to_be_visible()
     assert page.evaluate('getComputedStyle(document.body).pointerEvents')!='none'
     page.set_viewport_size({'width':width,'height':900})
    page.goto(f'{args.base_url.rstrip("/")}/{locale}/docs/start/intro',wait_until='domcontentloaded')
    page.screenshot(path=str(OUT/f'docs-{locale}-{theme}-{width}.png'))
    assert not errors,errors
    results.append({'locale':locale,'theme':theme,'width':width,'passed':True})
    c.close()
 b.close()
(OUT/'docs-navigation-results.json').write_text(json.dumps(results,indent=2))
print('PASS',len(results))
