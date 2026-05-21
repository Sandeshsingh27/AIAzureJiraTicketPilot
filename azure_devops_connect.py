import os
import sys
import requests
import urllib3
from dotenv import load_dotenv
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def str_to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def enable_insecure_requests() -> None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    original_request = requests.Session.request

    def patched_request(self, method, url, **kwargs):
        kwargs["verify"] = False
        return original_request(self, method, url, **kwargs)

    requests.Session.request = patched_request


def main() -> int:
    load_dotenv()

    try:
        org_url = require_env("AZURE_DEVOPS_ORG_URL").rstrip("/")
        personal_access_token = require_env("AZURE_DEVOPS_PAT")

        insecure = str_to_bool(os.getenv("AZURE_DEVOPS_INSECURE", "false"))
        if insecure:
            enable_insecure_requests()
            print("Warning: SSL verification is disabled (AZURE_DEVOPS_INSECURE=true).")

        credentials = BasicAuthentication("", personal_access_token)
        connection = Connection(base_url=org_url, creds=credentials)

        core_client = connection.clients.get_core_client()
        projects = core_client.get_projects()

        print("Connected to Azure DevOps.")
        print("Projects:")
        for project in projects:
            print(f"- {project.name}")

        return 0

    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 2
    except requests.exceptions.SSLError as exc:
        print("SSL error: certificate verification failed during TLS handshake.")
        print("Set AZURE_DEVOPS_INSECURE=true in .env for temporary bypass.")
        print(f"Details: {exc}")
        return 3
    except Exception as exc:
        print(f"Connection/auth error: {exc}")
        return 4


if __name__ == "__main__":
    sys.exit(main())
