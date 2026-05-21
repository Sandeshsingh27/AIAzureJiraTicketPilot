import os
from dotenv import load_dotenv
from jira import JIRA

load_dotenv()

jira_url = os.getenv('JIRA_URL', '').rstrip('/')
jira_pat = os.getenv('JIRA_PAT')
jira_email = os.getenv('JIRA_EMAIL')
jira_api_token = os.getenv('JIRA_API_TOKEN')

try:
    if jira_pat:
        # Jira Server / Data Center - Personal Access Token (Bearer)
        jira = JIRA(server=jira_url, token_auth=jira_pat)
    elif jira_email and jira_api_token:
        # Jira Cloud - email + API token (Basic)
        jira = JIRA(server=jira_url, basic_auth=(jira_email, jira_api_token))
    else:
        raise RuntimeError("Set JIRA_PAT (Server/DC) or JIRA_EMAIL + JIRA_API_TOKEN (Cloud) in .env")

    myself = jira.myself()
    print(f"Authenticated as: {myself.get('name') or myself.get('displayName')} <{myself.get('emailAddress','')}>")

    projects = jira.projects()
    print(f"Found {len(projects)} projects:")
    for project in projects:
        print(project.key, project.name)
except Exception as e:
    print(f"Connection/auth error: {e}")

