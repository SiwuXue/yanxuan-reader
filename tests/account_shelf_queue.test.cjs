/* node --test tests/account_shelf_queue.test.cjs */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const createAccountShelf = require('../src/zhihu_downloader/app/static/account-shelf.js');

function setup(config = {}) {
  const elements = new Map();
  const timers = new Map();
  const log = [];
  let timerId = 0;
  const state = { tasks: [], session: 'A', downloads: 0, pages: {}, ...config };
  const books = [1, 2, 3].map(id => ({ id: String(id), title: '测试书' + id,
    kind: 'paid_column', supported: true, url: 'https://www.zhihu.com/market/paid_column/' + id }));
  state.pages[0] = state.pages[0] || { books, total: 3, next_offset: null };
  const document = { querySelector(selector) {
    if (!elements.has(selector)) {
      elements.set(selector, { value: '', textContent: '', innerHTML: '', listeners: {},
        addEventListener(type, fn) { this.listeners[type] = fn; } });
    }
    return elements.get(selector);
  }};
  const shelf = createAccountShelf({
    document,
    escapeHtml: s => String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
    setTimeout: fn => { timers.set(++timerId, fn); return timerId; },
    clearTimeout: id => timers.delete(id), settings: () => ({ format: 'epub', resume: true }), onTask() {},
    async api(url, options) {
      if (url.startsWith('/api/account-shelf')) {
        if (state.onLoad) { return state.onLoad(url); }
        const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset'));
        return { ...state.pages[offset], session_id: state.session };
      }
      if (url === '/api/tasks') { return state.tasks.slice(); }
      assert.equal(url, '/api/download');
      const payload = JSON.parse(options.body);
      log.push(payload);
      state.downloads++;
      if (state.onDownload) { return state.onDownload(payload, state.downloads); }
      const task_id = 'task' + state.downloads;
      state.tasks.push({ id: task_id, url: payload.url, status: 'running' });
      return { task_id };
    }
  });
  shelf.bind(); shelf.setSession('A');
  return { shelf, state, log, timers, books,
    el: id => document.querySelector('#account-' + id),
    async tick() { const entry = timers.entries().next().value; if (entry) { timers.delete(entry[0]); await entry[1](); } }
  };
}

test('batch waits for a free slot, then submits the remaining book', async () => {
  const h = setup(); await h.shelf.load();
  await h.shelf.enqueue(['1', '2', '3']);
  assert.equal(h.log.length, 2);
  assert.match(h.el('queue').innerHTML, /等待提交/);
  h.state.tasks[0].status = 'done';
  await h.shelf.updateTasks(h.state.tasks);
  assert.equal(h.log.length, 3);
  assert.equal(h.log[2].account_session, 'A');
  assert.match(h.el('queue').innerHTML, /已完成/);
});

test('a duplicate URL is skipped and double click cannot submit it again', async () => {
  const h = setup(); await h.shelf.load();
  h.state.tasks.push({ id: 'existing', url: h.books[0].url, status: 'running' });
  await h.shelf.enqueue(['1', '2']);
  await h.shelf.enqueue(['2']);
  assert.equal(h.log.length, 1);
  assert.match(h.el('queue').innerHTML, /已跳过重复任务/);
});

test('a full server queue leaves the book pending until a later poll', async () => {
  const h = setup(); await h.shelf.load();
  h.state.onDownload = () => { throw Object.assign(new Error('队列已满'), { status: 429 }); };
  await h.shelf.enqueue(['1']);
  assert.match(h.el('queue').innerHTML, /等待提交/);
  assert.match(h.el('message').textContent, /等待空位/);
  h.state.onDownload = null;
  await h.tick();
  assert.equal(h.log.length, 2);
  assert.match(h.el('queue').innerHTML, /下载中/);
});

test('one failure does not block the rest and can be retried', async () => {
  const h = setup(); await h.shelf.load();
  h.state.onDownload = (payload, n) => {
    if (n === 2) { throw Object.assign(new Error('离线故障'), { status: 502 }); }
    h.state.tasks.push({ id: 'task' + n, url: payload.url, status: 'running' });
    return { task_id: 'task' + n };
  };
  await h.shelf.enqueue(['1', '2', '3']);
  assert.equal(h.log.length, 3);
  assert.match(h.el('queue').innerHTML, /失败：离线故障/);
  h.state.tasks.forEach(task => { task.status = 'done'; });
  await h.shelf.updateTasks(h.state.tasks);
  await h.shelf.enqueue(['2']);
  assert.equal(h.log.length, 4);
});

test('download failure is reflected from the existing task API', async () => {
  const h = setup(); await h.shelf.load(); await h.shelf.enqueue(['1']);
  h.state.tasks[0].status = 'error'; h.state.tasks[0].error = '正文无权限';
  await h.shelf.updateTasks(h.state.tasks);
  assert.match(h.el('queue').innerHTML, /失败：正文无权限/);
  assert.match(h.el('queue').innerHTML, /data-account-retry/);
});

test('switching accounts during submission clears the queue and prevents further submission', async () => {
  const h = setup(); await h.shelf.load();
  let finish;
  h.state.onDownload = () => new Promise(resolve => { finish = resolve; });
  const pumping = h.shelf.enqueue(['1', '2', '3']);
  await new Promise(resolve => setImmediate(resolve));
  h.shelf.setSession('B');
  finish({ task_id: 'old-account-task' }); await pumping;
  assert.equal(h.log.length, 1);
  assert.equal(h.el('list').innerHTML, ''); assert.equal(h.el('queue').innerHTML, '');
  assert.equal(h.timers.size, 0);
});

test('a stale page response cannot repopulate the previous account', async () => {
  const h = setup(); let finish;
  h.state.onLoad = () => new Promise(resolve => { finish = resolve; });
  const loading = h.shelf.load();
  h.shelf.setSession('B');
  finish({ books: h.books, total: 3, next_offset: null, session_id: 'A' });
  await loading;
  assert.equal(h.el('list').innerHTML, '');
});

test('pagination deduplicates IDs across pages and search only filters loaded books', async () => {
  const h = setup();
  h.state.pages = { 0: { books: h.books.slice(0, 2), total: 3, next_offset: 2 },
    2: { books: h.books.slice(1), total: 3, next_offset: null } };
  await h.shelf.load(); await h.shelf.load(true);
  assert.match(h.el('count').textContent, /已加载 3 \/ 3/);
  h.el('search').value = '测试书2'; h.el('search').listeners.input();
  assert.match(h.el('list').innerHTML, /测试书2/);
  assert.doesNotMatch(h.el('list').innerHTML, /测试书1|测试书3/);
});

test('unsupported books stay unselectable and server titles are escaped', async () => {
  const h = setup();
  h.state.pages[0].books = [{ id: 'app', title: '<img src=x onerror=alert(1)>', supported: false,
    unsupported_reason: 'App 内容暂不支持' }];
  await h.shelf.load(); await h.shelf.enqueue(['app']);
  assert.equal(h.log.length, 0);
  assert.match(h.el('list').innerHTML, /disabled/);
  assert.match(h.el('list').innerHTML, /&lt;img/);
  assert.doesNotMatch(h.el('list').innerHTML, /<img/);
});

test('login expiration clears cached titles and selected jobs', async () => {
  const h = setup(); await h.shelf.load();
  h.state.onLoad = () => { throw Object.assign(new Error('登录已失效'), { status: 401 }); };
  await h.shelf.load();
  assert.equal(h.el('list').innerHTML, '');
  assert.match(h.el('message').textContent, /登录已失效/);
});
