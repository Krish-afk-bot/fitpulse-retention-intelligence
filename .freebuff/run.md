# FitPulse — Preview Run Doc

Streamlit multipage app (bright fitness-SaaS theme: light page surfaces, dark
navigation rail and hero). Python 3.13, no Node toolchain.

## 1. Reproduce the artifacts

The UI reads prebuilt artifacts from `artifacts/` and the SQLite DB at
`data/processed/fitpulse.db` — both are produced by one command:

```bash
python scripts/pipeline.py
```

Inputs are the two bundled Kaggle CSVs in `data/raw/`
(`daily_gym_attendance_workout_data.csv`, `gym_members_dataset.csv`) — no
download step is needed. Outputs: `artifacts/*.json|csv`, the executive report
(`fitpulse_executive_report.md/.html`), and the SQLite DB loaded from
`sql/*.sql`. If artifacts already exist and are newer than `data/raw`, this
step can be skipped.

First-time dependency install:

```bash
pip install -r requirements.txt
```

## 2. Run the server (detached, Windows)

Port 8501 (Streamlit default) is used; check it is free first
(`netstat -ano | grep :8501`). Launch detached so it outlives the session
(stdout and stderr must go to different files):

```powershell
powershell -NoProfile -Command "(Start-Process -FilePath 'python.exe' -ArgumentList '-X','utf8','-m','streamlit','run','app/streamlit_app.py','--server.address','127.0.0.1','--server.port','8501','--server.headless','true','--browser.gatherUsageStats','false' -RedirectStandardOutput '<workspace>\.freebuff\preview.log' -RedirectStandardError '<workspace>\.freebuff\preview.log.err' -WindowStyle Hidden -PassThru).Id"
```

`-X utf8` avoids Windows code-page Unicode errors in the themed UI. Confirm
the pid is alive (`powershell -NoProfile -Command "Get-Process -Id <pid>"`)
and the URL answers (`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8501/`)
before registering the preview. Note: the Start-Process call can exceed a
30 s tool timeout while still succeeding — verify the pid rather than
retrying and spawning a second server.
