# Local-Only Development Workflow

## Không sử dụng Git

Claude không được:

- Chạy lệnh `git`.
- Yêu cầu tạo repository.
- Yêu cầu commit, branch, tag, stash hoặc pull request.
- Dựa vào Git để xem thay đổi hoặc khôi phục file.

## Quản lý thay đổi local

Trước mỗi phase, Claude phải:

1. Đọc `IMPLEMENTATION_STATUS.md`.
2. Liệt kê file dự kiến tạo hoặc sửa.
3. Yêu cầu hoặc tự tạo một snapshot local bằng script trong `scripts/local_backup.py` nếu script đã tồn tại.
4. Ghi tên snapshot vào `IMPLEMENTATION_STATUS.md`.

Snapshot phải:

- Được lưu ngoài cây source chính hoặc trong thư mục `.local_backups/` bị loại khỏi packaging.
- Bỏ qua model weights, virtual environments, cache, logs, audio recordings và secrets.
- Có timestamp và phase name.
- Có file manifest và checksum.

## Trạng thái file

Claude phải cập nhật:

- `IMPLEMENTATION_STATUS.md`: phase, kiểm thử, giới hạn và bước tiếp theo.
- `MANUAL_ACTIONS.md`: các thao tác đang chờ người dùng.
- `USER_RESULTS.md`: tóm tắt kết quả do người dùng cung cấp.

## Khôi phục

Nếu phase làm hỏng hệ thống:

1. Dừng chỉnh sửa.
2. Xác định snapshot gần nhất.
3. Hướng dẫn người dùng khôi phục hoặc dùng script local nếu an toàn.
4. Không xóa snapshot cho đến khi phase kế tiếp hoàn tất.

## Quy tắc hoàn thành

Một phase có hai trạng thái xác minh:

- `LOCAL_VERIFIED`: tất cả test local khả dụng đã chạy thành công.
- `HARDWARE_VERIFIED`: người dùng đã chạy các bước Windows/GPU thủ công và cung cấp output phù hợp.

Claude không được chuyển trạng thái thành `HARDWARE_VERIFIED` chỉ dựa trên mock hoặc suy luận.
