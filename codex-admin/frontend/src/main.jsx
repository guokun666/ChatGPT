import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertTriangle, Database, FileText, KeyRound, RefreshCw, UploadCloud } from 'lucide-react';
import './styles.css';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json();
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

function App() {
  const [accounts, setAccounts] = useState({ summary: {}, items: [] });
  const [dashboard, setDashboard] = useState({ accounts: {}, research_notes: {}, exceptions: {} });
  const [notes, setNotes] = useState([]);
  const [exceptions, setExceptions] = useState([]);
  const [apiKeys, setApiKeys] = useState({ summary: {}, items: [] });
  const [authText, setAuthText] = useState('');
  const [noteForm, setNoteForm] = useState({ title: '', status: 'pending', content: '' });
  const [exceptionForm, setExceptionForm] = useState({ account_id: '', level: 'warning', message: '', detail: '' });
  const [apiKeyForm, setApiKeyForm] = useState({ name: '', rate_limit_per_minute: 60, model_scopes: 'codex-code,code-mini' });
  const [message, setMessage] = useState('');

  async function loadAll() {
    const [accountData, dashboardData, noteData, exceptionData, apiKeyData] = await Promise.all([
      api('/api/accounts'),
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
    loadAll().catch((error) => setMessage(`加载失败：${error.message}`));
  }, []);

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
    await api(`/api/accounts/${accountId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status, reason: `manual set ${status}` }),
    });
    setMessage(`账号 ${accountId} 已设置为 ${status}`);
    await loadAll();
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

  const accountOptions = useMemo(() => accounts.items || [], [accounts]);

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

      {message && <div className="message">{message}</div>}

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
          <textarea value={authText} onChange={(e) => setAuthText(e.target.value)} placeholder='粘贴单个 auth.json 内容，例如 {"device_id":"..."}' />
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
        <h2>账号库</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>Account</th><th>DeviceID</th><th>状态</th><th>失败</th><th>过期时间</th><th>原因</th><th>操作</th></tr></thead>
            <tbody>
              {accounts.items?.map((account) => (
                <tr key={account.id}>
                  <td>{account.id}</td>
                  <td>{account.account_id}</td>
                  <td className="mono">{account.device_id}</td>
                  <td><StatusBadge value={account.status} /></td>
                  <td>{account.failure_count}</td>
                  <td>{account.expires_at || '-'}</td>
                  <td>{account.status_reason || '-'}</td>
                  <td className="actions">
                    {['normal', 'limited', 'banned', 'expired', 'disabled'].map((status) => (
                      <button key={status} className="mini" onClick={() => updateStatus(account.id, status)}>{status}</button>
                    ))}
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
          <input value={apiKeyForm.name} onChange={(e) => setApiKeyForm({ ...apiKeyForm, name: e.target.value })} placeholder="Key 名称，例如 cursor-client" />
          <input type="number" value={apiKeyForm.rate_limit_per_minute} onChange={(e) => setApiKeyForm({ ...apiKeyForm, rate_limit_per_minute: e.target.value })} placeholder="每分钟限流" />
          <input value={apiKeyForm.model_scopes} onChange={(e) => setApiKeyForm({ ...apiKeyForm, model_scopes: e.target.value })} placeholder="模型范围，逗号分隔" />
          <button>创建 API Key</button>
        </form>
        <div className="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>名称</th><th>Key 预览</th><th>状态</th><th>限流/分钟</th><th>模型权限</th><th>最后使用</th><th>操作</th></tr></thead>
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
                    <button className="mini" onClick={() => updateApiKeyStatus(item.id, 'active')}>启用</button>
                    <button className="mini" onClick={() => updateApiKeyStatus(item.id, 'disabled')}>禁用</button>
                    <button className="mini danger-button" onClick={() => deleteApiKey(item.id)}>删除</button>
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
            <input value={noteForm.title} onChange={(e) => setNoteForm({ ...noteForm, title: e.target.value })} placeholder="标题" />
            <select value={noteForm.status} onChange={(e) => setNoteForm({ ...noteForm, status: e.target.value })}>
              <option value="pending">pending</option>
              <option value="done">done</option>
              <option value="blocked">blocked</option>
            </select>
            <textarea value={noteForm.content} onChange={(e) => setNoteForm({ ...noteForm, content: e.target.value })} placeholder="调研内容 / 结论 / 待验证点" />
            <button>保存调研记录</button>
          </form>
          <div className="list">
            {notes.map((note) => <article key={note.id}><StatusBadge value={note.status} /><strong>{note.title}</strong><p>{note.content}</p></article>)}
          </div>
        </div>

        <div className="panel">
          <h2>异常情况</h2>
          <form className="compact-form" onSubmit={createException}>
            <select value={exceptionForm.account_id} onChange={(e) => setExceptionForm({ ...exceptionForm, account_id: e.target.value })}>
              <option value="">不绑定账号</option>
              {accountOptions.map((account) => <option value={account.id} key={account.id}>#{account.id} {account.device_id}</option>)}
            </select>
            <select value={exceptionForm.level} onChange={(e) => setExceptionForm({ ...exceptionForm, level: e.target.value })}>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="error">error</option>
            </select>
            <input value={exceptionForm.message} onChange={(e) => setExceptionForm({ ...exceptionForm, message: e.target.value })} placeholder="异常摘要，例如 429 quota" />
            <textarea value={exceptionForm.detail} onChange={(e) => setExceptionForm({ ...exceptionForm, detail: e.target.value })} placeholder="详细情况" />
            <button>保存异常记录</button>
          </form>
          <div className="list">
            {exceptions.map((item) => <article key={item.id}><StatusBadge value={item.level} /><strong>{item.message}</strong><p>{item.detail}</p><small>{item.device_id || '未绑定账号'} · {item.created_at}</small></article>)}
          </div>
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
