import { Form } from './Form';
import { aiErrors } from './aiErrors';
import { FormSelect, Select } from './FormSelect';
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { apiRequest, encryptedRequest, apiErrorMessage } from './api/http';

import { CaseDialog } from './CaseDialog';
import { useBlocker } from 'react-router-dom';
import { callModeName, parseAISettings } from './aiConfiguration';
import type { AISettings, CallMode, Configuration } from './aiConfiguration';

const messages: Record<string, string> = {
  ...aiErrors,
  invalid_request: '请检查必填字段、密钥格式，以及 API 地址是否为有效的 HTTPS 地址。',
  invalid_password_envelope: '安全校验已失效，请重新提交。',
  ai_configuration_changed: '配置已被修改，请重新加载后再操作。',
  ai_key_required: '首次配置需要填写 API Key。',
  ai_new_address_requires_key: 'API 地址已变化，请重新填写与新地址对应的 API Key。',
  ai_key_storage_unavailable: '密钥存储暂不可用，请联系平台管理员检查后端加密配置。',
  ai_parameters_rejected: '服务不接受当前参数，请核对模型及推理强度支持范围；未自动降档或重试。',
  ai_auth_failed: '密钥无效或已过期，请检查 API Key。',
  ai_access_denied: '服务拒绝访问，请检查密钥权限和模型授权。',
  ai_model_or_endpoint_unavailable: '模型或接口不可用，请检查模型名称和 API 地址。',
  ai_models_unavailable: '当前服务没有提供模型列表，请手动输入模型 ID。',
  ai_quota_or_rate_limit: '服务额度不足或请求过于频繁，请在供应商处核对。',
  ai_timeout: '测试超时，服务端可能已处理并计费。请核对后再试。',
  ai_connection_failed: '无法连接 AI 服务，请检查网络和服务地址。',
  ai_invalid_response: '服务返回的内容不符合 Responses 协议，未确认测试成功。',
  ai_incomplete_response: '模型未完成文本回复，未确认测试成功。请检查模型兼容性或输出限制。',
  ai_upstream_error: 'AI 服务返回错误，请检查中转服务状态和接口兼容性。',
  ai_gateway_error: 'AI中转服务返回502，请检查中转与上游模型的连接。',
  ai_service_unavailable: 'AI服务暂不可用（503）。',
  ai_gateway_timeout: 'AI中转服务等待上游超时（504），请检查中转超时配置。',
  too_many_attempts: '测试过于频繁，请稍后再试。',
  origin_not_allowed: '当前访问地址未获允许。',
  service_unavailable: '服务暂不可用，请稍后重试。',
};
const modelMessages = {
  ...messages,
  ai_key_required: '请先填写 API Key，或保存配置后使用已保存的密钥。',
  ai_timeout: '读取模型列表超时，请手动输入模型 ID 或稍后重试。',
  ai_invalid_response: '模型列表格式异常，请手动输入模型 ID。',
};

export function AIService({
  onSessionEnd,
  onDirtyChange,
}: {
  onSessionEnd: () => void;
  onDirtyChange?: (value: boolean) => void;
}) {
  const [settings, setSettings] = useState<AISettings | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<CallMode>('RESPONSES_API');
  const [dirty, setDirty] = useState(false);
  const [pendingMode, setPendingMode] = useState<CallMode | 'reload' | null>(null);
  const blocker = useBlocker(dirty);
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true);
      setError('');
      try {
        const value = parseAISettings(
          await apiRequest<unknown>('/api/ai-service', {
            signal: controller.signal,
            timeoutMs: 10000,
          }),
        );
        if (!controller.signal.aborted) {
          setSettings(value);
          setMode(value.call_mode);
          setDirty(false);
        }
      } catch (error) {
        if (!controller.signal.aborted) setError(apiErrorMessage(error, onSessionEnd, messages));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [revision, onSessionEnd]);

  return (
    <section className="panel panel-pad">
      <h2>AI 服务</h2>
      <div className="ai-providers mt">
        <div className="ai-provider selected">
          <span className="ai-provider-logo">◎</span>
          <div>
            <h3>Codex</h3>
            <span className="hint">API / Codex CLI</span>
          </div>
        </div>
        <div className="ai-provider disabled">
          <span className="ai-provider-logo">C</span>
          <div>
            <h3>Claude</h3>
            <span className="hint">后续支持</span>
          </div>
        </div>
        <div className="ai-provider disabled">
          <span className="ai-provider-logo">D</span>
          <div>
            <h3>DeepSeek</h3>
            <span className="hint">后续支持</span>
          </div>
        </div>
      </div>
      <div className="divider" />
      {loading ? (
        <p role="status">正在加载配置…</p>
      ) : (
        settings && (
          <>
            <p className="hint mb">当前已保存方式：{callModeName(settings.call_mode)}</p>
            <FormSelect
              label="调用方式"
              value={mode}
              disabled={busy}
              options={[
                { value: 'RESPONSES_API', label: 'API' },
                { value: 'CODEX_EXEC', label: 'Codex CLI' },
              ]}
              onChange={(value) => {
                const next = value as CallMode;
                if (dirty) setPendingMode(next);
                else {
                  setMode(next);
                  setError('');
                  setNotice('');
                }
              }}
            />
            {mode === 'CODEX_EXEC' && (
              <p className="hint mt" role="status">
                CLI：
                {
                  {
                    available: '可用',
                    not_installed: '未安装',
                    unsupported_version: '版本不受支持',
                    unverified: '未验证',
                  }[settings.cli_runtime.status]
                }
                {settings.cli_runtime.version && ` · ${settings.cli_runtime.version}`}。
                {settings.cli_runtime.available && '可能多轮计费；PDF 请使用 API。'}
                {!settings.cli_runtime.available &&
                  (settings.cli_runtime.probe_available
                    ? '可测试连接，业务调用未启用。'
                    : '当前仅可保存配置，业务调用未启用。')}
              </p>
            )}
            <ConnectionForm
              key={`${revision}-${mode}`}
              mode={mode}
              preferenceVersion={settings.preference_version}
              cliAvailable={settings.cli_runtime.available}
              cliProbeAvailable={settings.cli_runtime.probe_available ?? false}
              setDirty={setDirty}
              configuration={mode === 'CODEX_EXEC' ? settings.cli : settings.personal}
              busy={busy}
              setBusy={setBusy}
              onSessionEnd={onSessionEnd}
              onError={setError}
              onNotice={setNotice}
              notice={notice}
              onSaved={(value) => {
                setSettings(value);
                setDirty(false);
              }}
            />
          </>
        )
      )}
      {error && (
        <p className="form-error mt" role="alert">
          {error}
        </p>
      )}
      {!loading && (
        <button
          className="small mt"
          disabled={busy}
          onClick={() => {
            setNotice('');
            if (dirty) setPendingMode('reload');
            else setRevision((value) => value + 1);
          }}
        >
          重新加载配置
        </button>
      )}
      {(pendingMode !== null || blocker.state === 'blocked') && (
        <CaseDialog
          title="放弃未保存内容？"
          busy={busy}
          onClose={() => {
            setPendingMode(null);
            if (blocker.state === 'blocked') blocker.reset();
          }}
        >
          <p>当前方式的表单有未保存内容。放弃后将清空本次填写的 Key。</p>
          <div className="row mt">
            <button
              onClick={() => {
                setPendingMode(null);
                if (blocker.state === 'blocked') blocker.reset();
              }}
            >
              继续编辑
            </button>
            <button
              className="primary"
              onClick={() => {
                setDirty(false);
                setError('');
                setNotice('');
                if (blocker.state === 'blocked') blocker.proceed();
                else if (pendingMode === 'reload') setRevision((v) => v + 1);
                else if (pendingMode) setMode(pendingMode);
                setPendingMode(null);
              }}
            >
              放弃并继续
            </button>
          </div>
        </CaseDialog>
      )}
    </section>
  );
}

function ConnectionForm({
  mode,
  preferenceVersion,
  cliAvailable,
  cliProbeAvailable,
  setDirty,
  configuration,
  busy,
  setBusy,
  onSessionEnd,
  onError,
  onNotice,
  notice,
  onSaved,
}: {
  mode: CallMode;
  preferenceVersion: number;
  cliAvailable: boolean;
  cliProbeAvailable: boolean;
  setDirty: (value: boolean) => void;
  configuration: Configuration | null;
  busy: boolean;
  setBusy: (value: boolean) => void;
  onSessionEnd: () => void;
  onError: (value: string) => void;
  onNotice: (value: string) => void;
  notice: string;
  onSaved: (value: AISettings) => void;
}) {
  const [name, setName] = useState(configuration?.name || '');
  const [url, setUrl] = useState(configuration?.base_url || 'https://api.openai.com/v1');
  const [model, setModel] = useState(configuration?.model || '');
  const [effort, setEffort] = useState(configuration?.reasoning_effort || 'default');
  const [key, setKey] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [modelNotice, setModelNotice] = useState('');

  async function loadModels() {
    if (busy) return;
    setBusy(true);
    setModelNotice('');
    try {
      const result = await encryptedRequest<unknown>(
        '/api/ai-service/personal/models',
        { base_url: url, api_key: key, version: configuration?.version || 0 },
        20000,
      );
      if (
        !result ||
        typeof result !== 'object' ||
        !('models' in result) ||
        !Array.isArray(result.models) ||
        result.models.length > 1000 ||
        !result.models.every(
          (value) => typeof value === 'string' && value.length > 0 && value.length <= 160,
        )
      )
        throw new Error('ai_invalid_response');
      setModels(result.models);
      setModelNotice(
        result.models.length
          ? `已读取 ${result.models.length} 个模型 ID；选择后仍需测试连接。`
          : '服务未返回模型 ID，请手动输入。',
      );
    } catch (error) {
      setModels([]);
      setModelNotice(apiErrorMessage(error, onSessionEnd, modelMessages));
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    const test = submitter instanceof HTMLButtonElement && submitter.value === 'test';
    setBusy(true);
    onError('');
    onNotice('');
    try {
      const result = await encryptedRequest<unknown>(
        `/api/ai-service/${test ? 'test' : 'configuration'}`,
        {
          name,
          base_url: url,
          model,
          reasoning_effort: effort,
          api_key: key,
          version: configuration?.version || 0,
          call_mode: mode,
          ...(test
            ? {}
            : {
                preference_version: preferenceVersion,
                activate: mode === 'RESPONSES_API' || cliAvailable,
              }),
        },
        test ? 130000 : 15000,
      );
      if (test) {
        if (
          !result ||
          typeof result !== 'object' ||
          !('status' in result) ||
          !('capability' in result) ||
          result.status !== 'success' ||
          result.capability !== 'text'
        )
          throw new Error('ai_invalid_response');
        onNotice(
          mode === 'CODEX_EXEC'
            ? 'CLI 固定文字连接测试成功；配置未自动保存或激活，业务分析及附件能力尚未验证。'
            : '连接测试成功！当前配置可正常返回文本。配置尚未自动保存，图片能力未验证。',
        );
      } else {
        const saved = parseAISettings(result);
        onSaved(saved);
        setKey('');
        onNotice(
          mode === 'CODEX_EXEC' && !cliAvailable
            ? `CLI 配置已保存；未激活。当前实际方式：${callModeName(parseAISettings(result).call_mode)}。`
            : mode === 'CODEX_EXEC'
              ? '已保存并使用 Codex CLI；新任务按原生方式执行，可能多轮请求、自动重试或压缩上下文。保存未触发模型调用。'
              : `配置已保存并使用；新任务将使用 ${callModeName(mode)}。保存不代表测试通过。`,
        );
      }
    } catch (error) {
      onError(apiErrorMessage(error, onSessionEnd, messages));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Form
      onSubmit={submit}
      onChange={() => {
        onNotice('');
        onError('');
        setDirty(true);
      }}
    >
      <div className="ai-form-grid">
        <label className="form-field ai-full">
          配置名称
          <input
            required
            maxLength={80}
            value={name}
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="form-field ai-full">
          服务地址
          <input
            required
            type="url"
            maxLength={500}
            value={url}
            disabled={busy}
            onChange={(event) => {
              setUrl(event.target.value);
              setModels([]);
              setModelNotice('');
            }}
          />
        </label>
        <label className="form-field">
          模型名称
          <span className="ai-model-control">
            <FormSelect
              hideLabel
              label="模型名称"
              editable
              required
              maxLength={160}
              placeholder="选择或输入模型 ID"
              value={model}
              disabled={busy}
              options={models.map((id) => ({ value: id, label: id }))}
              onChange={(value) => {
                setModel(value);
                setDirty(true);
                onNotice('');
                onError('');
              }}
            />
            {mode === 'RESPONSES_API' && (
              <button
                type="button"
                className="small"
                disabled={busy || !url}
                onClick={() => void loadModels()}
              >
                {busy ? '正在读取…' : '读取模型列表'}
              </button>
            )}
          </span>
          {modelNotice && (
            <span className="hint" role="status">
              {modelNotice}
            </span>
          )}
        </label>
        <label className="form-field">
          推理强度
          <Select
            value={effort}
            disabled={busy}
            onChange={(event) => {
              setEffort(event);
              setDirty(true);
              onNotice('');
              onError('');
            }}
          >
            <option value="default">默认（由服务决定）</option>
            <option value="none">不启用推理（none）</option>
            <option value="minimal">最低（minimal）</option>
            <option value="low">低（low）</option>
            <option value="medium">中（medium）</option>
            <option value="high">高（high）</option>
            <option value="xhigh">很高（xhigh）</option>
            <option value="max">最大（max）</option>
            <option value="ultra">极高（ultra）</option>
          </Select>
        </label>
        <label className="form-field ai-full">
          API Key
          <input
            required={!configuration?.has_key}
            type="password"
            autoComplete="new-password"
            maxLength={1024}
            value={key}
            disabled={busy}
            placeholder={configuration?.has_key ? '已配置；留空保留，填写替换' : '请输入 API Key'}
            onChange={(event) => {
              setKey(event.target.value);
              setModels([]);
              setModelNotice('');
            }}
          />
        </label>
      </div>
      <div className="row mt">
        <button
          type="submit"
          value="test"
          disabled={busy || (mode === 'CODEX_EXEC' && !cliProbeAvailable)}
        >
          测试当前方式
        </button>
        <button type="submit" value="save" className="primary" disabled={busy}>
          {mode === 'CODEX_EXEC' && !cliAvailable ? '仅保存配置' : '保存并使用'}
        </button>
        {busy && <span role="status">正在处理…</span>}
      </div>
      {notice && (
        <p className="account-notice mt" role="status" aria-live="polite">
          <strong>✓ {notice}</strong>
        </p>
      )}
      <p className="hint mt">
        {mode === 'CODEX_EXEC'
          ? '连接测试仅发送“请只回复 OK”，最多1次请求，可能计费；最长等待约120秒。'
          : '连接测试仅发送“请只回复 OK”，可能计费；最长等待约120秒。'}
        修改地址后请重新填写密钥。
      </p>
    </Form>
  );
}
