# Ánh Dương Core — Runbook systemd

## Kiến trúc vận hành

- `8790`: bản ổn định chạy ngầm bằng systemd.
- `8791`: bản DEV chạy bằng `scripts/dev.sh`.
- SQLite: `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.
- Config: `/home/thadc/.config/anh-duong-core/.env`.

## Cài lần đầu

```bash
cd /home/thadc/AIOS/anh-duong-core
chmod +x scripts/*.sh
./scripts/install_systemd.sh
```

## Kiểm tra

```bash
./scripts/status.sh
```

## Chạy DEV

```bash
./scripts/dev.sh
```

## Sau khi code mới đã test đạt

```bash
./scripts/restart_service.sh
```

## Xem log

```bash
journalctl -u anh-duong-core.service -f
```

## Gỡ service

```bash
./scripts/uninstall_systemd.sh
```
