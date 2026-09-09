import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { DOC_GROUPS, docNavigationOrder } from '../src/lib/docs-navigation.ts';

test('every translated document appears exactly once in the reading order', () => {
  const navigation = DOC_GROUPS.flatMap(group => [...group.pages]);
  assert.equal(new Set(navigation).size, navigation.length);
  assert.equal(navigation[0], 'start/intro');
  for (const locale of ['en', 'zh']) {
    const actual = ['start', 'guides', 'about'].flatMap(section => fs.readdirSync(`content/docs/${locale}/${section}`)
      .filter(file => file.endsWith('.mdx')).map(file => `${section}/${file.slice(0, -4)}`));
    assert.deepEqual([...actual].sort(), [...navigation].sort());
    const ordered = actual.map(key => { const [section, name] = key.split('/'); return { section, name }; })
      .sort((a, b) => docNavigationOrder(a) - docNavigationOrder(b));
    assert.deepEqual(ordered.map(doc => `${doc.section}/${doc.name}`), navigation);
  }
});

test('3D and documents are discoverable with boards; unknown pages do not become the landing page', () => {
  const group = DOC_GROUPS.find(group => group.pages.includes('guides/boards'));
  assert.ok(group.pages.includes('guides/scenes'));
  assert.ok(group.pages.includes('guides/notes'));
  assert.ok(docNavigationOrder({ section: 'guides', name: 'new-guide' }) > docNavigationOrder({ section: 'about', name: 'contact' }));
});
