import { useState } from "react";
import { api, type AuthStatus } from "./api";

export function Login({ status, onDone }: { status: AuthStatus; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <form
        className="login-card"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api.login(password);
            setPassword("");
            onDone();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="brand" style={{ padding: 0, marginBottom: 18 }}>
          <span className="brand-mark" aria-hidden="true" />
          <div><span className="brand-name">TRAMA</span><span className="brand-sub">Tu biblioteca de producción</span></div>
        </div>
        <h1>Acceso privado</h1>
        <p className="muted">El catálogo, las previews y los originales solo se sirven con sesión iniciada.</p>
        {status.misconfigured && <div className="notice warn">El servidor está en modo contraseña pero no tiene ninguna configurada. Ejecuta <code>python -m trama set-password</code> y añade el resultado a .env.</div>}
        {!status.cookie_secure && window.location.protocol === "https:" && <div className="notice warn">Estás en HTTPS pero la cookie no lleva el atributo Secure: define <code>TRAMA_COOKIE_SECURE=1</code>.</div>}
        <label className="login-field">
          <span>Contraseña</span>
          <input className="input" type="password" autoComplete="current-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy || status.misconfigured} />
        </label>
        {error && <div className="notice warn" role="alert">{error}</div>}
        <button type="submit" className="btn primary block" disabled={busy || !password || status.misconfigured}>{busy ? "Entrando…" : "Entrar"}</button>
      </form>
    </div>
  );
}
