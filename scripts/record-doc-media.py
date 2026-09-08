#!/usr/bin/env python3
"""Capture current Mosael UI, in both languages and themes, from an isolated demo backend.

No DOM replacement, fabricated agent responses, provider calls, or publishing actions.
Screenshots are native Playwright captures. GIFs and MP4s come from actual browser video,
including hover, typing, scrolling and popup transitions. A failed scene stops the run so
an old asset cannot silently pass as a fresh recording.

Example:
  backend/.venv/bin/python scripts/record-doc-media.py --api http://127.0.0.1:8812 \
    --token-file /tmp/demo-token.json --fixture /tmp/demo-capture.json
The fixture contains project, board, workflow IDs and assets (forest, narration, forest-frame).
The token file is a JSON string, never included in the public capture manifest.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'website/public/media'
VIEWPORT = {'width':1440, 'height':900}

class Capture:
    def __init__(self, page, locale, theme, fixture):
        self.page, self.locale, self.theme, self.fixture = page, locale, theme, fixture
        self.outputs = []
        self.start = None
    def word(self, zh, en): return zh if self.locale == 'zh' else en
    def hold(self, ms=850): self.page.wait_for_timeout(ms)
    def button(self, zh, en=None): return self.page.get_by_role('button', name=self.word(zh,en or zh), exact=True)
    def click(self, zh, en=None): self.button(zh,en).first.click(); self.hold()
    def goto(self, view):
        self.page.goto('http://127.0.0.1:5173/#/'+view, wait_until='networkidle')
        self.page.wait_for_function('document.fonts.status === "loaded"')
        self.hold(800)
    def path(self, kind, name):
        p=PUBLIC/kind
        if self.locale=='en': p=p/'en'
        if self.theme=='dark': p=p/'dark'
        p.mkdir(parents=True,exist_ok=True)
        return p/name
    def shot(self,name):
        target=self.path('screens', name+'.png')
        self.page.screenshot(path=str(target))
        self.outputs.append(target)
    def begin(self): self.start=time.monotonic(); self.hold(1000)
    def escape(self): self.page.keyboard.press('Escape'); self.hold(550)
    def editor(self):
        self.goto('editor?p='+self.fixture['project'])
        self.page.locator('[data-tool] [role=button][title="林间光影 · Forest"]').first.wait_for()
    def setting(self,zh,en): self.goto('settings');self.click(zh,en)
    def workflow(self):
        self.goto('workflows');self.button('口播与访谈智能整理').click();self.hold(1400)
    def board(self):
        self.goto('boards'); self.page.get_by_text('镜头与灵感 · Story study',exact=True).click();self.hold(1200)

def home(c):
    c.goto('home'); c.shot('home'); c.begin()
    c.click('全部项目','All projects');c.hold();c.click('最近编辑','Recently edited')
    c.page.get_by_role('button',name=re.compile('Big Buck Bunny')).first.click();c.hold(1700)

def media(c):
    c.goto('media');c.shot('media');c.begin()
    c.click('从链接导入','From link');c.shot('url-import');c.hold(1300);c.escape()
    for kind,key,name in [('视频','forest','media-video'),('音频','narration','media-audio'),('图片','forest-frame','media-image')]:
        asset=c.fixture['assets'][key]
        # Cards expose the name as a button; use the actual asset title, not positional CSS.
        title={'forest':'林间光影 · Forest','narration':'剪辑旁白 · Narration','forest-frame':'林间光影 · Frame 01'}[key]
        c.page.get_by_role('button',name=title,exact=True).first.click();c.hold(1100);c.shot(name)
        c.hold(1200);c.escape()

def editor(c):
    c.editor();c.button('素材','Media').last.click();c.hold(1200);c.shot('editor');c.begin()
    clips=c.page.locator('[data-tool] [role=button][title]')
    clips.first.click();c.hold();c.shot('editor-inspector')
    if clips.count()>1:clips.nth(1).click();c.hold()
    c.click('播放 / 暂停 (Space)','Play / pause (Space)');c.hold(2000)
    c.click('播放 / 暂停 (Space)','Play / pause (Space)');c.hold()

def subtitles(c):
    c.editor();c.click('字幕','Subtitles');c.shot('subtitles');c.begin()
    c.page.get_by_role('button',name=re.compile('配音|Dub')).last.click();c.hold();c.shot('subtitle-dub');c.hold(1700)
    c.escape();c.click('逐字稿','Transcript');c.shot('transcript')

def ai(c):
    c.goto('ai');c.shot('ai-chat');c.begin()
    c.page.get_by_role('tab',name=c.word('轨迹','Trace'),exact=True).click();c.hold();c.shot('agent-trace');c.hold(1500)
    c.page.get_by_role('tab',name=c.word('对话','Conversation'),exact=True).last.click();c.hold()
    c.page.get_by_role('tab',name=c.word('生成','Generate'),exact=True).click();c.hold();c.shot('ai-generate');c.hold(1500)

def workflows(c):
    c.goto('workflows');c.shot('workflow-list');c.workflow();c.shot('workflows');c.begin()
    c.click('添加节点','Add node');c.shot('workflow-add-node');c.hold(1400);c.escape()
    node=c.page.locator('.react-flow__node').filter(has_text='生成带时间码逐字稿').first
    node.click();c.hold(1100);c.shot('workflow-node');c.hold(1400)

def boards(c):
    c.board();c.shot('boards');c.begin()
    # Pan the real canvas so the selected node's form fits in the recording viewport.
    c.page.mouse.move(850,200);c.page.mouse.down();c.page.mouse.move(450,200,steps=20);c.page.mouse.up();c.hold()
    node=c.page.locator('.react-flow__node[data-id="draft-video"]');node.click();c.hold(1100)
    box=c.page.locator('[contenteditable=true]').last
    draft='让画面中的阳光缓缓移动 / Let the sunlight move gently'
    box.fill(draft);c.hold();c.shot('board-form')
    box=c.page.locator('[contenteditable=true]').last
    box.click();c.page.keyboard.press('End');c.page.keyboard.type(' @',delay=200);c.hold(1000);c.shot('board-mention');c.hold(1400);c.escape()
    # Restore the typed draft so each language/theme starts from the same source data.
    box.fill(draft);c.hold()

def plugins(c):
    c.goto('plugins');c.shot('plugins');c.begin()
    c.click('新建连接','New connection');c.hold(1200);c.shot('plugin-connection');c.escape()
    c.page.get_by_role('button',name=re.compile('百度网盘|Baidu Netdisk')).first.click();c.hold(1100)


def publishing(c):
    c.goto('publish');c.shot('publish');c.begin()
    c.click('新建发布','New publish');c.shot('publish-form');c.hold(1600);c.escape()
    c.goto('browser-pool');c.shot('browser-pool');c.click('添加账号','Add account');c.shot('browser-account');c.hold(1600);c.escape()

def scheduler(c):
    c.goto('scheduler');c.shot('scheduler');c.begin()
    c.page.get_by_role('button',name=re.compile('每天整理创作素材')).first.click();c.hold(1500)
    c.click('新建任务','New task');c.shot('scheduler-form');c.hold(1500);c.escape()

def settings(c):
    c.goto('settings');c.shot('settings');c.begin()
    c.click('AI 对话','AI chat');c.shot('settings-models');c.hold(1300)
    c.click('AI 绘图','AI image');c.hold(1300)
    c.click('转写模型','Transcription models');c.shot('settings-asr');c.hold(1300)

def appearance(c):
    c.setting('外观','Appearance');c.shot('settings-appearance');c.begin()
    for zh,en in [('手写连笔 · Caveat','Handwritten · Caveat'),('手写笔记 · Kalam','Notebook · Kalam'),('默认 · Inter','Default · Inter')]:
        c.page.locator('label').filter(has=c.page.get_by_role('radio',name=c.word(zh,en),exact=True)).click();c.hold(1500)
    c.shot('settings-fonts')

def login(c):
    c.page.evaluate('localStorage.removeItem("mosael.auth.token")')
    c.page.reload(wait_until='networkidle');c.hold(1200);c.shot('login');c.begin()
    c.page.get_by_role('textbox').first.fill('creator');c.hold(1800)

def scenes(c):
    c.goto('scenes')
    c.page.get_by_text('三间展厅 · Camera study',exact=True).click();c.hold(1500)
    c.shot('scenes');c.begin()
    c.click('添加物体');c.shot('scene-add');c.hold(900);c.escape()
    c.click('机位视角');c.shot('scene-camera');c.hold(1100)
    c.click('俯瞰全场');c.click('播放镜头');c.hold(2200);c.click('暂停');c.shot('scene-observation')
    c.click('自由视角');c.click('回到起点')
    c.page.locator('button').filter(has_text=re.compile('^产品占位球$')).last.click();c.hold()
    c.page.keyboard.press('i');c.hold();c.click('跳到结尾');c.page.keyboard.press('i');c.hold()
    c.shot('scene-keyframes')

def notes(c):
    c.goto('notes?note='+c.fixture['note']);c.shot('notes');c.begin()
    c.click('阅读','Read');c.hold(1100);c.shot('notes-read')
    c.click('Markdown');c.hold(1300);c.shot('notes-markdown')
    c.click('编辑','Edit');c.hold(1000)

def annotations(c):
    c.goto('boards');c.page.get_by_text('展厅创作 · Story board',exact=True).click();c.hold(1200)
    c.click('适应画布','Fit to view');c.shot('annotations');c.begin()
    doc=c.page.locator('.react-flow__node[data-id="brief"]')
    box=doc.bounding_box();c.page.mouse.move(box['x']+90,box['y']+140);c.page.mouse.down();c.page.mouse.move(box['x']+130,box['y']+150,steps=15);c.page.mouse.up();c.hold()
    c.click('标记模式','Marker mode')
    c.page.get_by_role('button',name='开场 · Opening',exact=True).click();c.hold();c.shot('marker-editor')
    c.page.get_by_role('button',name='结尾 · Finale',exact=True).click();c.hold();c.escape()
    c.click('隐藏标记','Hide markers');c.hold();c.click('显示标记','Show markers')
    c.click('评论模式','Comment mode');c.hold(1100);c.escape();c.hold()

def board_collaboration(c):
    annotations(c)
    c.shot('boards')

SCENES={'scenes':scenes,'notes':notes,'annotations':annotations,'home':home,'media-preview':media,'timeline-edit':editor,'subtitle-dub':subtitles,'ai-studio':ai,'workflows':workflows,'boards':board_collaboration,'plugins':plugins,'publishing':publishing,'scheduler':scheduler,'providers':settings,'appearance':appearance,'login':login}

def encode(src,target,start,duration,gif):
    base=['ffmpeg','-y','-v','error','-ss',str(max(0,start)),'-i',str(src),'-t',str(duration),'-an']
    if gif:
        base+=['-filter_complex','fps=10,scale=960:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3','-loop','0']
    else: base+=['-vf','scale=1280:-2','-c:v','libx264','-crf','24','-preset','fast','-pix_fmt','yuv420p','-movflags','+faststart']
    subprocess.run(base+[str(target)],check=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--api',default='http://127.0.0.1:8812')
    parser.add_argument('--theme',choices=['light','dark','both'],default='both')
    parser.add_argument('--locale',choices=['zh','en','both'],default='both')
    parser.add_argument('--only',default='')
    args=parser.parse_args()
    if not re.match(r'^http://(127\.0\.0\.1|localhost):',args.api):parser.error('Use an isolated local demo backend.')
    token=json.loads(args.token_file.read_text());fixture=json.loads(args.fixture.read_text())
    themes=['light','dark'] if args.theme=='both' else [args.theme]
    locales=['zh','en'] if args.locale=='both' else [args.locale]
    manifest=PUBLIC/'capture-manifest.json';data=json.loads(manifest.read_text()) if manifest.exists() else {'captures':{}}
    version=json.loads((ROOT/'package.json').read_text())['version']
    # Preserve the provenance of reused captures before updating the batch metadata.
    for capture in data.get('captures', {}).values():
        for key in ('version', 'sourceCommit', 'capturedAt'):
            if key in data: capture.setdefault(key, data[key])
    data.update({'version':version,'documentedVersion':version,'sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'capturedAt':datetime.now(timezone.utc).isoformat(),'viewport':VIEWPORT,'note':'Live interface captures. Licensed sample footage and manually prepared editing exercise; no simulated AI replies or publishing successes.'})
    with sync_playwright() as p, tempfile.TemporaryDirectory(prefix='mosael-record-') as tmp:
        browser=p.chromium.launch()
        for locale in locales:
            for theme in themes:
                for name,fn in SCENES.items():
                    if args.only and name not in args.only.split(','):continue
                    print(f'{locale}/{theme}/{name}',flush=True)
                    context=browser.new_context(viewport=VIEWPORT,device_scale_factor=2,color_scheme=theme,record_video_dir=tmp,record_video_size=VIEWPORT)
                    # A fresh context for every recording; auth and preferences are written once.
                    page=context.new_page();origin=time.monotonic()
                    page.goto('http://127.0.0.1:5173',wait_until='domcontentloaded')
                    page.evaluate('([api,token,theme,locale])=>{localStorage.setItem("mosael.server.url",api);localStorage.setItem("mosael.auth.token",token);localStorage.setItem("mosael.preferences",JSON.stringify({theme,locale,font:"default"}));localStorage.setItem("mosael.sidebar.collapsed","false");localStorage.setItem("mosael.editor.panels.v2",JSON.stringify({left:{media:290,transcript:360,subtitle:340,voice:290},right:280,timeline:240}));}',[args.api,token,theme,'zh-CN' if locale=='zh' else 'en-US'])
                    page.reload(wait_until='networkidle')
                    c=Capture(page,locale,theme,fixture)
                    try:fn(c)
                    except Exception:
                        page.screenshot(path=f'/tmp/mosael-capture-failure-{name}.png')
                        Path(f'/tmp/mosael-capture-failure-{name}.txt').write_text(page.locator('body').inner_text())
                        raise
                    duration=time.monotonic()-c.start
                    video=page.video;context.close();raw=Path(video.path())
                    for kind,ext in [('gifs','gif'),('videos','mp4')]:
                        target=c.path(kind,f'{name}.{ext}');encode(raw,target,c.start-origin,duration,ext=='gif');c.outputs.append(target)
                    for target in c.outputs:
                        rel=str(target.relative_to(PUBLIC));data['captures'][rel]={'scene':name,'locale':locale,'theme':theme,'version':version,'sourceCommit':data['sourceCommit'],'capturedAt':data['capturedAt'],'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
                    manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
                    raw.unlink(missing_ok=True)
        browser.close()
    print('Capture manifest saved.',flush=True)
if __name__=='__main__':main()
