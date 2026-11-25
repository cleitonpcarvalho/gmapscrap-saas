"""VPS orchestration; touches only GmapScrap and its own backup directories.

Uses existing backend credentials in memory. No env files, tokens, database rows,
raw inspect output, or subprocess stderr are ever printed. No rollback/prune/
stack redeploy, volume changes, or unrelated service updates are performed.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

REGISTRY = "ghcr.io/cleitonpcarvalho/gmapscrap-saas-"
SERVICES = {"backend": "gmapscrap_backend", "frontend": "gmapscrap_frontend"}
ROOT = Path(__file__).resolve().parents[1]
STATE = Path("/var/lib/gmapscrap-deploy")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(command, *, env=None, data=None, timeout=120):
    result = subprocess.run(command, env=env, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    require(result.returncode == 0, f"{Path(command[0]).name} failed; release stopped without rollback")
    return result.stdout


def task(component):
    names = run(["docker", "ps", "-q", "--filter", f"label=com.docker.swarm.service.name={SERVICES[component]}"]).decode().split()
    require(len(names) == 1, f"Expected one local {component} replica")
    return names[0]


def existing_credentials():
    code = """import json
from sqlalchemy.engine import make_url
from backend.database import _database_url
import os
u=make_url(_database_url())
print(json.dumps(dict(PGHOST=u.host,PGPORT=str(u.port or 5432),PGDATABASE=u.database,PGUSER=u.username,PGPASSWORD=u.password,PGSSLMODE=u.query.get('sslmode',''),GMAPSCRAP_LEGACY_BACKEND='0' if os.getenv('GMAPSCRAP_SCHEMA_MANAGED')=='1' else '1')))
"""
    values = json.loads(run(["docker", "exec", "-i", task("backend"), "python", "-"], data=code.encode()))
    require(all(isinstance(value, str) and value for value in values.values()), "Existing DB credentials are incomplete")
    require(values["PGHOST"].endswith((".supabase.com", ".supabase.co")), "Existing backend does not target Supabase")
    return values


def check_running_version(component, release):
    image = f"{REGISTRY}{component}:{release}"
    expected = json.loads(run(["docker", "image", "inspect", image]))[0]
    container = json.loads(run(["docker", "inspect", task(component)]))[0]
    require(container["Image"] == expected["Id"], f"{component} running image differs from release")
    require(expected["Config"]["Labels"]["org.opencontainers.image.revision"] == release, f"{component} image revision label differs")
    service = json.loads(run(["docker", "service", "inspect", SERVICES[component]]))[0]
    require(service["Spec"]["Mode"]["Replicated"]["Replicas"] == 1, "Unexpected production replica topology")
    require(service.get("UpdateStatus", {}).get("State") == "completed", f"{component} rollout did not complete")
    require(service["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"].startswith(image + "@sha256:"), "Service is not pinned to the release image digest")
    return {"image_id": expected["Id"], "revision": release}


def release_production(release, mode, verified_ids):
    require(bool(re.fullmatch(r"[0-9a-f]{40}", release)), "Expected full commit SHA")
    require(bool(re.fullmatch(r"(?:[0-9]+(?:,[0-9]+)*)?", verified_ids)), "Invalid verified server IDs")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(STATE.stat().st_mode & 0o077 == 0, "Backup root must be private")
    with (STATE / "release.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        task("frontend")
        credentials = existing_credentials()
        images = {}
        for component in ("backend", "frontend", "migrations"):
            reference = f"{REGISTRY}{component}:{release}"
            run(["docker", "pull", reference], timeout=600)
            image = json.loads(run(["docker", "image", "inspect", reference]))[0]
            require(image["Config"]["Labels"]["org.opencontainers.image.revision"] == release, "Release image revision differs before migration")
            digests = [value.split("@", 1)[1] for value in image["RepoDigests"] if value.startswith(f"{REGISTRY}{component}@sha256:")]
            require(len(digests) == 1, "Release image has no unambiguous registry digest")
            images[component] = reference + "@" + digests[0]
        folder = STATE / f"{release}-{uuid.uuid4().hex}"
        folder.mkdir(mode=0o700)
        uid = int(run(["docker", "run", "--rm", "--entrypoint", "id", images["migrations"], "-u"]).decode().strip())
        os.chown(folder, uid, uid)
        command = ["docker", "run", "--rm", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=2g",
                   "--mount", f"type=bind,source={folder},target=/backup"]
        for name in credentials:
            command += ["--env", name]
        command += [images["migrations"], "--release", release,
                    "--verified-server-search-ids", verified_ids]
        gate_output = run(command, env={**os.environ, **credentials}, timeout=1800)
        evidence = json.loads((folder / "evidence.json").read_text())
        require(evidence["release"] == release and evidence["public_schema_restore"] and
                evidence["existing_rows_preserved"] and evidence["restored_backend_api"], "Missing migration evidence")
        print(gate_output.decode().strip(), flush=True)
        print(f"Private validated backup: {folder}/production.dump", flush=True)
        if mode == "prepare":
            print("Preparation complete; neither production service was updated", flush=True)
            return
        versions = {}
        for component in ("backend", "frontend"):
            command = ["docker", "service", "update", "--with-registry-auth", "--detach=false",
                       "--update-failure-action", "pause", "--update-order", "stop-first",
                       "--image", images[component]]
            if component == "backend":
                command += ["--env-add", "GMAPSCRAP_SCHEMA_MANAGED=1", "--env-add", f"GMAPSCRAP_RELEASE_SHA={release}"]
            command.append(SERVICES[component])
            run(command, timeout=600)
            versions[component] = check_running_version(component, release)
            if component == "backend":
                code = f"""import requests,time
for _ in range(30):
    try:
        r=requests.get('https://api.automasoluct.com.br/api/health',timeout=5)
        if r.status_code==200 and r.json()=={{'status':'ok','version':'{release}'}}: break
    except requests.RequestException: pass
    time.sleep(2)
else: raise SystemExit(1)
"""
                run(["docker", "exec", "-i", task("backend"), "python", "-"], data=code.encode(), timeout=240)
        smoke = run(["docker", "exec", "-i", task("backend"), "python", "-"], data=(ROOT / "scripts/production_smoke.py").read_bytes(), timeout=300)
        evidence["running_images"] = versions
        evidence["production_smoke"] = json.loads(smoke)
        (folder / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(smoke.decode().strip(), flush=True)
        print(json.dumps({"deployment": "verified", "release": release, "running_images": versions}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--mode", choices=("prepare", "deploy"), required=True)
    parser.add_argument("--verified-server-search-ids", default="")
    arguments = parser.parse_args()
    try:
        release_production(arguments.release, arguments.mode, arguments.verified_server_search_ids)
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else f"Release failed ({type(error).__name__}); stopped without rollback", file=sys.stderr)
        sys.exit(1)
