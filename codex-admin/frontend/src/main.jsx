import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertTriangle, Database, Edit3, FileText, KeyRound, RefreshCw, Trash2, UploadCloud } from 'lucide-react';
import './styles.css';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const ACCOUNT_STATUSES = ['normal', 'limited', 'banned', 'expired', 'disabled'];

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) return null;
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

function StatCard({ icon, label, value, tone = 'default' }) {
  return (
    <div className={`stat-card ${tone}`}>
      <div className="stat-icon">{icon}</div>
      <div>
        <div className="stat-value">{value}</div>
        <div className="stat-label">{label}</div>
      </div>
    </div>
  );
}

function StatusBadge({ value }) {
  return <span className={`badge badge-${value}`}>{value}</span>;
}

function Field({ label, children }) {
  return (
    <label className="field-label">
      <span>{label}</span>
      {children}
    </label>
  );
}

function AccountEditDialog({ account, onChange, onClose, onSave, pending }) {
  if (!account) return null;
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="edit-account-title">
        <header className="modal-header">
          <div>
            <p className="eyebrow">Edit account</p>
            <h2 id="edit-account-title">编辑账号</h2>
          </div>
          <button type="button" className="mini" onClick={onClose}>关闭</button>
        </header>
        <form className="modal-form" onSubmit={onSave}>
          <Field label="Account ID">
            <input value={account.account_id || ''} onChange={(event) => onChange({ ...account, account_id: event.target.value })} />
          </Field>
          <Field label="DeviceID">
            <input value={account.device_id || ''} onChange={(event) => onChange({ ...account, device_id: event.target.value })} />
          </Field>
          <Field label="过期时间">
            <input value={account.expires_at || ''} onChange={(event) => onChange({ ...account, expires_at: event.target.value })} placeholder="例如 2099-01-01T00:00:00+00:00" />
          </Field>
          <Field label="状态">
            <select value={account.status || 'normal'} onChange={(event) => onChange({ ...account, status: event.target.value })}>
              {ACCOUNT_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
          </Field>
          <Field label="原因 / 备注">
            <textarea value={account.status_reason || ''} onChange={(event) => onChange({ ...account, status_reason: event.target.value })} placeholder="状态原因、维护备注或 fallback 说明" />
          </Field>
          <Field label="重新输入 auth.json（可选）">
            <textarea className="auth-json-edit" value={account.auth_json_text || ''} onChange={(event) => onChange({ ...account, auth_json_text: event.target.value })} placeholder='留空则不更新凭证。粘贴新 auth.json 后会校验 access_token / refresh_token / account_id 或 device_id。' />
          </Field>
          <p className="modal-note">安全限制：这里不会回显之前的 auth.json、access_token 或 refresh_token。需要更新凭证时，请在上方重新粘贴完整 auth.json。</p>
          <footer className="modal-actions">
            <button type="button" className="secondary" onClick={onClose} disabled={pending}>取消</button>
            <button type="submit" disabled={pending}>{pending ? '保存中...' : '保存修改'}</button>
          </footer>
        </form>
      </section>
    </div>
  );
}

function ConfirmDialog({ account, onCancel, onConfirm, pending }) {
  if (!account) return null;
  const target = account.account_id || account.device_id || `#${account.id}`;
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal danger-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-account-title" aria-describedby="delete-account-desc">
        <header className="modal-header">
          <div>
            <p className="eyebrow danger-text">Danger zone</p>
            <h2 id="delete-account-title">删除账号？</h2>
          </div>
        </header>
        <p id="delete-account-desc" className="modal-note">
          这会把账号 <span className="mono strong">{target}</span> 从默认账号库中移除。当前实现是软删除，后续仍可通过后端 restore 接口恢复。
        </p>
        <footer className="modal-actions">
          <button type="button" className="secondary" onClick={onCancel} disabled={pending}>取消</button>
          <button type="button" className="danger-primary" onClick={onConfirm} disabled={pending}>{pending ? '删除中...' : '删除账号'}</button>
        </footer>
      </section>
    </div>
  );
}

function App() {
  const [accounts, setAccounts] = useState({ summary: {}, items: [] });
  const [dashboard, setDashboard] = useState({ accounts: {}, research_notes: {}, exceptions: {}, api_keys: {} });
  const [notes, setNotes] = useState([]);
  const [exceptions, setExceptions] = useState([]);
  const [apiKeys, setApiKeys] = useState({ summary: {}, items: [] });
  const [authText, setAuthText] = useState('');
  const [noteForm, setNoteForm] = useState({ title: '', status: 'pending', content: '' });
  const [exceptionForm, setExceptionForm] = useState({ account_id: '', level: 'warning', message: '', detail: '' });
  const [apiKeyForm, setApiKeyForm] = useState({ name: '', rate_limit_per_minute: 60, model_scopes: 'codex-code,code-mini' });
  const [message, setMessage] = useState('');
  const [showDeleted, setShowDeleted] = useState(false);
  const [editingAccount, setEditingAccount] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [pendingAction, setPendingAction] = useState(false);

  async function loadAll(includeDeleted = showDeleted) {
    const [accountData, dashboardData, noteData, exceptionData, apiKeyData] = await Promise.all([
      api(`/api/accounts?include_deleted=${includeDeleted ? 'true' : 'false'}`),
      api('/api/dashboard'),
      api('/api/research-notes'),
      api('/api/exceptions'),
      api('/api/api-keys'),
    ]);
    setAccounts(accountData);
    setDashboard(dashboardData);
    setNotes(noteData.items || []);
    setExceptions(exceptionData.items || []);
    setApiKeys(apiKeyData);
  }

  useEffect(() => {
    loadAll(showDeleted).catch((error) => setMessage(`加载失败：${error.message}`));
  }, [showDeleted]);

  async function importAuth(event) {
    event.preventDefault();
    try {
      const parsed = JSON.parse(authText);
      await api('/api/accounts/import', { method: 'POST', body: JSON.stringify({ auth_json: parsed }) });
      setAuthText('');
      setMessage('auth.json 已导入/更新');
      await loadAll();
    } catch (error) {
      setMessage(`导入失败：${error.message}`);
    }
  }

  async function updateStatus(accountId, status) {
    try {
      await api(`/api/accounts/${accountId}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status, reason: `manual set ${status}` }),
      });
      setMessage(`账号 ${accountId} 已设置为 ${status}`);
      await loadAll();
    } catch (error) {
      setMessage(`状态更新失败：${error.message}`);
    }
  }

  async function saveEditingAccount(event) {
    event.preventDefault();
    if (!editingAccount) return;
    setPendingAction(true);
    try {
      let parsedAuthJson;
      if (editingAccount.auth_json_text?.trim()) {
        try {
          parsedAuthJson = JSON.parse(editingAccount.auth_json_text);
        } catch (error) {
          setMessage(`auth.json 格式错误：${error.message}`);
          return;
        }
      }
      const payload = {
        account_id: editingAccount.account_id,
        device_id: editingAccount.device_id,
        expires_at: editingAccount.expires_at || null,
        status: editingAccount.status,
        status_reason: editingAccount.status_reason || null,
      };
      if (parsedAuthJson) {
        payload.auth_json = parsedAuthJson;
      }
      await api(`/api/accounts/${editingAccount.id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      setMessage(`账号 ${editingAccount.id} 已更新`);
      setEditingAccount(null);
      await loadAll();
    } catch (error) {
      setMessage(`保存账号失败：${error.message}`);
    } finally {
      setPendingAction(false);
    }
  }

  async function deleteAccount() {
    if (!deleteTarget) return;
    setPendingAction(true);
    try {
      await api(`/api/accounts/${deleteTarget.id}`, { method: 'DELETE' });
      setMessage(`账号 ${deleteTarget.id} 已删除`);
      setDeleteTarget(null);
      await loadAll(false);
    } catch (error) {
      setMessage(`删除账号失败：${error.message}`);
    } finally {
      setPendingAction(false);
    }
  }

  async function restoreAccount(accountId) {
    try {
      await api(`/api/accounts/${accountId}/restore`, { method: 'POST' });
      setMessage(`账号 ${accountId} 已恢复`);
      await loadAll();
    } catch (error) {
      setMessage(`恢复账号失败：${error.message}`);
    }
  }

  async function createNote(event) {
    event.preventDefault();
    await api('/api/research-notes', { method: 'POST', body: JSON.stringify(noteForm) });
    setNoteForm({ title: '', status: 'pending', content: '' });
    setMessage('调研记录已保存');
    await loadAll();
  }

  async function createException(event) {
    event.preventDefault();
    await api('/api/exceptions', {
      method: 'POST',
      body: JSON.stringify({
        account_id: exceptionForm.account_id ? Number(exceptionForm.account_id) : null,
        level: exceptionForm.level,
        message: exceptionForm.message,
        detail: exceptionForm.detail,
      }),
    });
    setExceptionForm({ account_id: '', level: 'warning', message: '', detail: '' });
    setMessage('异常记录已保存');
    await loadAll();
  }

  async function createApiKey(event) {
    event.preventDefault();
    const scopes = apiKeyForm.model_scopes.split(',').map((item) => item.trim()).filter(Boolean);
    const created = await api('/api/api-keys', {
      method: 'POST',
      body: JSON.stringify({
        name: apiKeyForm.name,
        status: 'active',
        rate_limit_per_minute: Number(apiKeyForm.rate_limit_per_minute) || null,
        model_scopes: scopes,
      }),
    });
    setApiKeyForm({ name: '', rate_limit_per_minute: 60, model_scopes: 'codex-code,code-mini' });
    setMessage(`API Key 已创建，只显示一次：${created.key}`);
    await loadAll();
  }

  async function updateApiKeyStatus(apiKeyId, status) {
    await api(`/api/api-keys/${apiKeyId}`, { method: 'PATCH', body: JSON.stringify({ status }) });
    setMessage(`API Key ${apiKeyId} 已设置为 ${status}`);
    await loadAll();
  }

  async function deleteApiKey(apiKeyId) {
    await api(`/api/api-keys/${apiKeyId}`, { method: 'DELETE' });
    setMessage(`API Key ${apiKeyId} 已删除`);
    await loadAll();
  }

  const accountOptions = useMemo(() => accounts.items?.filter((account) => !account.deleted_at) || [], [accounts]);

  return (
    <main className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">Codex Account Admin</p>
          <h1>Codex 账号库管理后台</h1>
          <p>独立目录实现，管理 auth.json 账号库、调研记录与异常情况。后端默认 SQLite，后续可替换 MySQL/PostgreSQL。</p>
        </div>
        <button className="secondary" onClick={() => loadAll()}><RefreshCw size={16} />刷新</button>
      </header>

      {message && <div className="message" role="status" aria-live="polite">{message}</div>}

      <section className="grid stats">
        <StatCard icon={<Database />} label="账号总数" value={dashboard.accounts?.total || 0} />
        <StatCard icon={<Database />} label="正常账号" value={dashboard.accounts?.normal || 0} tone="ok" />
        <StatCard icon={<AlertTriangle />} label="异常账号" value={(dashboard.accounts?.limited || 0) + (dashboard.accounts?.banned || 0) + (dashboard.accounts?.expired || 0)} tone="warn" />
        <StatCard icon={<FileText />} label="调研记录" value={dashboard.research_notes?.total || 0} />
        <StatCard icon={<KeyRound />} label="对外 API Key" value={dashboard.api_keys?.total || 0} />
        <StatCard icon={<AlertTriangle />} label="异常记录" value={dashboard.exceptions?.total || 0} tone="danger" />
      </section>

      <section className="panel two-col">
        <form onSubmit={importAuth}>
          <h2><UploadCloud size={18} /> 导入 auth.json</h2>
          <textarea value={authText} onChange={(event) => setAuthText(event.target.value)} placeholder='粘贴单个 auth.json 内容，例如 {"tokens":{"access_token":"..."}}' />
          <button type="submit">导入/更新账号</button>
        </form>
        <div>
          <h2>状态说明</h2>
          <ul className="help-list">
            <li>normal：正常参与账号池</li>
            <li>limited：429/限流/熔断，临时摘除</li>
            <li>banned：风控或封禁，长期摘除</li>
            <li>expired：鉴权失败或刷新失败</li>
            <li>disabled：人工禁用</li>
          </ul>
        </div>
      </section>

      <section className="panel">
        <div className="panel-title-row">
          <div>
            <h2>账号库</h2>
            <p className="muted">默认只展示未删除账号。删除为软删除，不会返回 access_token / refresh_token / auth_raw。</p>
          </div>
          <label className="inline-toggle">
            <input type="checkbox" checked={showDeleted} onChange={(event) => setShowDeleted(event.target.checked)} />
            显示已删除
          </label>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">ID</th><th scope="col">Account</th><th scope="col">DeviceID</th><th scope="col">状态</th><th scope="col">失败</th><th scope="col">过期时间</th><th scope="col">原因</th><th scope="col">操作</th></tr></thead>
            <tbody>
              {accounts.items?.length === 0 && <tr><td colSpan="8" className="empty-cell">暂无账号。请先导入 auth.json。</td></tr>}
              {accounts.items?.map((account) => (
                <tr key={account.id} className={account.deleted_at ? 'deleted-row' : ''}>
                  <td>{account.id}</td>
                  <td>{account.account_id}</td>
                  <td className="mono wrap-cell">{account.device_id}</td>
                  <td><StatusBadge value={account.deleted_at ? 'deleted' : account.status} /></td>
                  <td>{account.failure_count}</td>
                  <td>{account.expires_at || '-'}</td>
                  <td className="reason-cell">{account.deleted_reason || account.status_reason || '-'}</td>
                  <td className="actions action-bar">
                    {account.deleted_at ? (
                      <button type="button" className="mini" onClick={() => restoreAccount(account.id)}>恢复</button>
                    ) : (
                      <>
                        <button type="button" className="mini" onClick={() => setEditingAccount({ ...account })}><Edit3 size={13} />编辑</button>
                        <select className="mini-select" value={account.status} onChange={(event) => updateStatus(account.id, event.target.value)} aria-label={`设置账号 ${account.id} 状态`}>
                          {ACCOUNT_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
                        </select>
                        <button type="button" className="mini danger-button" onClick={() => setDeleteTarget(account)}><Trash2 size={13} />删除</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2>对外 API Key 管理</h2>
        <form className="api-key-form" onSubmit={createApiKey}>
          <input value={apiKeyForm.name} onChange={(event) => setApiKeyForm({ ...apiKeyForm, name: event.target.value })} placeholder="Key 名称，例如 cursor-client" />
          <input type="number" value={apiKeyForm.rate_limit_per_minute} onChange={(event) => setApiKeyForm({ ...apiKeyForm, rate_limit_per_minute: event.target.value })} placeholder="每分钟限流" />
          <input value={apiKeyForm.model_scopes} onChange={(event) => setApiKeyForm({ ...apiKeyForm, model_scopes: event.target.value })} placeholder="模型范围，逗号分隔" />
          <button>创建 API Key</button>
        </form>
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">ID</th><th scope="col">名称</th><th scope="col">Key 预览</th><th scope="col">状态</th><th scope="col">限流/分钟</th><th scope="col">模型权限</th><th scope="col">最后使用</th><th scope="col">操作</th></tr></thead>
            <tbody>
              {apiKeys.items?.map((item) => (
                <tr key={item.id}>
                  <td>{item.id}</td>
                  <td>{item.name}</td>
                  <td className="mono">{item.key_preview}</td>
                  <td><StatusBadge value={item.status} /></td>
                  <td>{item.rate_limit_per_minute || '-'}</td>
                  <td>{item.model_scopes?.join(', ') || '全部'}</td>
                  <td>{item.last_used_at || '-'}</td>
                  <td className="actions">
                    <button type="button" className="mini" onClick={() => updateApiKeyStatus(item.id, 'active')}>启用</button>
                    <button type="button" className="mini" onClick={() => updateApiKeyStatus(item.id, 'disabled')}>禁用</button>
                    <button type="button" className="mini danger-button" onClick={() => deleteApiKey(item.id)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid two-panels">
        <div className="panel">
          <h2>调研情况</h2>
          <form className="compact-form" onSubmit={createNote}>
            <input value={noteForm.title} onChange={(event) => setNoteForm({ ...noteForm, title: event.target.value })} placeholder="标题" />
            <select value={noteForm.status} onChange={(event) => setNoteForm({ ...noteForm, status: event.target.value })}>
              <option value="pending">pending</option>
              <option value="done">done</option>
              <option value="blocked">blocked</option>
            </select>
            <textarea value={noteForm.content} onChange={(event) => setNoteForm({ ...noteForm, content: event.target.value })} placeholder="调研内容 / 结论 / 待验证点" />
            <button>保存调研记录</button>
          </form>
          <div className="list">
            {notes.map((note) => <article key={note.id}><StatusBadge value={note.status} /><strong>{note.title}</strong><p>{note.content}</p></article>)}
          </div>
        </div>

        <div className="panel">
          <h2>异常情况</h2>
          <form className="compact-form" onSubmit={createException}>
            <select value={exceptionForm.account_id} onChange={(event) => setExceptionForm({ ...exceptionForm, account_id: event.target.value })}>
              <option value="">不绑定账号</option>
              {accountOptions.map((account) => <option value={account.id} key={account.id}>#{account.id} {account.device_id}</option>)}
            </select>
            <select value={exceptionForm.level} onChange={(event) => setExceptionForm({ ...exceptionForm, level: event.target.value })}>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="error">error</option>
            </select>
            <input value={exceptionForm.message} onChange={(event) => setExceptionForm({ ...exceptionForm, message: event.target.value })} placeholder="异常摘要，例如 429 quota" />
            <textarea value={exceptionForm.detail} onChange={(event) => setExceptionForm({ ...exceptionForm, detail: event.target.value })} placeholder="详细情况" />
            <button>保存异常记录</button>
          </form>
          <div className="list">
            {exceptions.map((item) => <article key={item.id}><StatusBadge value={item.level} /><strong>{item.message}</strong><p>{item.detail}</p><small>{item.device_id || '未绑定账号'} · {item.created_at}</small></article>)}
          </div>
        </div>
      </section>

      <AccountEditDialog account={editingAccount} onChange={setEditingAccount} onClose={() => setEditingAccount(null)} onSave={saveEditingAccount} pending={pendingAction} />
      <ConfirmDialog account={deleteTarget} onCancel={() => setDeleteTarget(null)} onConfirm={deleteAccount} pending={pendingAction} />
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
