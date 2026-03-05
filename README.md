# System Monitor

A self-hosted dashboard to track system health and security across multiple machines (Mac, PC, Raspberry Pi).

## What it monitors

**System Health**
- CPU usage, core count, frequency
- RAM and swap usage
- Disk usage per partition
- Network I/O and interface addresses
- System uptime and OS info

**Security**
- Open / listening ports — flags unusual ports (Telnet, RDP, VNC, SMB, etc.)
- Failed SSH / login attempts (last 24h) — works on macOS, Linux, and Windows
- Suspicious process names (netcat, nmap, miners, RATs, etc.)
- Available package updates (Homebrew on Mac, apt/dnf on Linux, winget on Windows)
- Auto-generated alerts with severity levels (info / warning / critical)

---

## Project layout

```
computer_monitor/
├── agent/               # Runs on each monitored machine
│   ├── agent.py
│   ├── collectors/
│   │   ├── system.py    # CPU, RAM, disk, network
│   │   └── security.py  # Ports, logins, processes, packages
│   ├── config.example.yaml
│   └── requirements.txt
├── server/              # Central FastAPI server + SQLite
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── alerting.py
│   ├── Dockerfile
│   └── requirements.txt
├── dashboard/           # Static web dashboard
│   ├── index.html
│   ├── css/style.css
│   └── js/dashboard.js
├── docker-compose.yml
└── .env.example
```

---

## Quick start (local)

### 1. Start the server

```bash
cd server
pip install -r requirements.txt
API_KEY=my-secret-key uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` to see the dashboard.

### 2. Configure and run an agent

```bash
cd agent
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml: set server_url, api_key, machine_name, machine_type
python agent.py --config config.yaml
```

Use `--dry-run` to print a JSON snapshot without sending it:

```bash
python agent.py --dry-run --once
```

### 3. Repeat for each machine

Copy the `agent/` folder to your PC and Raspberry Pi, install deps, and configure each with the same `server_url` and `api_key` but different `machine_name`.

---

## Deploy server to the web (Render — free tier)

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → New → Web Service.
3. Select your repo.
4. Set:
   - **Root directory**: `server`
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Environment variable**: `API_KEY` = your secret key
5. Deploy. Copy the URL (e.g. `https://monitor-abc.onrender.com`).
6. Update `server_url` in each agent's `config.yaml` to that URL.
7. In `dashboard/js/dashboard.js` set `SERVER_URL` to the same URL (only needed if you host the dashboard separately).

The server also serves the dashboard at `/` automatically.

---

## Run agents automatically on startup

### macOS (launchd)

Create `~/Library/LaunchAgents/com.monitor.agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>          <string>com.monitor.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/agent/agent.py</string>
    <string>--config</string>
    <string>/path/to/agent/config.yaml</string>
  </array>
  <key>RunAtLoad</key>      <true/>
  <key>KeepAlive</key>      <true/>
  <key>StandardErrorPath</key>  <string>/tmp/monitor-agent.log</string>
  <key>StandardOutPath</key>    <string>/tmp/monitor-agent.log</string>
</dict>
</plist>
```

Then: `launchctl load ~/Library/LaunchAgents/com.monitor.agent.plist`

### Linux / Raspberry Pi (systemd)

Create `/etc/systemd/system/monitor-agent.service`:

```ini
[Unit]
Description=System Monitor Agent
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/agent/agent.py --config /path/to/agent/config.yaml
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Then: `sudo systemctl enable --now monitor-agent`

### Windows (Task Scheduler)

Use Task Scheduler to run `python agent.py --config config.yaml` at login with "Run whether user is logged in or not".

---

## Dashboard tip — saving your API key

To enable the "Dismiss" button on alerts, paste this once in your browser console:

```js
localStorage.setItem('monitor_api_key', 'your-api-key-here');
```

---

## Security notes

- The API key protects the ingest endpoint. The read endpoints (dashboard data) are public — add auth middleware if you need private data.
- Run the agent with a normal user account. For full failed-login log access on Linux, you may need to run as root or add the user to the `adm` group.
- All communication should use HTTPS in production (Render handles this automatically).
