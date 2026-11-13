// Explicit local check; no threads, model calls, keys or project data.
const http = require('node:http');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

async function initialize() {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket('ws://127.0.0.1:4500');
    let finished = false;
    const timer = setTimeout(() => {
      finished = true;
      ws.close();
      reject(Error('CLI初始化超时'));
    }, 8000);
    ws.onopen = () =>
      ws.send(
        JSON.stringify({
          id: 1,
          method: 'initialize',
          params: { clientInfo: { name: 'verity_protocol_probe', version: '0.1.0' } },
        }),
      );
    ws.onmessage = ({ data }) => {
      const response = JSON.parse(String(data));
      if (response.id !== 1) return;
      clearTimeout(timer);
      finished = true;
      if (response.result && !response.error) {
        ws.send(JSON.stringify({ method: 'initialized', params: {} }));
        resolve(true);
      } else reject(Error('CLI初始化失败'));
      ws.close();
    };
    ws.onerror = () => {
      if (!finished) {
        clearTimeout(timer);
        reject(Error('本机CLI连接失败'));
      }
    };
  });
}

async function browserHandshake() {
  return new Promise((resolve, reject) => {
    const request = http.request({
      hostname: '127.0.0.1',
      port: 4500,
      path: '/',
      headers: {
        Connection: 'Upgrade',
        Upgrade: 'websocket',
        'Sec-WebSocket-Version': '13',
        'Sec-WebSocket-Key': crypto.randomBytes(16).toString('base64'),
        Origin: 'http://127.0.0.1:5173',
      },
    });
    request.on('response', (response) => {
      response.resume();
      resolve(response.statusCode);
    });
    request.on('upgrade', (response, socket) => {
      socket.destroy();
      resolve(response.statusCode);
    });
    request.on('error', reject);
    request.setTimeout(8000, () => request.destroy(Error('浏览器握手检查超时')));
    request.end();
  });
}

(async () => {
  assert.equal(await initialize(), true);
  const status = await browserHandshake();
  console.log('CLI协议初始化：成功');
  console.log('浏览器Origin握手：HTTP ' + status);
  if (status === 403) console.log('结论：当前CLI拒绝网页直接连接；尚未验证AI会话。');
  else if (status === 101) console.log('握手接受；仍需浏览器实点和会话验证。');
  else throw Error('未预期的握手状态：' + status);
})().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
