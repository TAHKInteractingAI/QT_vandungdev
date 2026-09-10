# Quy Tắc Không Tự Ý Git Commit

1. **Phạm vi áp dụng**: Mọi thao tác quản lý phiên bản Git trong dự án.
2. **Nguyên tắc cốt lõi**:
   - **TUYỆT ĐỐI KHÔNG** tự ý thực hiện lệnh `git commit` (hoặc `git commit -am`, `git commit -m`) khi chưa có yêu cầu tường minh từ người dùng.
3. **Chỉ thị bắt buộc cho Agent**:
   - Sau khi hoàn thành chỉnh sửa code, tài liệu hoặc cấu hình, chỉ được thực hiện kiểm thử và kiểm tra thay đổi (`git status`, `git diff`, `detect_changes()`).
   - Giữ nguyên các thay đổi ở working directory hoặc staging area.
   - Báo cáo kết quả công việc cho người dùng và **chỉ thực hiện `git commit` khi và chỉ khi người dùng yêu cầu rõ ràng** (ví dụ: *"commit đi"*, *"hãy commit code này"*, *"lưu commit lại"*...).
