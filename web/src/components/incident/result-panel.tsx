"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/incident/diagnosis-panel";
import { grade, type Investigation, type Truth } from "@/lib/incident";

/** Paso 4: si la tienda se recuperó y si el agente acertó. */
export function ResultPanel({
  investigation,
  truth,
  readOnly,
  onEnd,
}: {
  investigation: Investigation;
  truth: Truth | null;
  readOnly: boolean;
  onEnd: () => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const { diagnosis, phase, verification, execution } = investigation;
  const result = truth && diagnosis ? grade(truth, diagnosis) : null;
  const finished = phase === "done" || phase === "error" || readOnly;

  if (!diagnosis && !finished) {
    return (
      <section
        aria-label="Resultado"
        className="shrink-0 border-2 border-dashed border-border p-4 text-xs text-muted-foreground"
      >
        Cuando decidas, acá vas a ver si la tienda se recuperó y si el agente acertó.
      </section>
    );
  }

  return (
    <section
      aria-label="Resultado"
      className="flex max-h-[65%] shrink-0 flex-col gap-3 overflow-y-auto border-2 border-foreground p-4 text-xs"
    >
      <h2 className="text-sm text-foreground">Resultado</h2>
      {phase === "awaiting_approval" && !readOnly && <p className="text-muted-foreground">Esperando tu decisión.</p>}
      {(execution || verification || phase === "executing") && (
        <Section title="La tienda" topic="verification">
          {phase === "executing" && !verification && (
            <p className="text-muted-foreground">Aplicando y midiendo la tienda durante un minuto…</p>
          )}
          {verification && !verification.skipped && (
            <>
              <p className={`font-pixel text-xl ${verification.recovered ? "text-success" : "text-destructive"}`}>
                {verification.recovered ? "Resuelto" : "Sigue el problema"}
              </p>
              <table className="mt-2 w-full">
                <tbody>
                  {verification.checks.map((check) => (
                    <tr key={check.name} className="border-b border-border last:border-none">
                      <td className="py-1 text-muted-foreground">{check.name}</td>
                      <td className="py-1 text-right tabular-nums text-foreground">{check.value}</td>
                      <td className={`py-1 pl-2 text-right ${check.ok ? "text-success" : "text-destructive"}`}>
                        {check.ok ? "ok" : `> ${check.max}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Section>
      )}

      {result && truth && (
        <Section title="¿Acertó el agente?" topic="evals">
          {diagnosis?.service === "dry-run" && (
            <p className="mb-2 text-muted-foreground">
              Modo prueba: el diagnóstico es un ejemplo fijo, así que no puede acertar. Apagá el modo prueba para ver al
              agente investigar de verdad.
            </p>
          )}
          {!revealed ? (
            <Button variant="outline" size="sm" onClick={() => setRevealed(true)}>
              Ver la respuesta correcta
            </Button>
          ) : (
            <div className="flex flex-col gap-2">
              <p className="break-words text-muted-foreground">{truth.root_cause}</p>
              <ul className="flex flex-col gap-1">
                {[
                  ["Acción que arregla el problema", result.action],
                  ["Servicio", result.service],
                  [truth.culprit_sha ? "Commit culpable" : "No culpar a ningún commit", result.commit],
                ].map(([label, ok]) => (
                  <li key={label as string} className="flex justify-between gap-2">
                    <span className="text-muted-foreground">{label}</span>
                    <span className={ok ? "text-success" : "text-destructive"}>{ok ? "acertó" : "falló"}</span>
                  </li>
                ))}
              </ul>
              {result.decoy && <p className="text-destructive">Culpó a un commit inocente (un señuelo).</p>}
            </div>
          )}
        </Section>
      )}
      {finished && (
        <Button variant="ghost" size="sm" className="self-start" onClick={onEnd}>
          {readOnly ? "Volver" : "Terminar y simular otro"}
        </Button>
      )}
    </section>
  );
}
