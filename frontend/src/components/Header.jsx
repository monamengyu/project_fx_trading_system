import { API_URL } from "../services/api.js";

export function Header() {
  return (
    <header className="header">
      <div className="header__brand">
        <h1 className="header__title">FX Trading System</h1>
        <span className="header__subtitle">Market data · Blotter · New trade</span>
      </div>
      <span className="header__badge">Backend: {API_URL}</span>
    </header>
  );
}
