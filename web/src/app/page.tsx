import { Suspense } from "react";
import { Console } from "@/app/console";

// The console is all live state (clocks, streams, who has the shop): rendered on each
// visit, never prerendered at build time.
export default function Page() {
  return (
    <Suspense fallback={null}>
      <Console />
    </Suspense>
  );
}
