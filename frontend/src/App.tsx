import './prototype-directory.css';
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AuthStatus, Login, useAuth } from './Auth';
import type { User } from './Auth';
import { platformRoleLabels } from './accountRoles';
import { Platform } from './Platform';
import { Icon } from './Icon';
import { CreateProjectDialog, ProjectSettings, useProjects } from './Projects';
import { Documents } from './Documents';
import { Prototypes } from './Prototypes';
import { Cases } from './Cases';
import { RiskReports } from './RiskReports';
import { CodeAnalysis } from './CodeAnalysis';
import { ChangeAnalysis } from './ChangeAnalysis';
import { CaseGeneration } from './CaseGeneration';
import type { GenerationPageCache } from './CaseGeneration';
import { CaseAnalysis } from './CaseAnalysis';
import { Skills } from './Skills';
import { ProjectOverview } from './ProjectOverview';
import { AIResultsAcceptance } from './AIResultsAcceptance';
import { OverviewEntry } from './OverviewEntry';
import { RequirementChat } from './RequirementChat';

type SidebarLayout = { width: number; collapsed: boolean };
const SIDEBAR_STORAGE = 'verity-sidebar-layout';
const clampSidebarWidth = (value: number) =>
  Math.max(200, Math.min(360, Number.isFinite(value) ? value : 224));
function readSidebarLayout(): SidebarLayout {
  try {
    const value = JSON.parse(localStorage.getItem(SIDEBAR_STORAGE) || 'null');
    return {
      width: clampSidebarWidth(typeof value?.width === 'number' ? value.width : 224),
      collapsed: value?.collapsed === true,
    };
  } catch {
    return { width: 224, collapsed: false };
  }
}

const groups = [
  { title: '', items: [['/', '项目概览', 'grid']] },
  {
    title: '项目资料',
    items: [
      ['/documents', '需求资料', 'file'],
      ['/prototypes', '原型资料', 'template'],
      ['/cases', '用例管理', 'list'],
    ],
  },
  {
    title: 'AI 分析工作台',
    items: [
      ['/requirements', '需求分析', 'spark'],
      ['/generate', '用例生成', 'list'],
      ['/coverage', '用例分析', 'chart'],
      ['/code', '代码分析', 'code'],
      ['/changes', '变更分析', 'branch'],
    ],
  },
  {
    title: '配置与管理',
    items: [
      ['/skills', 'Skill 管理', 'spark'],
      ['/ai-acceptance', 'AI结果验收', 'chart'],
      ['/project', '项目设置', 'settings'],
      ['/platform', '平台设置', 'sliders'],
    ],
  },
];
const modules = groups.flatMap((group) => group.items);

function Pending({ name }: { name: string }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{name}</h1>
        </div>
      </div>
      <section className="panel panel-pad">
        <span className="badge">尚未实现</span>
        <h2 className="mt">功能待接入</h2>
      </section>
    </>
  );
}
export function App() {
  const { pathname } = useLocation();
  const auth = useAuth(pathname);
  if (auth.loading || auth.error) return <AuthStatus error={auth.error} onRetry={auth.refresh} />;
  if (!auth.user) {
    return pathname === '/login' ? (
      <Login onLogin={auth.updateUser} />
    ) : (
      <Navigate to="/login" replace />
    );
  }
  if (pathname === '/login') return <Navigate to="/" replace />;
  return <Workspace key={auth.user.id} user={auth.user} onLogout={auth.updateUser} />;
}

function Workspace({ user, onLogout }: { user: User; onLogout: (user: User | null) => void }) {
  const { pathname, search } = useLocation();
  const sourceId = Number(new URLSearchParams(search).get('document'));
  const documentId = Number.isSafeInteger(sourceId) && sourceId > 0 ? sourceId : undefined;
  const [menuOpen, setMenuOpen] = useState(false);
  const [help, setHelp] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState('');
  const current = modules.find((m) => m[0] === pathname)?.[1] || '页面不存在';
  const endSession = useCallback(() => onLogout(null), [onLogout]);
  const projects = useProjects(user.id, endSession);
  const projectId = projects.current?.id;
  const [accountViews] = useState(() => ({
    acceptance: new Map<string, unknown>(),
    platform: new Map<string, unknown>(),
    skills: new Map<string, unknown>(),
  }));
  const projectViews = useMemo(
    () => ({
      projectId,
      overview: new Map<string, unknown>(),
      prototypes: new Map<string, unknown>(),
      documents: new Map<string, unknown>(),
      settings: new Map<string, unknown>(),
      cases: new Map<string, unknown>(),
      requirements: new Map<string, unknown>(),
      requirementChat: new Map<string, unknown>(),
      code: new Map<string, unknown>(),
      changes: new Map<string, unknown>(),
      coverage: new Map<string, unknown>(),
    }),
    [projectId],
  );
  const generationPageCache = useMemo<GenerationPageCache>(() => ({ projectId }), [projectId]);
  const [creatingProject, setCreatingProject] = useState(false);
  const projectPicker = useRef<HTMLDetailsElement>(null);
  const accountMenu = useRef<HTMLDetailsElement>(null);
  const [sidebar, setSidebar] = useState<SidebarLayout>(readSidebarLayout);
  const sidebarValue = useRef(sidebar);
  const resizeHandle = useRef<HTMLDivElement>(null);
  const dragStart = useRef<{ id: number; width: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  function updateSidebar(value: SidebarLayout, persist = true) {
    sidebarValue.current = value;
    setSidebar(value);
    if (persist) {
      try {
        localStorage.setItem(SIDEBAR_STORAGE, JSON.stringify(value));
      } catch {
        /* Keep usable when storage is blocked. */
      }
    }
  }
  const finishResize = useCallback((cancel = false) => {
    const start = dragStart.current;
    if (!start) return;
    dragStart.current = null;
    const value = {
      ...sidebarValue.current,
      width: cancel ? start.width : sidebarValue.current.width,
    };
    sidebarValue.current = value;
    setSidebar(value);
    setDragging(false);
    if (resizeHandle.current?.hasPointerCapture(start.id))
      resizeHandle.current.releasePointerCapture(start.id);
    try {
      localStorage.setItem(SIDEBAR_STORAGE, JSON.stringify(value));
    } catch {
      /* In-memory fallback. */
    }
  }, []);

  useEffect(() => {
    function outside(event: PointerEvent) {
      for (const menu of [projectPicker.current, accountMenu.current]) {
        if (event.target instanceof Node && menu && !menu.contains(event.target)) menu.open = false;
      }
    }
    function escape(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      if (dragStart.current) {
        finishResize(true);
        resizeHandle.current?.focus();
      }
      for (const menu of [projectPicker.current, accountMenu.current]) {
        if (menu?.open) {
          menu.open = false;
          menu.querySelector('summary')?.focus();
        }
      }
    }
    function resize() {
      finishResize(true);
    }
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    window.addEventListener('resize', resize);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape);
      window.removeEventListener('resize', resize);
    };
  }, [finishResize]);

  function chooseProject(id: number) {
    projects.setSelected(id);
    if (projectPicker.current) {
      projectPicker.current.open = false;
      projectPicker.current.querySelector('summary')?.focus();
    }
  }

  async function logout() {
    setLoggingOut(true);
    setLogoutError('');
    try {
      const response = await fetch('/api/auth/logout', {
        method: 'POST',
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) throw new Error('logout_failed');
      onLogout(null);
    } catch {
      setLogoutError('退出未完成，请重试。');
      if (accountMenu.current) accountMenu.current.open = true;
    } finally {
      setLoggingOut(false);
    }
  }
  return (
    <div
      className={`app${menuOpen ? ' menu-open' : ''}${sidebar.collapsed ? ' sidebar-collapsed' : ''}${dragging ? ' sidebar-dragging' : ''}`}
      style={{ '--sidebar-expanded': `${sidebar.width}px` } as CSSProperties}
    >
      <aside className="sidebar" aria-label="侧边栏">
        <button
          className="sidebar-toggle"
          type="button"
          aria-controls="workspace-navigation"
          aria-label={sidebar.collapsed ? '展开侧栏' : '收起侧栏'}
          aria-expanded={!sidebar.collapsed}
          title={sidebar.collapsed ? '展开侧栏' : '收起侧栏'}
          onClick={() => {
            if (projectPicker.current) projectPicker.current.open = false;
            if (window.innerWidth <= 900) setMenuOpen(false);
            else
              updateSidebar({
                ...sidebarValue.current,
                collapsed: !sidebarValue.current.collapsed,
              });
          }}
        >
          <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path
              d="m10 4-4 4 4 4"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <div
          ref={resizeHandle}
          className="sidebar-resize"
          role="separator"
          aria-label="调整侧栏宽度"
          aria-orientation="vertical"
          aria-valuemin={200}
          aria-valuemax={360}
          aria-valuenow={sidebar.width}
          tabIndex={0}
          title="拖动调整宽度；双击恢复默认；方向键微调"
          onPointerDown={(event) => {
            if (event.button !== 0 || window.innerWidth <= 900 || sidebar.collapsed) return;
            event.preventDefault();
            dragStart.current = { id: event.pointerId, width: sidebar.width };
            event.currentTarget.setPointerCapture(event.pointerId);
            setDragging(true);
            if (projectPicker.current) projectPicker.current.open = false;
          }}
          onPointerMove={(event) => {
            if (dragStart.current?.id === event.pointerId)
              updateSidebar(
                { ...sidebarValue.current, width: clampSidebarWidth(event.clientX) },
                false,
              );
          }}
          onPointerUp={() => finishResize()}
          onPointerCancel={() => finishResize(true)}
          onLostPointerCapture={() => finishResize()}
          onDoubleClick={() => updateSidebar({ ...sidebarValue.current, width: 224 })}
          onKeyDown={(event) => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const width =
              event.key === 'Home'
                ? 200
                : event.key === 'End'
                  ? 360
                  : clampSidebarWidth(sidebar.width + (event.key === 'ArrowRight' ? 8 : -8));
            updateSidebar({ ...sidebarValue.current, width });
          }}
        />
        <Link to="/" className="brand" aria-label="质序首页">
          <div className="brand-mark">v</div>
          <div>
            <strong>质序</strong>
            <small>VERITY / AI QUALITY</small>
          </div>
        </Link>
        <div className="project-pick">
          <details className="project-switch" ref={projectPicker}>
            <summary
              aria-label={`切换项目：${projects.current?.name || '未选择项目'}`}
              aria-disabled={projects.loading}
              onClick={(event) => {
                if (projects.loading) event.preventDefault();
              }}
            >
              <span className="project-icon" aria-hidden="true">
                <Icon name="box" />
              </span>
              <span className="project-current">
                <span className="project-caption">当前项目</span>
                <strong title={projects.current?.name}>
                  {projects.loading ? '正在加载项目…' : projects.current?.name || '选择项目'}
                </strong>
              </span>
              <svg className="project-chevron" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path
                  d="m4 6 4 4 4-4"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </summary>
            <div className="project-dropdown">
              <div className="project-dropdown-heading">切换项目</div>
              <div className="project-options" aria-label="可选项目">
                {projects.projects.map((project) => (
                  <button
                    type="button"
                    key={project.id}
                    className={`project-option${projects.selected === project.id ? ' selected' : ''}`}
                    aria-current={projects.selected === project.id ? 'true' : undefined}
                    title={project.name}
                    disabled={projects.loading}
                    onClick={() => chooseProject(project.id)}
                  >
                    <span>{project.name}</span>
                    <span className="project-selected-mark" aria-hidden="true">
                      {projects.selected === project.id ? '✓' : ''}
                    </span>
                  </button>
                ))}
                {!projects.projects.length && (
                  <p className="hint" role="status">
                    {projects.error ? '项目加载失败，请重试。' : '暂无可访问的项目。'}
                  </p>
                )}
              </div>
              <button
                className="collapsed-project-create"
                onClick={() => {
                  if (projectPicker.current) projectPicker.current.open = false;
                  setCreatingProject(true);
                }}
              >
                ＋ 创建项目
              </button>
            </div>
          </details>
          <button
            className="project-create"
            aria-label="创建项目"
            title="创建项目"
            onClick={() => {
              if (projectPicker.current) projectPicker.current.open = false;
              setCreatingProject(true);
            }}
          >
            +
          </button>
        </div>
        <nav className="nav-scroll" id="workspace-navigation" aria-label="主导航">
          {groups.map((group) => (
            <Fragment key={group.title}>
              {group.title && <div className="nav-label">{group.title}</div>}
              {group.items
                .filter(([path]) => path !== '/ai-acceptance' || user.platform_role === 'ADMIN')
                .map(([path, name, icon]) => (
                  <NavLink
                    key={path}
                    to={path}
                    end={path === '/'}
                    title={name}
                    aria-label={name}
                    onClick={() => setMenuOpen(false)}
                    className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}
                  >
                    <Icon name={icon} />
                    <span className="nav-text">{name}</span>
                  </NavLink>
                ))}
            </Fragment>
          ))}
        </nav>
      </aside>
      <div className="shell">
        <header className="topbar">
          <div className="row">
            <button
              className="mobile-toggle ghost small"
              aria-label="展开导航"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen(!menuOpen)}
            >
              ☰
            </button>
            <div className="breadcrumb">
              <span>工作空间</span>
              <span>/</span>
              <span>{projects.current?.name || '未选择项目'}</span>
              <span>/</span>
              <strong>{current}</strong>
            </div>
          </div>
          <div className="topbar-right">
            <span className="demo-label">GitHub 只读接入</span>
            <button className="ghost small" aria-label="说明" onClick={() => setHelp(!help)}>
              ⓘ
            </button>
            <details className="account-menu" ref={accountMenu}>
              <summary
                className="account-trigger"
                aria-label={`账号菜单：${user.display_name}`}
                title="账号菜单"
              >
                <span className="avatar" aria-hidden="true">
                  {user.display_name.slice(0, 1)}
                </span>
                <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path
                    d="m4 6 4 4 4-4"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </summary>
              <div className="account-dropdown">
                <div className="account-menu-info">
                  <strong>{user.display_name}</strong>
                  <span>账号：{user.login_name}</span>
                  <span>{platformRoleLabels[user.platform_role]}</span>
                </div>
                <button
                  type="button"
                  className="account-logout"
                  disabled={loggingOut}
                  onClick={logout}
                >
                  <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <path
                      d="M8 4H4v12h4m4-10 4 4-4 4m-4-4h8"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  {loggingOut ? '正在退出…' : '退出登录'}
                </button>
                {logoutError && (
                  <p className="form-error" role="alert">
                    {logoutError}
                  </p>
                )}
              </div>
            </details>
          </div>
        </header>
        <main className="main" tabIndex={-1}>
          {projects.error && (
            <div className="panel panel-pad mb" role="alert">
              {projects.error}
              <button className="small" onClick={projects.reload}>
                重新加载项目
              </button>
            </div>
          )}
          {creatingProject && (
            <CreateProjectDialog
              user={user}
              onSessionEnd={endSession}
              onClose={() => setCreatingProject(false)}
              onCreated={(project) => {
                setCreatingProject(false);
                projects.setSelected(project.id);
                projects.reload();
              }}
            />
          )}
          {help && (
            <div role="status" className="panel panel-pad mb">
              <p className="smalltext">Git 来源仅支持读取。</p>
            </div>
          )}
          <Routes>
            <Route
              path="/ai-acceptance"
              element={
                <AIResultsAcceptance
                  user={user}
                  pageCache={accountViews.acceptance}
                  projects={projects.projects}
                  projectsLoading={projects.loading}
                  onSelectProject={projects.setSelected}
                  onSessionEnd={endSession}
                />
              }
            />
            <Route
              path="/skills"
              element={
                <Skills user={user} onSessionEnd={endSession} pageCache={accountViews.skills} />
              }
            />
            <Route
              path="/"
              element={
                <ProjectOverview
                  key={`${user.id}:${projects.current?.id}`}
                  project={projects.current}
                  pageCache={projectViews.overview}
                  onSessionEnd={endSession}
                />
              }
            />
            <Route
              path="/prototypes"
              element={
                <Prototypes
                  key={`${projectId}:${documentId}`}
                  project={projects.current}
                  documentId={documentId}
                  pageCache={projectViews.prototypes}
                  onSessionEnd={endSession}
                />
              }
            />
            <Route
              path="/project"
              element={
                <ProjectSettings
                  key={projects.current?.id || 0}
                  project={projects.current}
                  pageCache={projectViews.settings}
                  user={user}
                  onChanged={projects.reload}
                  onSessionEnd={endSession}
                />
              }
            />
            <Route
              path="/documents"
              element={
                <Documents
                  key={`${projectId}:${documentId}`}
                  project={projects.current}
                  documentId={documentId}
                  pageCache={projectViews.documents}
                  onSessionEnd={endSession}
                />
              }
            />
            <Route
              path="/cases"
              element={
                <Cases
                  key={projects.current?.id || 0}
                  project={projects.current}
                  pageCache={projectViews.cases}
                  onSessionEnd={endSession}
                />
              }
            />
            <Route
              path="/requirements"
              element={
                <OverviewEntry
                  projectId={projects.current?.id}
                  projectLoading={projects.loading}
                  module="requirements"
                >
                  {(target) => (
                    <RiskReports
                      key={`${projects.current?.id}:${target?.recordType}:${target?.id}:${target?.state}`}
                      project={projects.current}
                      onSessionEnd={endSession}
                      overviewTarget={target}
                      pageCache={target ? undefined : projectViews.requirements}
                    />
                  )}
                </OverviewEntry>
              }
            />
            <Route
              path="/requirements/chat/:reportId"
              element={
                <RequirementChat
                  project={projects.current}
                  onSessionEnd={endSession}
                  pageCache={projectViews.requirementChat}
                />
              }
            />
            <Route
              path="/code"
              element={
                <OverviewEntry
                  projectId={projects.current?.id}
                  projectLoading={projects.loading}
                  module="code"
                >
                  {(target) => (
                    <CodeAnalysis
                      key={`${projects.current?.id}:${target?.recordType}:${target?.id}:${target?.group}:${target?.state}`}
                      project={projects.current}
                      user={user}
                      onSessionEnd={endSession}
                      overviewTarget={target}
                      pageCache={target ? undefined : projectViews.code}
                    />
                  )}
                </OverviewEntry>
              }
            />
            <Route
              path="/changes"
              element={
                <OverviewEntry
                  projectId={projects.current?.id}
                  projectLoading={projects.loading}
                  module="changes"
                >
                  {(target) => (
                    <ChangeAnalysis
                      key={`${projects.current?.id}:${target?.recordType}:${target?.id}:${target?.group}:${target?.state}`}
                      project={projects.current}
                      user={user}
                      onSessionEnd={endSession}
                      overviewTarget={target}
                      pageCache={target ? undefined : projectViews.changes}
                    />
                  )}
                </OverviewEntry>
              }
            />
            <Route
              path="/generate"
              element={
                <OverviewEntry
                  projectId={projects.current?.id}
                  projectLoading={projects.loading}
                  module="generate"
                >
                  {(target) => (
                    <CaseGeneration
                      key={`${projects.current?.id}:${target?.recordType}:${target?.id}:${target?.group}:${target?.state}`}
                      project={projects.current}
                      user={user}
                      onSessionEnd={endSession}
                      overviewTarget={target}
                      pageCache={target ? undefined : generationPageCache}
                    />
                  )}
                </OverviewEntry>
              }
            />
            <Route
              path="/coverage"
              element={
                <OverviewEntry
                  projectId={projects.current?.id}
                  projectLoading={projects.loading}
                  module="coverage"
                >
                  {(target) => (
                    <CaseAnalysis
                      key={`${projects.current?.id}:${target?.recordType}:${target?.id}:${target?.group}:${target?.state}`}
                      project={projects.current}
                      user={user}
                      onSessionEnd={endSession}
                      overviewTarget={target}
                      pageCache={target ? undefined : projectViews.coverage}
                    />
                  )}
                </OverviewEntry>
              }
            />
            {modules
              .filter(
                (m) =>
                  m[0] !== '/skills' &&
                  m[0] !== '/ai-acceptance' &&
                  m[0] !== '/' &&
                  m[0] !== '/platform' &&
                  m[0] !== '/project' &&
                  m[0] !== '/documents' &&
                  m[0] !== '/prototypes' &&
                  m[0] !== '/cases' &&
                  m[0] !== '/code' &&
                  m[0] !== '/changes' &&
                  m[0] !== '/generate' &&
                  m[0] !== '/coverage' &&
                  m[0] !== '/requirements',
              )
              .map(([path, name]) => (
                <Route key={path} path={path} element={<Pending name={name} />} />
              ))}
            <Route
              path="/platform"
              element={
                <Platform
                  user={user}
                  onSessionEnd={endSession}
                  onUserChange={onLogout}
                  pageCache={accountViews.platform}
                />
              }
            />
            <Route path="/interfaces" element={<Navigate to="/documents" replace />} />
            <Route path="/projects" element={<Navigate to="/project" replace />} />
            <Route path="/settings" element={<Navigate to="/platform" replace />} />
            <Route path="*" element={<Pending name="页面不存在" />} />
          </Routes>
          <footer className="footer-note">
            <span>VERITY · 让每一个质量判断都有依据</span>
            <span>
              {pathname === '/'
                ? '项目摘要 · 人工审阅'
                : pathname === '/ai-acceptance'
                  ? 'AI结果验收 · 管理员可见'
                  : pathname === '/changes'
                    ? '静态证据 · 人工审阅'
                    : '分析功能待接入'}
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
