import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import './soft-theme.css';
import './codexDemo.css';

function Demo() {
  const socket = useRef<WebSocket | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [state, setState] = useState('尚未测试');
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<string[]>([]);
  useEffect(
    () => () => {
      clearTimeout(timer.current);
      socket.current?.close();
    },
    [],
  );

  function connect() {
    if (busy) return;
    const rows: string[] = [];
    const record = (text: string) => {
      rows.push(text);
      setEvents([...rows]);
    };
    setBusy(true);
    setState('正在连接');
    let finished = false;
    const finish = (message: string) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer.current);
      setState(message);
      setBusy(false);
      socket.current?.close();
    };
    record('页面来源：' + location.origin);
    record('直接连接 ws://127.0.0.1:4500（不经过平台代理）');
    try {
      const ws = new WebSocket('ws://127.0.0.1:4500');
      socket.current = ws;
      timer.current = setTimeout(() => finish('连接超时，请确认本机服务已启动。'), 8000);
      ws.onopen = () => {
        record('WebSocket连接成功，开始协议初始化。');
        ws.send(
          JSON.stringify({
            id: 1,
            method: 'initialize',
            params: { clientInfo: { name: 'verity_browser_probe', version: '0.1.0' } },
          }),
        );
      };
      ws.onmessage = ({ data }) => {
        try {
          const response = JSON.parse(String(data)) as {
            id?: unknown;
            result?: unknown;
            error?: unknown;
          };
          if (response.id !== 1) return;
          if (response.result && !response.error) {
            ws.send(JSON.stringify({ method: 'initialized', params: {} }));
            record('CLI初始化成功；没有创建会话、读取历史或调用AI。');
            finish('浏览器直连协议验证成功');
          } else finish('连接已建立，但CLI初始化失败。');
        } catch {
          finish('CLI返回了无法识别的协议消息。');
        }
      };
      ws.onerror = () => {
        record('浏览器未提供HTTP状态码；请结合本机协议检查判断原因。');
        finish('浏览器连接失败');
      };
      ws.onclose = () => {
        if (!finished) finish('连接在初始化前关闭');
      };
    } catch {
      finish('浏览器阻止了连接或本机服务不可访问。');
    }
  }

  return (
    <main className="codex-demo">
      <header>
        <p className="hint">质序 · 本机CLI直连最小验证</p>
        <h1>浏览器能否直接连接 Codex？</h1>
        <p>点击后仅建立本地连接并初始化协议，不发送需求资料、不调用模型。</p>
      </header>
      <section className="panel panel-pad">
        <div className="row">
          <button className="primary" disabled={busy} onClick={connect}>
            {busy ? '正在测试…' : '测试浏览器直连'}
          </button>
          <span role="status">{state}</span>
        </div>
        <ol aria-live="polite">
          {events.map((event, index) => (
            <li key={index}>{event}</li>
          ))}
        </ol>
      </section>
      <section className="panel panel-pad">
        <h2>本机协议实测结果</h2>
        <p>
          本次使用 Codex CLI 0.144.1：普通程序的协议初始化成功；带页面来源的浏览器握手返回 HTTP
          403。
        </p>
        <p>因此当前版本的网页直连路径受阻，尚不能进入创建、恢复和继续对话环节。</p>
        <p className="hint">
          上方为当前浏览器即时测试；本节为开发时本机协议检查记录，不会把连接失败当成成功。
        </p>
      </section>
      <section className="panel panel-pad">
        <h2>下一步选择</h2>
        <p>
          若要在Web内继续真实会话，需要一个经过身份校验的本地连接层，使用Codex支持的标准输入输出接口。也可保留CLI操作，仅把报告和会话关联放到平台。
        </p>
        <a href="https://learn.chatgpt.com/docs/app-server" target="_blank" rel="noreferrer">
          查看官方 App Server 说明
        </a>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<Demo />);
