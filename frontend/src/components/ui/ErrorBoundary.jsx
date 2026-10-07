import React from "react";

/**
 * Feature-level Error Boundary: an error in one tab degrades that tab to a
 * readable retry state instead of blanking the whole app (TZ 11 — controlled
 * stop behaviour applied to the UI).
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <section className="ops-panel" role="alert" aria-label="Ошибка раздела">
          <div className="ops-panel-head">
            <div>
              <span className="eyebrow">UI ERROR</span>
              <h3>Раздел не удалось отобразить</h3>
              <p>Остальные разделы работают. Данные не пострадали.</p>
            </div>
          </div>
          <p className="warning">
            {String(this.state.error.message || this.state.error)}
          </p>
          <button
            className="primary"
            onClick={() => this.setState({ error: null })}
          >
            Повторить
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
