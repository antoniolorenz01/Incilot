"""CLI del injector.

    python -m incilot_sim.injector.cli list
    python -m incilot_sim.injector.cli inject deploy-latency-regression [--variant ID]
    python -m incilot_sim.injector.cli status
    python -m incilot_sim.injector.cli recover

Configuración por variables de entorno: INJECTOR_DATA (incilot-data),
COMPANY_REPO (repo Git de la empresa), GROUNDTRUTH_DATABASE_URL y FAULTS_REDIS_URL.
"""

import argparse
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from redis.asyncio import Redis

from incilot_sim.injector import scenarios
from incilot_sim.injector.core import InjectionError, Injector, connect_groundtruth


def data_dir() -> Path:
    return Path(os.getenv("INJECTOR_DATA", "../incilot-data"))


@asynccontextmanager
async def connect():
    db = await connect_groundtruth(os.environ["GROUNDTRUTH_DATABASE_URL"])
    redis = Redis.from_url(os.environ["FAULTS_REDIS_URL"], decode_responses=True)
    repo = Path(os.getenv("COMPANY_REPO", "build/company-repo"))
    injector = Injector(db, redis, data_dir(), repo, os.environ["GROUNDTRUTH_DATABASE_URL"])
    try:
        yield injector
    finally:
        await injector.aclose()


def show(injection: dict) -> None:
    print(f"{injection['id']}  {injection['scenario']}/{injection['variant']}")
    print(f"  servicio     {injection['service']} ({injection['category']})")
    print(f"  causa raíz   {injection['root_cause']}")
    print(f"  acción       {injection['action']}")
    print(f"  commit       {injection['culprit_sha'] or '—'}")
    print(f"  señuelos     {', '.join(s[:7] for s in injection['decoy_shas']) or '—'}")
    print(f"  inyectado    {injection['injected_at']:%Y-%m-%d %H:%M:%S}")
    if injection["recovered_at"]:
        print(f"  recuperado   {injection['recovered_at']:%Y-%m-%d %H:%M:%S}")


def cmd_list(_args) -> None:
    for scenario_id, variants in scenarios.load(data_dir()).items():
        print(f"{scenario_id}  ({variants[0].category}) {variants[0].title}")
        for v in variants:
            print(f"  - {v.id}  [{v.service}]{'  (exam)' if v.split == 'exam' else ''}")


async def cmd_inject(args) -> None:
    variant = scenarios.pick(scenarios.load(data_dir()), args.scenario, args.variant)
    async with connect() as injector:
        show(await injector.inject(variant))


async def cmd_status(_args) -> None:
    async with connect() as injector:
        active = await injector.active()
    if active:
        show(active)
    else:
        print("no hay ninguna inyección activa")


async def cmd_recover(_args) -> None:
    async with connect() as injector:
        show(await injector.recover())


def main() -> None:
    parser = argparse.ArgumentParser(description="Injector de fallos de la mini-empresa")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="escenarios disponibles").set_defaults(run=cmd_list)
    inject = commands.add_parser("inject", help="provoca un fallo")
    inject.add_argument("scenario")
    inject.add_argument("--variant", help="por defecto, una al azar")
    inject.set_defaults(run=cmd_inject)
    commands.add_parser("status", help="inyección activa").set_defaults(run=cmd_status)
    commands.add_parser("recover", help="recupera la inyección activa").set_defaults(
        run=cmd_recover
    )

    args = parser.parse_args()
    try:
        result = args.run(args)
        if asyncio.iscoroutine(result):
            asyncio.run(result)
    except (InjectionError, KeyError) as exc:
        parser.exit(1, f"error: {exc.args[0]}\n")


if __name__ == "__main__":
    main()
