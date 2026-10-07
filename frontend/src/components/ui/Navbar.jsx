import React, {useEffect, useRef, useState} from "react";
import Icon from "./icons";

/**
 * Navbar — перенос верхней панели из дизайн-проекта (src/components/Navbar.tsx):
 * utility-бар (хлебные крошки, поиск/команды, тема, статус согласований,
 * идентификатор пользователя) и строка вкладок с индикатором активной секции.
 *
 * Отличия от дизайн-проекта (по правилам объединения):
 *  - нет переключателя RBAC-пользователей и регистрации (демо-данные запрещены):
 *    чип идентичности показывает только реального /me и открывает форму доступа;
 *  - нет захардкоженного названия организации — хлебные крошки из фактического
 *    контекста приложения; нет «live»-бейджей 1C/Legal RAG с фиктивными числами.
 *
 * @param {{
 *   tabs: Array<[string, string, string]>, activeTab: string,
 *   onNavigate: (tab: string) => void,
 *   pendingApprovalsCount: number, activeTasksCount: number,
 *   me: {user_id: string, role: string}|null,
 *   onLogin: (mode: "api_key"|"oidc"|"invitation", credential: string) => void,
 *   onLogout: () => void,
 *   theme: "light"|"dark", onToggleTheme: () => void,
 *   onOpenPalette: () => void, onRefresh: () => void, busy: boolean,
 * }} props
 */
export default function Navbar({tabs, activeTab, onNavigate, pendingApprovalsCount,
  activeTasksCount, me, onLogin, onLogout, theme, onToggleTheme, onOpenPalette, onRefresh, busy}) {
  const [loginOpen, setLoginOpen] = useState(false);
  const [credential, setCredential] = useState("");
  const [loginMode, setLoginMode] = useState("api_key");
  const isMac = typeof navigator !== "undefined" && /Mac|iPod|iPhone|iPad/.test(navigator.userAgent);
  const modKey = isMac ? "⌘" : "Ctrl";
  const panelRef = useRef(null);

  useEffect(() => {
    if (!loginOpen) return;
    const close = event => { if (!panelRef.current?.contains(event.target)) setLoginOpen(false); };
    const escape = event => { if (event.key === "Escape") setLoginOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, [loginOpen]);

  return <header className="navbar" role="banner">
    <div className="navbar-inner">
      <div className="navbar-meta">
        <strong>AI-Офис собственника</strong>
        <Icon name="chevronRight" size={13} className="navbar-chevron" />
        <span className="navbar-version">v3 · integration</span>
        {pendingApprovalsCount > 0 && <button type="button" className="navbar-badge navbar-badge-alert"
          onClick={() => onNavigate("approvals")} title="Открыть согласования">
          <Icon name="clock" size={12} className="icon" />
          Согласований: {pendingApprovalsCount}
        </button>}
      </div>
      <div className="navbar-tools">
        <button type="button" className="navbar-button" onClick={onOpenPalette}
          title="Открыть командную строку и поиск (Ctrl K)">
          <Icon name="search" size={13} />
          <span className="navbar-search-label">Поиск и команды</span>
          <kbd>{modKey}K</kbd>
        </button>
        <button type="button" className="navbar-button" disabled={busy} onClick={onRefresh}
          title="Обновить данные из API">
          <Icon name="refresh" size={13} />
          Обновить
        </button>
        <button type="button" className="navbar-button" onClick={onToggleTheme}
          title={theme === "light" ? "Переключить в тёмную тему" : "Переключить в светлую тему"}>
          <Icon name={theme === "light" ? "moon" : "sun"} size={13} />
          {theme === "light" ? "Dark" : "Light"}
        </button>
        <div className="navbar-login-anchor" ref={panelRef} style={{position: "relative"}}>
          <button type="button" className="navbar-identity navbar-button" aria-expanded={loginOpen}
            onClick={() => setLoginOpen(open => !open)}
            title={me ? `${me.user_id} · ${me.role}` : "Указать ключ доступа"}>
            <span className="navbar-identity-icon"><Icon name="user" size={12} /></span>
            <span><b>{me ? me.user_id : "Нет доступа"}</b>
              <small>{me?.role || "Авторизуйтесь"}</small></span>
          </button>
          {loginOpen && <form className="login-form navbar-login-panel" onSubmit={event => {
            event.preventDefault();
            if (busy) return;
            onLogin(loginMode, credential);
            setCredential("");
            setLoginOpen(false);
          }}>
            <label>Способ входа
              <select value={loginMode} onChange={event => setLoginMode(event.target.value)}>
                <option value="api_key">Ключ API</option>
                <option value="oidc">OIDC-токен</option>
                <option value="invitation">Приглашение</option>
              </select>
            </label>
            <label>{loginMode === "api_key" ? "Ключ доступа" :
              loginMode === "oidc" ? "Токен провайдера" : "Токен приглашения"}
              <input type="password" autoComplete="off" autoFocus value={credential}
                onChange={event => setCredential(event.target.value)} />
            </label>
            <div className="actions">
              <button disabled={busy}>Подключиться</button>
              <button type="button" className="quiet" disabled={busy}
                onClick={() => {onLogout(); setLoginOpen(false);}}>Выйти</button>
            </div>
            <p>Access и refresh-токены хранятся только в памяти вкладки.</p>
          </form>}
        </div>
      </div>
    </div>
    <nav className="navbar-tabs" aria-label="Разделы">
      {tabs.map(([id, label, icon]) => {
        const active = activeTab === id;
        return <button key={id} type="button" className="navbar-tab" aria-current={active ? "page" : undefined}
          onClick={() => onNavigate(id)}>
          <Icon name={icon} size={14} />
          <span>{label}</span>
          {id === "approvals" && pendingApprovalsCount > 0 &&
            <span className="navbar-tab-count navbar-tab-count-waiting">{pendingApprovalsCount}</span>}
          {id === "tasks" && activeTasksCount > 0 &&
            <span className="navbar-tab-count">{activeTasksCount}</span>}
        </button>;
      })}
    </nav>
  </header>;
}
