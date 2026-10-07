"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { actionLabel } from "@/components/incident/terminal";
import { grade, type Investigation, type Truth } from "@/lib/incident";

const CONFIDENCE = { low: "baja", medium: "media", high: "alta" } as const;

export type Decision = { approved: boolean; note: string; action?: { kind: string; target: string } };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-border pt-3">
      <h3 className="mb-2 text-xs text-muted-foreground">{title}</h3>
      {children}
    </div>
  );
}

function CorrectDialog({ open, onOpenChange, kind, target, onConfirm }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kind: string;
  target: string;
  onConfirm: (decision: Decision) => void;
}) {
  const [newKind, setNewKind] = useState(kind);
  const [newTarget, setNewTarget] = useState(target);
  const [note, setNote] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="border-2 border-foreground">
        <DialogHeader>
          <DialogTitle>Corregir la acción</DialogTitle>
          <DialogDescription>Se ejecuta tu versión en lugar de la que propuso el agente.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3 text-xs">
          <label className="flex flex-col gap-1 text-muted-foreground">
            Acción
            <select
              value={newKind}
              onChange={(e) => setNewKind(e.target.value)}
              className="border border-input bg-background px-2 py-1.5 text-foreground"
            >
              {["rollback", "revert_config", "restart", "terminate_session", "escalate"].map((k) => (
                <option key={k} value={k}>
                  {actionLabel(k)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-muted-foreground">
            Sobre qué (commit, servicio o sesión)
            <input
              value={newTarget}
              onChange={(e) => setNewTarget(e.target.value)}
              className="border border-input bg-background px-2 py-1.5 text-foreground"
            />
          </label>
          <label className="flex flex-col gap-1 text-muted-foreground">
            Por qué (queda registrado)
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
          </label>
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost" />}>Cancelar</DialogClose>
          <Button
            className="bg-accent text-accent-foreground hover:bg-accent/85"
            onClick={() => onConfirm({ approved: true, note, action: { kind: newKind, target: newTarget } })}
          >
            Ejecutar mi versión
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DiagnosisPanel({
  investigation,
  truth,
  onDecide,
  onEnd,
}: {
  investigation: Investigation;
  truth: Truth | null;
  onDecide: (decision: Decision) => void;
  onEnd: () => void;
}) {
  const [correcting, setCorrecting] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const { diagnosis, phase, verification, execution } = investigation;

  if (!diagnosis) {
    return (
      <section aria-label="Diagnóstico" className="border-2 border-dashed border-border p-4 text-xs text-muted-foreground">
        {phase === "investigating"
          ? "El agente está investigando. Su diagnóstico va a aparecer acá."
          : "Todavía no hay diagnóstico."}
      </section>
    );
  }

  const { action } = diagnosis;
  const result = truth ? grade(truth, diagnosis) : null;
  return (
    <section aria-label="Diagnóstico" className="flex flex-col gap-3 border-2 border-foreground p-4 text-xs">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-muted-foreground">Causa en</p>
          <p className="font-pixel text-2xl leading-tight text-foreground">{diagnosis.service}</p>
        </div>
        <Badge variant="outline" className="shrink-0">
          confianza {CONFIDENCE[diagnosis.confidence]}
        </Badge>
      </div>
      <p className="text-sm leading-relaxed text-foreground">{diagnosis.root_cause}</p>

      <Section title="Evidencia">
        <ul className="flex flex-col gap-1.5 text-muted-foreground">
          {diagnosis.evidence.map((item, i) => (
            <li key={i} className="border-l border-border pl-2">
              {item}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Plan">
        <ol className="list-decimal space-y-1 pl-4 text-muted-foreground">
          {diagnosis.plan.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      </Section>

      <div className="border-2 border-accent p-3">
        <p className="text-muted-foreground">Acción propuesta</p>
        <p className="mt-1 text-sm text-foreground">
          {actionLabel(action.kind)} <span className="text-accent">{action.target.slice(0, 40)}</span>
        </p>
        <p className="mt-1 text-muted-foreground">{action.reason}</p>
        {phase === "awaiting_approval" && (
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              className="bg-accent text-accent-foreground hover:bg-accent/85"
              onClick={() => onDecide({ approved: true, note: "" })}
            >
              Aprobar y ejecutar
            </Button>
            <Button variant="outline" onClick={() => setCorrecting(true)}>
              Corregir
            </Button>
            <Button variant="ghost" onClick={() => onDecide({ approved: false, note: "rechazado desde la UI" })}>
              Rechazar
            </Button>
          </div>
        )}
      </div>

      {(execution || verification || phase === "executing") && (
        <Section title="Resultado">
          {phase === "executing" && !verification && (
            <p className="text-muted-foreground">Ejecutando y esperando a que se vean los cambios en las métricas (~1 min)…</p>
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
                      <td className="py-1 text-right text-foreground">{check.value}</td>
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
        <Section title="¿Acertó el agente?">
          {diagnosis.service === "dry-run" && (
            <p className="mb-2 text-muted-foreground">
              Modo prueba: el diagnóstico es un ejemplo fijo, así que no puede acertar. Apagá el modo
              prueba para ver al agente investigar de verdad.
            </p>
          )}
          {!revealed ? (
            <Button variant="outline" size="sm" onClick={() => setRevealed(true)}>
              Ver la respuesta correcta
            </Button>
          ) : (
            <div className="flex flex-col gap-2">
              <p className="text-muted-foreground">{truth.root_cause}</p>
              <ul className="flex flex-col gap-1">
                {[
                  ["Acción que arregla el problema", result.action],
                  ["Servicio", result.service],
                  [truth.culprit_sha ? "Commit culpable" : "No culpar a ningún commit", result.commit],
                ].map(([label, ok]) => (
                  <li key={label as string} className="flex justify-between">
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

      {(phase === "done" || phase === "error") && (
        <Button variant="ghost" size="sm" className="self-start" onClick={onEnd}>
          Terminar y simular otro
        </Button>
      )}

      <CorrectDialog
        open={correcting}
        onOpenChange={setCorrecting}
        kind={action.kind}
        target={action.target}
        onConfirm={(decision) => {
          setCorrecting(false);
          onDecide(decision);
        }}
      />
    </section>
  );
}
