(function () {
  'use strict';

  var form = document.getElementById('unlock-form');
  var input = document.getElementById('access-code');
  var button = document.getElementById('unlock-button');
  var status = document.getElementById('unlock-status');

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    var code = input.value.trim();
    if (!/^[0-9]{8}$/.test(code)) {
      status.textContent = '请输入 8 位数字访问码。';
      input.focus();
      return;
    }

    button.disabled = true;
    status.textContent = '正在验证…';
    try {
      var response = await fetch('/api/lan/unlock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code })
      });
      var result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || '验证失败，请重试。');
      }
      status.textContent = '验证成功，正在打开书房…';
      window.location.replace('/');
    } catch (error) {
      status.textContent = error && error.message ? error.message : '连接失败，请检查网络后重试。';
      input.select();
      input.focus();
      button.disabled = false;
    }
  });
}());
