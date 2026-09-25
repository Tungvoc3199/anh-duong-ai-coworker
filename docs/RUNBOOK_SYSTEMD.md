# Ánh Dương Core — Runbook systemd

## Kiến trúc vận hành

- Production chạy bằng `anh-duong-core.service`; release và endpoint hiện hành phải lấy từ `/usr/local/libexec/anh-duong/runtime-truth`.
- `8790` chỉ là port mặc định của unit template khi không có override; không được dùng làm production truth.
- `8791`: bản DEV chạy bằng `scripts/dev.sh`.
- SQLite: `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.
- Config: `/home/thadc/.config/anh-duong-core/.env`.

## Cài lần đầu

```bash
cd "$(git rev-parse --show-toplevel)"
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

Không restart/cutover production trực tiếp từ một coding lane. Chỉ chạy restart sau
owner deploy gate và sau khi release/cutover target đã được xác minh. Khi đã được duyệt:

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
