# Windows server auto-deploy

This document describes the GitHub Actions → SSH deployment set up for the
hospital chatbot production server.

## What was done

| Piece | Detail |
|-------|--------|
| Workflow | `.github/workflows/deploy.yml` |
| Trigger | Push (or merge) to `main`, plus manual **Run workflow** |
| Target host | Windows server (`196.219.86.38` by default) |
| App path | `C:\apps\hospital-chatbot` |
| Auth | SSH public-key login as `Administrator` |
| GitHub secret | `WINDOWS_SSH_KEY` = OpenSSH **private** key |
| Server public key file | `C:\ProgramData\ssh\administrators_authorized_keys` |
| Backend service | `HospitalChatbotBackend` (restarted on every deploy) |
| Streamlit | **Not** a Windows service; code updates on disk, restart manually |

### Deploy steps (every successful run)

1. SSH into the server as `Administrator`
2. `git fetch` / `checkout main` / `pull origin main`
3. `pip install -r requirements.txt` (supports `venv` or `.venv`)
4. `python -m alembic upgrade head`
5. `Restart-Service HospitalChatbotBackend`

## Architecture

```text
Developer
   │  git push / merge PR → main
   ▼
GitHub Actions (ubuntu-latest)
   │  appleboy/ssh-action@v1.2.5
   │  uses secret WINDOWS_SSH_KEY
   ▼
Windows OpenSSH (port 22)
   │  Administrator + administrators_authorized_keys
   ▼
C:\apps\hospital-chatbot
   ├── git pull origin main
   ├── pip + alembic
   └── Restart-Service HospitalChatbotBackend
```

## GitHub secrets

Repo → **Settings** → **Secrets and variables** → **Actions**

| Secret | Required | Default if unset | Purpose |
|--------|----------|------------------|---------|
| `WINDOWS_SSH_KEY` | **Yes** | — | Full private key (`BEGIN` … `END`) |
| `WINDOWS_SSH_HOST` | No | `196.219.86.38` | Server IP/hostname |
| `WINDOWS_SSH_USER` | No | `Administrator` | SSH username |
| `WINDOWS_SSH_PORT` | No | `22` | SSH port |

**Rules for the private key secret**

- Paste the **private** key file contents, not the `.pub` file.
- Include the `-----BEGIN …-----` and `-----END …-----` lines.
- No surrounding quotes.
- Prefer OpenSSH format (`BEGIN OPENSSH PRIVATE KEY`).

## Server SSH setup (Windows)

OpenSSH Server (`sshd`) must be **Running**.

### Important: Administrator keys path

For users in the **Administrators** group, Windows OpenSSH **does not** use:

`C:\Users\Administrator\.ssh\authorized_keys`

It uses:

`C:\ProgramData\ssh\administrators_authorized_keys`

Wrong path → `ssh: unable to authenticate, attempted methods [none publickey]`.

### Create / update the admin authorized keys file

Run in an **elevated** PowerShell on the server (one public-key line):

```powershell
$pub = 'ssh-ed25519 AAAA... comment'

New-Item -ItemType Directory -Force -Path "$env:ProgramData\ssh" | Out-Null
Set-Content -Path "$env:ProgramData\ssh\administrators_authorized_keys" -Value $pub -Encoding ascii

icacls "$env:ProgramData\ssh\administrators_authorized_keys" /inheritance:r
icacls "$env:ProgramData\ssh\administrators_authorized_keys" /grant "SYSTEM:(F)"
icacls "$env:ProgramData\ssh\administrators_authorized_keys" /grant "BUILTIN\Administrators:(F)"

Restart-Service sshd
icacls "$env:ProgramData\ssh\administrators_authorized_keys"
```

Expected ACL: only `NT AUTHORITY\SYSTEM:(F)` and `BUILTIN\Administrators:(F)`.

### Test from your laptop (not from the server)

The private key lives on the **client** (laptop / GitHub Actions). Testing on the
server itself fails unless you copy the private key there (not recommended).

```powershell
# Example key name used for this project
ssh -i $env:USERPROFILE\.ssh\server_ed25519 Administrator@196.219.86.38 "echo SSH_OK"
```

If you see `SSH_OK`, GitHub can use the same private key via `WINDOWS_SSH_KEY`.

## What auto-updates vs what does not

| Change type | Auto on deploy? | Notes |
|-------------|-----------------|--------|
| Backend (`app/`, webhook, voice, etc.) | **Yes** | Service restart loads new code |
| DB migrations (`alembic/`) | **Yes** | `alembic upgrade head` |
| Python deps (`requirements.txt`) | **Yes** | `pip install -r requirements.txt` |
| Streamlit dashboard (`dashboard/`) | **Files only** | Restart Streamlit manually |
| `.env` / secrets on server | **No** | Edit on server; never commit secrets |
| Branches other than `main` | **No** | Only `main` triggers deploy |

### Restart Streamlit manually

```powershell
cd C:\apps\hospital-chatbot
# Stop the existing Streamlit process/window, then:
.\venv\Scripts\streamlit.exe run dashboard/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

Dashboard URL: `http://196.219.86.38:8501/`

## How to deploy day to day

1. Develop on a feature branch (e.g. `work`).
2. Open a PR / merge into `main`, or push directly to `main` if that is your process.
3. Watch **Actions** → **Deploy to Windows server**.
4. Confirm WhatsApp / API behavior; check server logs if needed:

```powershell
Get-Service HospitalChatbotBackend
Get-Content "C:\apps\hospital-chatbot\logs\stdout.log" -Tail 40 -Encoding UTF8
```

Manual trigger (no code change): Actions → **Deploy to Windows server** → **Run workflow**.

## Manual fallback (if Actions is down)

```powershell
cd C:\apps\hospital-chatbot
git checkout main
git pull origin main
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\python.exe -m alembic upgrade head
Restart-Service HospitalChatbotBackend
Get-Service HospitalChatbotBackend
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `unable to authenticate` / `no supported methods remain` | Wrong key, wrong secret, or wrong authorized_keys path | Fix `administrators_authorized_keys` + `WINDOWS_SSH_KEY` |
| `Unexpected input(s) 'script_stop'` | Old ssh-action option removed in v1.2+ | Do not use `script_stop`; use `$ErrorActionPreference = 'Stop'` in PowerShell |
| Deploy green but WhatsApp unchanged | Looking at old process / wrong branch | Confirm commit on `main`, service restarted, logs show new revision |
| Dashboard UI unchanged | Streamlit not restarted | Restart Streamlit (see above) |
| `venv not found` | Virtualenv missing or renamed | Create `C:\apps\hospital-chatbot\venv` (or `.venv`) |
| Alembic error | Migration conflict / DB state | Fix migrations locally, then redeploy; do not skip `upgrade head` |

Workflow debug is currently enabled (`debug: true` in `deploy.yml`) so Actions logs show the SSH client config. Turn it off later if the logs are too noisy.

## Key rotation (recommended)

If a private key was ever pasted into chat, email, or a ticket, rotate it:

1. On the laptop: `ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\server_ed25519_new -N '""'`
2. Put the new **public** line into `administrators_authorized_keys` on the server (ACLs as above).
3. Put the new **private** key into GitHub `WINDOWS_SSH_KEY`.
4. Re-run deploy; remove the old public key from the server when confirmed.
5. Delete or archive the old private key locally.

## Related files

- `.github/workflows/deploy.yml` — workflow definition
- `README.md` — short deploy summary
- `docs/DOCUMENTATION.md` — full project guide (includes a Deployment section)
