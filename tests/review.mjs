// Exercise the actual administrator page without changing dispatch selections.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../public/index.html', import.meta.url), 'utf8');
const source = html.split('<script>')[1].split('</script>')[0];
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    innerHTML: '', textContent: '', value: '', hidden: false,
    classList: { add() {}, remove() {} }, querySelectorAll: () => [],
    focus() {}, scrollIntoView() {},
  });
  return elements.get(id);
}
const context = vm.createContext({
  document: { getElementById: element }, addEventListener() {},
  fetch: () => new Promise(() => {}), location: { search: '' },
  URL, URLSearchParams, setTimeout, clearTimeout,
});
vm.runInContext(source + '\n;globalThis.probe = {state, reviewRows, filteredRows, plainText, render, renderResults, renderRow};', context);
const p = context.probe;
const article = (id, title, extra = {}) => ({
  id, title, source: '시험매체', url: `https://news.example/${id}`, published: '2026-09-19 06:00', ...extra,
});
Object.assign(p.state, {
  date: '2026-09-19', excluded: new Set(['c']),
  data: { sectors: [
    { id: 'energy', title: '에너지', limit: 1, articles: [
      article('a', '발송할 대표 기사', { duplicates: [article('dup', '숨겨졌던 다른 매체 보도', { source: '추적매체' })] }),
      article('b', '상한으로 빠진 기사', { summary: '특별 조사 내용' }),
      article('c', '담당자가 제외한 기사'),
    ] },
    { id: 'public', title: '공공기관', limit: 1, articles: [article('d', '다른 분야의 기사')] },
  ] },
});
const ids = (rows) => Array.from(rows, r => r.article.id);
const sent = p.plainText();
assert.deepEqual(ids(p.reviewRows()), ['a', 'dup', 'b', 'c', 'd']);
p.state.view = 'unsent';
assert.deepEqual(ids(p.filteredRows()), ['dup', 'b', 'c']);
p.state.view = 'duplicate';
p.state.query = '숨겨졌던 추적매체';
assert.deepEqual(ids(p.filteredRows()), ['dup']);
p.state.view = 'all';
p.state.query = '특별 조사';
assert.deepEqual(ids(p.filteredRows()), ['b']);
p.state.query = '';
p.state.sector = 'public';
assert.deepEqual(ids(p.filteredRows()), ['d']);
assert.equal(p.plainText(), sent, 'Read-only browsing must never alter the dispatch preview');

p.state.excluded.add('a');
p.state.sector = 'all';
p.state.view = 'selected';
assert.deepEqual(ids(p.filteredRows()), ['b', 'd'], 'Exclusion must still promote the next representative');
assert.ok(!p.plainText().includes('https://news.example/dup'), 'Duplicates are readable but not extra dispatch items');
assert.ok(p.renderRow(p.reviewRows()[1]).includes('href="https://news.example/dup"'));
assert.ok(!p.renderRow(p.reviewRows()[1]).includes('data-toggle-id'), 'A duplicate must not mutate representative exclusions');
const malicious = p.renderRow({ article: article('bad', '<img src=x onerror=alert(1)>', { url: 'javascript:alert(1)' }), status: 'duplicate', parent: article('a', '대표') });
assert.ok(malicious.includes('&lt;img'));
assert.ok(!malicious.includes('href="javascript:'));

Object.assign(p.state, { view: 'all', query: '', page: 1, excluded: new Set() });
p.state.data.sectors[0].articles = Array.from({ length: 42 }, (_, i) => article(`page-${i}`, `기사 ${i}`));
p.render();
assert.equal((element('articleResults').innerHTML.match(/class="item /g) || []).length, 40);
element('nextPage').onclick();
assert.equal((element('articleResults').innerHTML.match(/class="item /g) || []).length, 3);
assert.ok(element('articleResults').innerHTML.includes('기사 41'));
p.state.query = '없는 검색어';
p.renderResults();
assert.equal(p.state.page, 1);
assert.ok(element('articleResults').innerHTML.includes('조건에 맞는 기사가 없습니다'));
console.log('Administrator browsing, hidden duplicates, pagination and dispatch invariance checks passed');
