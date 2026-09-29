import { useState } from "react";

/**
 * Botón con confirmación en la propia página. No usa window.confirm: el navegador integrado de
 * la app de escritorio lo bloquea y el botón «no hacía nada».
 */
export function ConfirmButton({ label, question, yes, className = "btn ghost small", yesClassName = "btn small danger", onConfirm }: {
  label: string;
  question: string;
  yes: string;
  className?: string;
  yesClassName?: string;
  onConfirm: () => void | Promise<void>;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) return <button type="button" className={className} onClick={() => setAsking(true)}>{label}</button>;
  return (
    <span className="confirm-inline" role="group" aria-label={question}>
      <span className="tiny">{question}</span>
      <button type="button" className={yesClassName} onClick={async () => { setAsking(false); await onConfirm(); }}>{yes}</button>
      <button type="button" className="btn ghost small" onClick={() => setAsking(false)}>Cancelar</button>
    </span>
  );
}
