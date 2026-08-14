# GPU Server Manual Workflow

## Quyền hạn

Claude Opus không được trực tiếp thao tác GPU server. Điều này bao gồm:

- Không SSH hoặc remote shell.
- Không download model trên server.
- Không copy source hoặc config lên server.
- Không cài CUDA, driver, Docker, Python package hoặc vLLM.
- Không chạy, dừng hoặc restart container hay service.
- Không thay đổi firewall, port, user, permission hoặc system service.
- Không đọc file server trực tiếp.

Claude chỉ được:

1. Chuẩn bị code và config ở máy local.
2. Soạn lệnh để người dùng tự chạy.
3. Giải thích nơi chạy, điều kiện tiên quyết, rủi ro và cách rollback.
4. Yêu cầu người dùng gửi lại output đã loại bỏ secret.
5. Phân tích output.
6. Đưa ra bước thủ công tiếp theo.

## Manual checkpoint bắt buộc

Khi cần GPU server, Claude phải tạo một mục trong `MANUAL_ACTIONS.md` theo mẫu:

```markdown
## Action ID: GPU-001

Status: WAITING_FOR_USER
Purpose: ...
Run on: GPU server
Prerequisites: ...
Safety notes: ...
Commands:
...
Expected success indicators:
...
Expected artifacts:
...
Rollback or cleanup:
...
Return to Claude:
- Exact command used
- Exit status
- Full stdout/stderr with secrets removed
- `nvidia-smi` summary if relevant
- Any observed error
```

Sau đó Claude phải dừng. Không được giả định lệnh thành công và không được tiếp tục bước phụ thuộc vào kết quả đó.

## Trình tự GPU đề xuất

1. `GPU-001`: kiểm tra hệ điều hành, GPU, driver, CUDA compatibility, dung lượng RAM và disk.
2. `GPU-002`: kiểm tra Docker/NVIDIA Container Toolkit hoặc Python environment đã chọn.
3. `GPU-003`: download Qwen3.6-27B-FP8 thủ công và ghi model revision/checksum.
4. `GPU-004`: khởi động vLLM bằng lệnh được tạo từ config local.
5. `GPU-005`: kiểm tra health và model listing.
6. `GPU-006`: gửi request dịch Nhật sang Việt.
7. `GPU-007`: gửi request dịch Việt sang Nhật.
8. `GPU-008`: chạy translation validation suite từ máy local tới endpoint.
9. `GPU-009`: cài/chạy faster-whisper trên GPU ASR.
10. `GPU-010`: chạy ASR fixture tiếng Nhật và tiếng Việt.
11. `GPU-011`: chạy end-to-end hardware test.
12. `GPU-012`: chạy benchmark latency và concurrency.

Mỗi action phụ thuộc phải chờ action trước thành công.

## Xử lý secret

- Không yêu cầu người dùng paste password, token thật, private key hoặc nội dung `.env` đầy đủ.
- Dùng placeholder trong lệnh.
- Khi gửi output, người dùng phải redact token, hostname nhạy cảm và đường dẫn chứa thông tin cá nhân nếu cần.
- Không ghi secret vào `USER_RESULTS.md`.
