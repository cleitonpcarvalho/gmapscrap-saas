"""Run inside the deployed backend. Logs status codes/version only, never rows."""
import json
import os

import requests

from backend.config import get_settings


def main():
    settings = get_settings()
    api = "https://api.automasoluct.com.br"
    with requests.Session() as client:
        health = client.get(api + "/api/health", timeout=30)
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "version": os.environ["GMAPSCRAP_RELEASE_SHA"]}
        result = client.post(api + "/api/auth/login", json={"username": settings.app_username, "password": settings.app_password}, timeout=30)
        assert result.status_code == 200
        checks = {}
        for endpoint in ("/api/auth/me", "/api/leads?limit=1", "/api/website-qualification/results?limit=1", "/api/crm/funnels", "/api/crm/leads", "/api/crm/manual/leads?limit=1", "/api/crm/manual/follow-ups", "/api/niches", "/api/searches"):
            result = client.get(api + endpoint, timeout=30)
            assert result.status_code == 200
            checks[endpoint] = result.status_code
        for funnel in client.get(api + "/api/crm/funnels", timeout=30).json():
            endpoint = f"/api/crm/manual/cards?funnel_id={funnel['id']}"
            assert client.get(api + endpoint, timeout=30).status_code == 200
            checks[endpoint] = 200
        assert requests.get(api + "/api/crm/manual/leads", timeout=30).status_code == 401
        for path in ("/", "/crm"):
            assert client.get("https://gmapscrap.automasoluct.com.br" + path, timeout=30).status_code == 200
        print(json.dumps({"release": os.environ["GMAPSCRAP_RELEASE_SHA"], "backend": "healthy", "frontend": "healthy", "authenticated_gets": checks, "anonymous_crm": 401}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Production smoke failed ({type(error).__name__}); stop for review")
        raise SystemExit(1)
