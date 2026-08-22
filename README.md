# Ánh Dương AI Coworker Core

Phase 0–1 foundation for the Python “brain” service.

## Runtime paths

- Source: `/mnt/f/AIOS/anh-duong-core`
- SQLite URL: `sqlite+pysqlite:////home/thadc/.local/state/anh-duong-core/anh_duong.db`
- Human-readable data mirror: `/mnt/f/AIOS/anh-duong-data`

SQLite is deliberately stored inside the Linux filesystem, not on the NTFS-mounted F: drive.

## Setup

```bash
./scripts/setup.sh
cp .env.example ~/.config/anh-duong-core/.env
./scripts/init_db.sh
./scripts/test.sh
```

## Run

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8790
```

## Health

```bash
curl http://127.0.0.1:8790/health
curl http://127.0.0.1:8790/ready
```
