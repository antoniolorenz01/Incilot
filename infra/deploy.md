# Deploying the public demo

One server runs everything with Docker Compose. Only Caddy faces the internet (HTTPS on
443, certificates from Let's Encrypt); the shop, the agent, the injector, observability
and the databases stay on the internal network.

Spending is capped three ways:

1. Real investigations per IP and per day, in the web (`DEMO_RUNS_PER_IP`, `DEMO_RUNS_PER_DAY`).
2. One simulation at a time: there is a single shop, so everyone else watches.
3. A monthly budget on the OpenAI project whose key the server uses. This is the real
   ceiling if everything else fails: set it before going live.

Recordings (`make record`, run locally and committed) and dry runs cost nothing.

## 1. Server and domain

- A Linux server with 8 GB of RAM (e.g. a Hetzner CX32), with Docker and the Compose plugin.
- A DNS `A` record pointing the demo's domain at the server's IP.
- Ports 80 and 443 open; nothing else needs to be.

## 2. Code and data

The compose file expects `incilot-data` next to `Incilot`:

```sh
git clone <Incilot repo> Incilot
git clone <incilot-data repo> incilot-data   # or copy it: rsync -a ../incilot-data server:
```

## 3. Secrets (`Incilot/.env`, never committed)

```sh
DOMAIN=incidentpilot.example.com
OPENAI_API_KEY=sk-...              # a key from a project with a monthly budget
OPENAI_MODEL=gpt-6-luna
OPENAI_FALLBACK_MODEL=...          # optional
OPS_TOKEN=<random, e.g. openssl rand -hex 24>
DEMO_RUNS_PER_IP=2                 # optional, these are the defaults
DEMO_RUNS_PER_DAY=20
```

Do not set `LLM_PROVIDER=claude-code` here: that is for local runs on a subscription.

## 4. Start it

```sh
make prod-up       # builds and starts everything; Caddy gets the certificate
make prod-logs     # web, agent and Caddy logs
```

## 5. Backups

The agent's database (investigations, decisions) is dumped daily, keeping 14 days:

```sh
crontab -e
0 4 * * * cd ~/Incilot && make backup
```

## Updating

```sh
git pull && make prod-up
```
