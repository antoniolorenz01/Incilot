"use client";

import { Popover, PopoverContent, PopoverDescription, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { REPO_URL } from "@/lib/mode";

/** The recorded demo, said once in the header: what's real and how to run it live. */
export function DemoNotice({ model }: { model: string | null }) {
  const repo = REPO_URL.split("github.com/")[1];
  return (
    <Popover>
      <PopoverTrigger className="border-2 border-accent px-2 py-1 text-xs text-accent hover:bg-accent hover:text-accent-foreground focus-visible:outline-2 focus-visible:outline-ring">
        Demo mode: recorded runs
      </PopoverTrigger>
      <PopoverContent className="w-80 rounded-none border-2 border-foreground bg-card text-xs shadow-none ring-0">
        <PopoverTitle className="text-sm text-foreground">Everything here really happened</PopoverTitle>
        <PopoverDescription className="leading-relaxed">
          The real agent investigated the real shop
          {model ? `, with ${model.replace(" (via ", " via ").replace(/\)$/, "")}` : ""}, and each run was recorded so
          it’s instant and free. Simulating plays one of those runs; you take the decision.
        </PopoverDescription>
        <p className="border-t border-border pt-2.5 leading-relaxed text-muted-foreground">
          To run it live:{" "}
          <a className="text-foreground underline hover:text-accent" href={`https://codespaces.new/${repo}`}>
            open it in Codespaces
          </a>{" "}
          or{" "}
          <a className="text-foreground underline hover:text-accent" href={`${REPO_URL}#run-it-locally`}>
            run it locally
          </a>
          .
        </p>
      </PopoverContent>
    </Popover>
  );
}
