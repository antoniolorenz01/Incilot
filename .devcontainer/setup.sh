#!/usr/bin/env bash
# Codespaces setup: the tools, the synthetic data and a .env.
set -euo pipefail

pip install --quiet uv
[ -d ../incilot-data ] || git clone --depth 1 https://github.com/antoniolorenz01/incilot-data ../incilot-data
make install
(cd web && npm ci)

# The OpenAI key comes from the visitor's Codespaces secret, if they set one.
if [ ! -f .env ]; then
  {
    echo "OPENAI_MODEL=gpt-6-luna"
    if [ -n "${OPENAI_API_KEY:-}" ]; then echo "OPENAI_API_KEY=${OPENAI_API_KEY}"; fi
  } > .env
fi

echo
echo "Ready. Start the shop and the agent with 'make up', then the console with 'make web'."
echo "Without an OpenAI key, turn on 'Dry run' when simulating."
