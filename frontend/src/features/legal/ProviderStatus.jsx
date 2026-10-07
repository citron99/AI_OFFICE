import React, {useEffect, useState} from "react";
import Icon from "../../components/ui/icons";
import {formatLicenseScope, providerIsActive} from "./legalProviderStatus";

const modeLabels = {
  consultant_plus: "КонсультантПлюс",
  consultant: "КонсультантПлюс",
  builtin_corpus: "Встроенный корпус источников",
  mock: "Тестовый провайдер",
};

/**
 * Статус юридического провайдера (Консультант+ и аналоги) из
 * GET /api/v1/legal/provider-status → {mode, status, license_scope}.
 *
 * Эндпоинт может отсутствовать в текущем контуре — тогда показывается явное
 * состояние «статус недоступен» без подмены данных. Данные только из API.
 *
 * @param {{request: (path: string, options?: object) => Promise<any>}} props
 *   request — функция запроса API-клиента (см. src/api/client.js).
 */
export default function ProviderStatus({request}) {
  const [state, setState] = useState({status: "loading"});

  useEffect(() => {
    let active = true;
    setState({status: "loading"});
    request("/legal/provider-status")
      .then(provider => { if (active) setState({status: "ready", provider}); })
      .catch(reason => { if (active) setState({status: "unavailable", error: reason?.message}); });
    return () => { active = false; };
  }, [request]);

  const provider = state.provider;
  const isActive = providerIsActive(provider?.status);
  const scope = formatLicenseScope(provider?.license_scope);
  return <section className="provider-card" aria-label="Статус юридического провайдера">
    <div className="provider-id">
      <span className="provider-id-icon"><Icon name="book" size={17} /></span>
      <div>
        <b>{state.status === "ready" ? (modeLabels[provider?.mode] || provider?.mode || "Юридический провайдер")
          : "Юридический провайдер"}</b>
        <small>{state.status === "ready"
          ? "Правовая база, доступная юридическому агенту для поиска оснований."
          : state.status === "loading"
            ? "Запрашиваем статус провайдера…"
            : `Статус недоступен: ${state.error || "эндпоинт не отвечает"}.`}</small>
      </div>
    </div>
    <div className="provider-flags">
      {state.status === "loading" && <span className="provider-flag"><span className="pulse" />проверяем…</span>}
      {state.status === "ready" && <>
        <span className={`provider-flag ${isActive ? "provider-active" : "provider-inactive"}`}>
          <span className="pulse" />{isActive ? "активен" : `статус: ${provider?.status || "неизвестен"}`}
        </span>
        {provider?.mode && <span className="provider-flag">mode: {provider.mode}</span>}
        {scope && <span className="provider-flag">license_scope: {scope}</span>}
      </>}
      {state.status === "unavailable" && <span className="provider-flag provider-inactive">
        <span className="pulse" />статус недоступен</span>}
    </div>
  </section>;
}
