// Explicaciones de cada pieza, para alguien de afuera: qué hace en palabras simples y
// con qué está hecha. Las muestra <Explain topic="…" />.

export type Topic = { title: string; body: string; stack: string[] };

export const TOPICS = {
  simulate: {
    title: "Una tienda de verdad, rota a propósito",
    body:
      "La tienda son cuatro microservicios (tienda, usuarios, inventario y pagos) con tráfico de clientes simulado. " +
      "Cada fallo se inyecta de verdad: un deploy con un bug, un cambio de config, una base trabada. " +
      "Además se suman commits inocentes como señuelos, para que el agente no acierte de casualidad.",
    stack: ["Python", "FastAPI", "Postgres", "Redis", "Docker Compose", "Git"],
  },
  health: {
    title: "Lo que vería un equipo de guardia",
    body:
      "Cada servicio publica métricas (pedidos, errores, tiempos) que se guardan cada pocos segundos. " +
      "Estos gráficos son los últimos 15 minutos: cuando rompemos algo, se nota acá antes de que nadie lo explique.",
    stack: ["Prometheus", "Grafana"],
  },
  agent: {
    title: "Un agente que investiga, no un chatbot",
    body:
      "El modelo de lenguaje decide en cada paso qué consultar: métricas, logs, cambios en el código, la documentación o la base. " +
      "Lee los resultados y sigue hasta tener una causa con evidencia. Todas sus herramientas son de solo lectura, " +
      "y tiene un límite de pasos y de tokens.",
    stack: ["LangGraph", "OpenAI", "modelo de respaldo", "tool calling"],
  },
  stream: {
    title: "En vivo y sin perder nada",
    body:
      "La investigación corre en un proceso aparte. Cada paso se publica en una cola y llega acá al instante. " +
      "Si se corta la conexión, se retoma desde el último paso visto.",
    stack: ["Redis Streams", "Server-Sent Events", "Next.js"],
  },
  triage: {
    title: "Primero, qué cambió (sin IA)",
    body:
      "Antes de usar el modelo, se compara cada indicador con la hora anterior y se agrupan los logs nuevos. " +
      "Así el agente arranca sabiendo dónde mirar, y es más barato y rápido.",
    stack: ["Prometheus", "Loki"],
  },
  query_metrics: {
    title: "Métricas",
    body: "Números en el tiempo: pedidos por minuto, errores, latencia, conexiones a la base.",
    stack: ["Prometheus", "PromQL"],
  },
  search_logs: {
    title: "Logs",
    body:
      "Lo que escribe cada servicio. Se agrupan los mensajes repetidos por patrón, " +
      "para que el agente vea 3 problemas distintos y no 3.000 líneas.",
    stack: ["Loki", "Alloy"],
  },
  git: {
    title: "Cambios en el código",
    body:
      "El agente revisa qué se desplegó hace poco y qué cambió en cada commit. " +
      "Cuidado: también hay commits inocentes, y culparlos cuenta como error.",
    stack: ["Git (solo lectura)"],
  },
  rag: {
    title: "RAG: buscar en la documentación",
    body:
      "Los manuales de la empresa, el código y la config se parten en fragmentos y se convierten en vectores. " +
      "Cuando el agente pregunta algo, se buscan los fragmentos con significado más parecido y se los damos para leer. " +
      "El método de búsqueda (vectores, palabras clave, híbrido, con reranker) se eligió midiendo cuál encuentra mejor.",
    stack: ["embeddings", "pgvector", "LangChain"],
  },
  query_database: {
    title: "La base de datos",
    body:
      "Consultas SQL de solo lectura, validadas antes de correr. Sirven para ver, por ejemplo, " +
      "una sesión que tiene trabada una tabla.",
    stack: ["Postgres", "SQL validado"],
  },
  approval: {
    title: "Nada se toca sin un humano",
    body:
      "El agente propone una acción y queda en pausa, guardado en la base. Puede esperar horas: " +
      "cuando decidís, se retoma exactamente donde quedó. Podés aprobar, corregir la acción o rechazarla, " +
      "y la decisión queda registrada.",
    stack: ["LangGraph interrupt", "checkpoints en Postgres", "salida estructurada"],
  },
  verification: {
    title: "Verificar, no suponer",
    body:
      "Después de actuar esperamos un minuto y medimos de nuevo la tienda. " +
      "Solo cuenta como resuelto si los errores y los tiempos volvieron a lo normal.",
    stack: ["Prometheus", "conectores de ejecución"],
  },
  evals: {
    title: "¿Cómo sabemos si el agente es bueno?",
    body:
      "Cada fallo tiene una respuesta correcta conocida. Corriendo todos los fallos varias veces se mide " +
      "cuántas veces el agente elige la acción que arregla el problema, y si culpa a un señuelo.",
    stack: ["evals propios", "escenarios con respuesta conocida"],
  },
  history: {
    title: "Memoria de incidentes",
    body: "Cada investigación queda guardada con el diagnóstico, la decisión y si se resolvió. Podés volver a verla entera.",
    stack: ["Postgres"],
  },
} satisfies Record<string, Topic>;

export type TopicId = keyof typeof TOPICS;

/** Qué mirar en cada momento, y en qué columnas (0 a 3, una por paso). */
export const FOCUS: Record<string, { columns: number[]; hint: string }> = {
  idle: { columns: [0], hint: "Empezá acá: elegí qué romper" },
  breaking: {
    columns: [0],
    hint: "Mirá «Salud de la tienda»: los clientes lo notan",
  },
  investigating: {
    columns: [1],
    hint: "Tocá una consulta para ver qué encontró",
  },
  awaiting_approval: { columns: [2], hint: "Leé la evidencia y decidí abajo" },
  executing: {
    columns: [0, 3],
    hint: "Mirá cómo vuelve la tienda a la normalidad",
  },
  done: { columns: [3], hint: "¿Se resolvió? ¿Acertó el agente?" },
  error: { columns: [1], hint: "El detalle del error está en la consola" },
};
