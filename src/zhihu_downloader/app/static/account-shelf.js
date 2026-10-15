'use strict';
/* 账号书架控制器。批量队列仅存于当前页面；下载仍由原有 /api/download 执行。 */
(function (root) {
  function createAccountShelf(opts) {
    var doc = opts.document || document;
    var later = opts.setTimeout || root.setTimeout.bind(root);
    var cancel = opts.clearTimeout || root.clearTimeout.bind(root);
    var books = [], selected = new Set(), jobs = new Map();
    var session = '', epoch = 0, requestId = 0, loading = false, loaded = false;
    var total = 0, next = null, pumping = false, timer = null;
    var statuses = { queued: '等待提交', submitted: '下载中', done: '已完成', error: '失败', skipped: '已跳过重复任务' };
    function el(id) { return doc.querySelector('#account-' + id); }
    function esc(s) { return opts.escapeHtml(s); }
    function kindLabel(kind, supported) {
      var labels = {
        short_story: '盐选短故事', work: '盐选短故事', live: 'Live 音视频',
        paid_column: '盐选专栏', column: '知乎专栏', answer: '知乎回答', article: '知乎文章'
      };
      var key = String(kind || '').toLowerCase().replace(/[\s-]+/g, '_');
      return labels[key] || (supported ? '可下载藏书' : '账号藏书');
    }
    function message(text, bad) {
      el('message').textContent = text;
      el('message').className = 'form-msg' + (bad ? ' form-msg-bad' : '');
    }
    function busy(job) { return job && (job.status === 'queued' || job.status === 'submitted'); }
    function visible() {
      var query = el('search').value.trim().toLocaleLowerCase();
      return books.filter(function (b) { return b.title.toLocaleLowerCase().includes(query); });
    }
    function render() {
      var list = visible();
      var available = list.filter(function (b) { return b.supported && !busy(jobs.get(b.id)); });
      el('refresh').disabled = loading;
      el('refresh').textContent = loading ? '读取中…' : (loaded ? '刷新书架' : '读取书架');
      el('count').textContent = loaded ? '已加载 ' + books.length + ' / ' + total + ' 条 · 可下载 ' +
        books.filter(function (b) { return b.supported; }).length + ' 条' : '';
      var navCount = doc.querySelector('#nav-account-count');
      if (navCount) { navCount.textContent = loaded ? String(total) : '—'; }
      el('download').disabled = selected.size === 0;
      el('download').textContent = '下载所选' + (selected.size ? '（' + selected.size + '）' : '');
      var selectionCount = doc.querySelector('#account-selection-count');
      if (selectionCount) {
        selectionCount.textContent = selected.size ? selected.size + ' 本书已选中' :
          '选择书籍后，可以批量保存到本机';
      }
      doc.body.classList.toggle('has-account-selection', selected.size > 0);
      el('select-all').disabled = !available.length;
      var checked = available.filter(function (b) { return selected.has(b.id); }).length;
      el('select-all').checked = available.length > 0 && checked === available.length;
      el('select-all').indeterminate = checked > 0 && checked < available.length;
      el('more').hidden = !loaded || next === null;
      el('more').disabled = loading;
      el('list').innerHTML = list.map(function (b) {
        var job = jobs.get(b.id);
        var locked = !b.supported || busy(job);
        var action = job && job.status === 'error' ? '重试' : (job && job.status === 'done' ? '再次下载' : '下载');
        return '<li class="shelf-item' + (selected.has(b.id) ? ' is-selected' : '') + '"><div class="account-cover-stage">' +
          '<div class="account-cover" aria-hidden="true"><small>YANXUAN · MY LIBRARY</small><span class="account-cover-title">' +
          esc(b.title) + '</span><span class="account-cover-foot">' + esc(kindLabel(b.kind, b.supported)) +
          '</span></div></div><div class="account-book-info"><div class="account-book-head">' +
          '<label><input class="account-book-select" type="checkbox" data-account-select="' + esc(b.id) + '"' +
          (locked ? ' disabled' : '') + (selected.has(b.id) ? ' checked' : '') + ' /><span class="shelf-title">' +
          esc(b.title) + '</span></label>' + (b.supported ? '<button class="btn btn-outline btn-sm" type="button" data-account-download="' +
          esc(b.id) + '"' + (locked ? ' disabled' : '') + '>' + action + '</button>' : '') + '</div>' +
          '<p class="account-book-reason' + (b.supported ? '' : ' is-unsupported') + '">' +
          esc(b.supported ? '支持网页下载' : b.unsupported_reason) + '</p></div></li>';
      }).join('');
      if (loaded && !list.length) {
        el('list').innerHTML = '<li class="empty">' + (books.length ? '已加载书目中没有匹配结果。' : '当前账号书架为空。') + '</li>';
      }
      el('queue-box').hidden = jobs.size === 0;
      el('queue').innerHTML = Array.from(jobs.values()).map(function (job) {
        return '<li><b>' + esc(job.book.title) + '</b> · ' + esc(statuses[job.status] || job.status) +
          (job.message ? '：' + esc(job.message) : '') + (job.status === 'error' ?
            ' <button class="btn btn-ghost btn-sm" type="button" data-account-retry="' + esc(job.book.id) + '">重试</button>' : '') + '</li>';
      }).join('');
    }
    function reset(text) {
      epoch += 1; requestId += 1;
      books = []; selected.clear(); jobs.clear(); total = 0; next = null; loaded = false; loading = false;
      el('search').value = '';
      if (timer !== null) { cancel(timer); timer = null; }
      message(text || '登录信息已变化，请重新读取账号书架。');
      render();
    }
    function setSession(value) {
      if (session && session !== value) { reset(); }
      session = value || '';
    }
    async function load(more) {
      if (loading || (more && next === null)) { return; }
      if (opts.refreshAuth) { await opts.refreshAuth(); }
      var generation = epoch, serial = ++requestId;
      loading = true;
      if (!more) { books = []; selected.clear(); next = null; loaded = false; }
      message('正在读取账号书架…'); render();
      try {
        var data = await opts.api('/api/account-shelf?offset=' + (more ? next : 0));
        if (generation !== epoch || serial !== requestId) { return; }
        if (session && data.session_id !== session) { reset(); return; }
        session = data.session_id;
        var seen = new Set(books.map(function (b) { return b.id; }));
        data.books.forEach(function (b) { if (!seen.has(b.id)) { books.push(b); seen.add(b.id); } });
        total = data.total; next = data.next_offset; loaded = true;
        message(next === null ? '书架已全部加载。' : '已读取一页，可以继续加载更多。');
      } catch (error) {
        if (generation !== epoch || serial !== requestId) { return; }
        if (error.status === 401 || error.status === 409) { reset(error.message); }
        message('读取失败：' + error.message, true);
      } finally {
        if (generation === epoch && serial === requestId) { loading = false; render(); }
      }
    }
    function enqueue(ids) {
      ids.forEach(function (id) {
        var book = books.find(function (b) { return b.id === id; });
        var prior = jobs.get(id);
        book = book || (prior && prior.book);
        if (!session || !book || !book.supported || busy(prior)) { return; }
        jobs.set(id, { book: book, status: 'queued', message: '', settings: opts.settings(), session: session });
        selected.delete(id);
      });
      render();
      return pump();
    }
    function syncTasks(tasks) {
      jobs.forEach(function (job) {
        if (job.status !== 'submitted') { return; }
        var task = tasks.find(function (t) { return t.id === job.taskId; });
        if (task && ['done', 'error', 'cancelled'].includes(task.status)) {
          job.status = task.status === 'done' ? 'done' : 'error';
          job.message = task.status === 'done' ? '' : (task.error || (task.status === 'cancelled' ? '任务已停止。' : ''));
        }
      });
    }
    function schedule() {
      if (timer !== null || !Array.from(jobs.values()).some(busy)) { return; }
      timer = later(function () { timer = null; return pump(); }, 3000);
    }
    async function pump() {
      if (pumping || !Array.from(jobs.values()).some(busy)) { return; }
      pumping = true;
      var generation = epoch;
      try {
        var tasks = await opts.api('/api/tasks');
        if (generation !== epoch) { return; }
        syncTasks(tasks);
        var active = tasks.filter(function (t) { return !['done', 'error', 'cancelled'].includes(t.status); });
        var pending = Array.from(jobs.values()).filter(function (job) { return job.status === 'queued'; });
        for (var i = 0; i < pending.length; i++) {
          var job = pending[i];
          if (generation !== epoch) { return; }
          if (active.some(function (t) { return t.url === job.book.url; })) {
            job.status = 'skipped'; continue;
          }
          // 与服务端的两个执行槽位保持一致，不把整份书架塞满服务端任务表。
          if (active.length >= 2) { break; }
          try {
            var data = await opts.api('/api/download', { method: 'POST', body: JSON.stringify(Object.assign({},
              job.settings, { url: job.book.url, account_session: job.session })) });
            if (generation !== epoch) { return; }
            if (!data || !data.task_id) { throw new Error('服务没有返回任务编号，请重试。'); }
            job.status = 'submitted'; job.taskId = data.task_id;
            active.push({ id: data.task_id, url: job.book.url, status: 'pending' });
            opts.onTask(data.task_id);
          } catch (error) {
            if (generation !== epoch) { return; }
            if (error.status === 401 || error.status === 409) { reset(error.message); return; }
            if (error.status === 429) { message('任务队列已满，等待空位后继续提交。'); break; }
            job.status = error.status === 400 && /已有任务/.test(error.message) ? 'skipped' : 'error';
            job.message = error.message;
          }
        }
      } catch (error) {
        if (generation === epoch) { message('队列暂时无法同步：' + error.message, true); }
      } finally {
        pumping = false;
        if (generation === epoch) { render(); }
        schedule();
      }
    }
    function updateTasks(tasks) { syncTasks(tasks); render(); if (!pumping) { return pump(); } }
    function bind() {
      el('refresh').addEventListener('click', function () { load(false); });
      el('more').addEventListener('click', function () { load(true); });
      el('search').addEventListener('input', render);
      el('download').addEventListener('click', function () { enqueue(Array.from(selected)); });
      el('select-all').addEventListener('change', function (event) {
        visible().forEach(function (book) {
          if (!book.supported || busy(jobs.get(book.id))) { return; }
          if (event.target.checked) { selected.add(book.id); } else { selected.delete(book.id); }
        });
        render();
      });
      el('list').addEventListener('change', function (event) {
        var id = event.target.getAttribute('data-account-select');
        if (!id) { return; }
        if (event.target.checked) { selected.add(id); } else { selected.delete(id); }
        render();
        var restored = Array.prototype.find.call(el('list').querySelectorAll('[data-account-select]'), function (input) {
          return input.getAttribute('data-account-select') === id;
        });
        if (restored) { restored.focus(); }
      });
      el('list').addEventListener('click', function (event) {
        var id = event.target.getAttribute('data-account-download');
        if (id) { enqueue([id]); }
      });
      el('queue').addEventListener('click', function (event) {
        var id = event.target.getAttribute('data-account-retry');
        if (id) { enqueue([id]); }
      });
      render();
    }
    return { bind: bind, load: load, enqueue: enqueue, reset: reset, setSession: setSession, updateTasks: updateTasks };
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = createAccountShelf; }
  else { root.createAccountShelf = createAccountShelf; }
})(typeof window !== 'undefined' ? window : globalThis);
