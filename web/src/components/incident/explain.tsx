"use client";

import { createContext, useContext } from "react";
import { InfoIcon } from "lucide-react";
import { Popover, PopoverContent, PopoverDescription, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { TOPICS, type TopicId } from "@/lib/explain";

/** Technical mode: shows real names, timings and tokens. */
export const TechMode = createContext(false);

export function useTechMode() {
  return useContext(TechMode);
}

/** "How does it work?" icon: opens a short explanation on click (on mobile too). */
export function Explain({ topic, className = "" }: { topic: TopicId; className?: string }) {
  const { title, body, stack } = TOPICS[topic];
  return (
    <Popover>
      <PopoverTrigger
        aria-label={`How it works: ${title}`}
        className={`inline-flex shrink-0 cursor-help items-center text-muted-foreground hover:text-accent focus-visible:text-accent focus-visible:outline-2 focus-visible:outline-ring ${className}`}
      >
        <InfoIcon className="h-3.5 w-3.5" />
      </PopoverTrigger>
      <PopoverContent className="w-80 rounded-none border-2 border-foreground bg-card text-xs shadow-none ring-0">
        <PopoverTitle className="text-sm text-foreground">{title}</PopoverTitle>
        <PopoverDescription className="leading-relaxed">{body}</PopoverDescription>
        {stack.length > 0 && (
          <ul className="flex flex-wrap gap-1.5 border-t border-border pt-2.5" aria-label="Tools">
            {stack.map((item) => (
              <li key={item} className="border border-accent px-1.5 py-0.5 text-[11px] text-accent">
                {item}
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
