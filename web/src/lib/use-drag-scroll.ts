import { useEffect, useRef } from "react";

// Lo que se puede tocar: ahí el clic es del control, no para arrastrar.
const INTERACTIVE = "button, a, input, select, textarea, label, [role=combobox], [role=switch], [role=option]";

/** Scroll arrastrando con el mouse (además de la rueda y el touch), para paneles con la barra oculta. */
export function useDragScroll<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let start: { y: number; top: number } | null = null;
    let dragging = false;

    const down = (e: PointerEvent) => {
      if (e.pointerType !== "mouse" || e.button !== 0) return;
      if ((e.target as Element).closest(INTERACTIVE)) return;
      start = { y: e.clientY, top: el.scrollTop };
    };
    const move = (e: PointerEvent) => {
      if (!start) return;
      const dy = e.clientY - start.y;
      if (!dragging && Math.abs(dy) < 4) return; // un clic no es un arrastre
      dragging = true;
      el.style.userSelect = "none";
      el.style.cursor = "grabbing";
      el.scrollTop = start.top - dy;
    };
    const up = () => {
      start = null;
      dragging = false;
      el.style.userSelect = "";
      el.style.cursor = "";
    };

    el.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      el.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, []);
  return ref;
}
