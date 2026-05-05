## 2024-05-18 - Path Traversal bypass with startswith()
**Vulnerability:** Path validation using `path.startswith(base_dir)` is vulnerable to prefix bypasses. For example, if `base_dir` is `/data`, then `/data_backup/file.txt` will bypass the check because it starts with `/data`.
**Learning:** `os.path.commonpath` must be used along with `os.path.realpath` to properly enforce directory boundaries.
**Prevention:** Always use `os.path.commonpath([abs_path, abs_base]) == abs_base` and resolve symlinks with `os.path.realpath`.
