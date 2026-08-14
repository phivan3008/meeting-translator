# Local Development and Version Control Workflow

## Sử dụng Git

Kể từ 2026-08-14, project này được theo dõi bằng Git, remote `origin` tại
`https://github.com/phivan3008/meeting-translator.git`, branch `master`.

Claude được phép:

- Chạy `git status`, `git diff`, `git log`, `git add`, `git commit`,
  `git push` tới `origin/master`.
- Commit tại các mốc hợp lý (kết thúc một phase, một cập nhật file theo
  dõi thao tác thủ công, một bugfix) thay vì sau mỗi lần sửa file.
- Push tới `origin/master` ngay sau khi commit, trừ khi người dùng yêu
  cầu khác cho một thay đổi cụ thể.

Claude vẫn không được, trừ khi người dùng yêu cầu rõ ràng cho thao tác cụ
thể đó:

- `push --force`, `reset --hard`, `rebase -i`, xóa branch, hoặc bỏ qua
  hook (`--no-verify`).
- Dựa vào Git để thay thế snapshot local -- cả hai được duy trì song
  song, xem phần "Quản lý thay đổi local" bên dưới.

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
