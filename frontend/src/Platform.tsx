import { useState } from 'react';
import type { User } from './Auth';
import { Accounts } from './Accounts';
import { AIService } from './AIService';
import { GitHubConnections } from './GitHubConnections';
import { CaseDialog } from './CaseDialog';

export function Platform({
  user,
  onSessionEnd,
  onUserChange,
}: {
  user: User;
  onSessionEnd: () => void;
  onUserChange: (user: User) => void;
}) {
  const [tab, setTab] = useState(user.platform_role === 'ADMIN' ? 'accounts' : 'general');
  const [aiDirty, setAiDirty] = useState(false);
  const [pendingTab, setPendingTab] = useState<string | null>(null);
  const sections = [
    ['general', 'AI 服务'],
    ['github', 'GitHub 连接'],
    ['accounts', '账号管理'],
  ];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>平台设置</h1>
          <p>统一配置 AI 服务与 GitHub 访问方式。</p>
        </div>
      </div>
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="平台设置分类">
          {sections.map(([key, name]) => (
            <button
              key={key}
              className={tab === key ? 'active' : ''}
              onClick={() => {
                if (key !== tab && aiDirty) setPendingTab(key);
                else setTab(key);
              }}
              aria-current={tab === key ? 'page' : undefined}
            >
              {name}
            </button>
          ))}
        </nav>
        {tab === 'general' ? (
          <AIService onSessionEnd={onSessionEnd} onDirtyChange={setAiDirty} />
        ) : tab === 'github' ? (
          <GitHubConnections onSessionEnd={onSessionEnd} />
        ) : user.platform_role !== 'ADMIN' ? (
          <section className="panel empty">
            <h2>仅平台管理员可配置</h2>
            <p>当前账号没有此项管理权限。</p>
          </section>
        ) : (
          <Accounts user={user} onSessionEnd={onSessionEnd} onUserChange={onUserChange} />
        )}
      </div>
      {pendingTab && (
        <CaseDialog title="放弃未保存内容？" busy={false} onClose={() => setPendingTab(null)}>
          <p>AI 配置表单有未保存内容，切换设置分类将放弃本次修改。</p>
          <div className="row mt">
            <button onClick={() => setPendingTab(null)}>继续编辑</button>
            <button
              className="primary"
              onClick={() => {
                setTab(pendingTab);
                setPendingTab(null);
                setAiDirty(false);
              }}
            >
              放弃并继续
            </button>
          </div>
        </CaseDialog>
      )}
    </>
  );
}
