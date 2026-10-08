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
import { actionLabel, shortTarget } from "@/components/incident/terminal";
import { Explain, useTechMode } from "@/components/incident/explain";
import type { TopicId } from "@/lib/explain";
import type { Investigation } from "@/lib/incident";

const CONFIDENCE = { low: "baja", medium: "media", high: "alta" } as const;

export type Decision = {
  approved: boolean;
  note: string;
  action?: { kind: string; target: string };
};

export function Section({ title, topic, children }: { title: string; topic?: TopicId; children: React.ReactNode }) {
  return (
    <div className="border-t border-border pt-3">
      <h3 className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        {title}
        {topic && <Explain topic={topic} />}
      </h3>
      {children}
    </div>
  );
}

function CorrectDialog({
  open,
  onOpenChange,
  kind,
  target,
  onConfirm,
}: {
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
            onClick={() =>
              onConfirm({
                approved: true,
                note,
                action: { kind: newKind, target: newTarget },
              })
            }
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
  readOnly,
  onDecide,
}: {
  investigation: Investigation;
  readOnly: boolean;
  onDecide: (decision: Decision) => void;
}) {
  const [correcting, setCorrecting] = useState(false);
  const tech = useTechMode();
  const { diagnosis, phase } = investigation;

  if (!diagnosis) {
    return (
      <section
        aria-label="Diagnóstico"
        className="min-h-0 border-2 border-dashed border-border p-4 text-xs text-muted-foreground"
      >
        {phase === "investigating" || phase === "breaking"
          ? "El diagnóstico del agente va a aparecer acá cuando termine de investigar."
          : "Todavía no hay diagnóstico."}
      </section>
    );
  }

  const { action } = diagnosis;
  const deciding = phase === "awaiting_approval" && !readOnly;
  return (
    <section aria-label="Diagnóstico" className="flex min-h-0 flex-col border-2 border-foreground text-xs">
      {/* Paso 3. Contenido con scroll propio; la acción y los botones quedan fijos abajo. */}
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-muted-foreground">Causa en</p>
            <p className="font-pixel text-2xl leading-tight break-words text-foreground">{diagnosis.service}</p>
          </div>
          <span className="flex shrink-0 items-center gap-1.5">
            <Badge variant="outline">confianza {CONFIDENCE[diagnosis.confidence]}</Badge>
            <Explain topic="confidence" />
          </span>
        </div>
        <p className="text-sm leading-relaxed break-words text-foreground">{diagnosis.root_cause}</p>

        <Section title="Evidencia" topic="evidence">
          <ul className="flex flex-col gap-1.5 text-muted-foreground">
            {diagnosis.evidence.map((item, i) => (
              <li key={i} className="border-l border-border pl-2 break-words">
                {item}
              </li>
            ))}
          </ul>
        </Section>

        <Section title="Plan">
          <ol className="list-decimal space-y-1 pl-4 break-words text-muted-foreground">
            {diagnosis.plan.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </Section>

        {tech && (
          <Section title="Salida estructurada (JSON)">
            <pre className="overflow-x-auto bg-muted/40 p-2 text-[11px] whitespace-pre-wrap break-words text-muted-foreground">
              {JSON.stringify(diagnosis, null, 2)}
            </pre>
          </Section>
        )}
      </div>

      <footer className="shrink-0 border-t-2 border-foreground p-4">
        <div className={deciding ? "border-2 border-accent p-3" : ""}>
          <p className="flex items-center gap-1.5 text-muted-foreground">
            {deciding ? "El agente propone" : "Acción propuesta"} <Explain topic="approval" />
          </p>
          <p className="mt-1 text-sm break-words text-foreground">
            {actionLabel(action.kind)} <span className="text-accent">{shortTarget(action.target)}</span>
          </p>
          <p className="mt-1 line-clamp-3 break-words text-muted-foreground" title={action.reason}>
            {action.reason}
          </p>
          {deciding && (
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
      </footer>

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
