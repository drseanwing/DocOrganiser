# Processor Test Error Analysis

**Test Date:** 2026-01-28
**Test Type:** Live processor test with ~30 mixed documents (unzipped)
**Environment:** Docker container

---

## Summary

The test encountered **2 distinct errors** that cascaded through the processing pipeline:

| # | Error Type | Errno | Location | Severity |
|---|-----------|-------|----------|----------|
| 1 | OSError (Device busy) | 16 | `main.py:259` | **Critical** |
| 2 | PermissionError | 13 | `main.py:444` | High |

---

## Error 1: Device or Resource Busy

### Details

| Field | Value |
|-------|-------|
| Exception | `OSError: [Errno 16] Device or resource busy` |
| Path | `/data/source` |
| Operation | `shutil.rmtree(source_dir)` |
| Location | `src/main.py:259` in `_extract_zip()` |
| Frequency | Repeated 3 times (13:47:17, 13:47:17, 13:47:31) |

### Stack Trace
```
File "/app/src/main.py", line 101, in process_zip
    await self._extract_zip(zip_path)
File "/app/src/main.py", line 259, in _extract_zip
    shutil.rmtree(source_dir)
File "/usr/local/lib/python3.11/shutil.py", line 763, in rmtree
    onerror(os.rmdir, path, sys.exc_info())
OSError: [Errno 16] Device or resource busy: '/data/source'
```

### Root Cause Analysis

The `/data/source` directory cannot be removed because:

1. **Docker Volume Mount**: In containerized environments, `/data/source` is likely a bind mount or volume. The directory itself cannot be deleted while mounted.
2. **Open File Handles**: A process may still have files open in the directory.
3. **Working Directory**: A subprocess might have `/data/source` as its current working directory.

### Proposed Fixes

**Fix 1: Clear contents instead of removing directory** (Recommended)
```python
async def _extract_zip(self, zip_path: str):
    """Extract ZIP to source directory."""
    source_dir = Path(self.settings.data_source_path)

    # Clear existing source directory contents (not the directory itself)
    if source_dir.exists():
        for item in source_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    source_dir.mkdir(parents=True, exist_ok=True)
```

**Fix 2: Use a subdirectory for extraction**
```python
source_dir = Path(self.settings.data_source_path) / f"job_{self.job_id}"
```

**Fix 3: Add retry logic with delay**
```python
import time

def safe_rmtree(path, retries=3, delay=1):
    for attempt in range(retries):
        try:
            shutil.rmtree(path)
            return
        except OSError as e:
            if e.errno == 16 and attempt < retries - 1:
                time.sleep(delay)
            else:
                raise
```

---

## Error 2: Permission Denied on Rename

### Details

| Field | Value |
|-------|-------|
| Exception | `PermissionError: [Errno 13] Permission denied` |
| Path | `/data/input/OL4-1.0.0.zip` -> `/data/input/OL4-1.0.0.zip.error` |
| Operation | `zip_file.rename()` |
| Location | `src/main.py:444` in error handling block |

### Stack Trace
```
File "/app/src/main.py", line 444, in main
    zip_file.rename(zip_file.with_suffix('.zip.error'))
File "/usr/local/lib/python3.11/pathlib.py", line 1175, in rename
    os.rename(self, target)
PermissionError: [Errno 13] Permission denied
```

### Root Cause Analysis

1. **File Permissions**: The container process doesn't have write permission to `/data/input`
2. **Read-Only Mount**: The input directory may be mounted as read-only
3. **File Lock**: The ZIP file may still be open by another process

### Proposed Fixes

**Fix 1: Check/request correct permissions in Docker**
```yaml
# docker-compose.yml
volumes:
  - ./input:/data/input:rw  # Ensure read-write
```

**Fix 2: Wrap rename in try/except with fallback**
```python
except Exception as e:
    logger.error("processing_error", error=str(e))
    try:
        zip_file.rename(zip_file.with_suffix('.zip.error'))
    except PermissionError:
        logger.warning("cannot_rename_error_file",
                      path=str(zip_file),
                      reason="Permission denied - file left as-is")
```

**Fix 3: Use status tracking instead of rename**
```python
# Track processed files in a state file or database instead
# of relying on file renames
```

---

## Queries for Investigation

### High Priority

| # | Query | Purpose |
|---|-------|---------|
| 1 | What is the Docker volume configuration for `/data/source`? | Confirm if mounted as volume |
| 2 | What user/group is the container process running as? | Check UID/GID permissions |
| 3 | Are there any background processes accessing `/data/source` during processing? | Identify competing file handles |
| 4 | What permissions does `/data/input` have in the host system? | Verify write access |

### Medium Priority

| # | Query | Purpose |
|---|-------|---------|
| 5 | Is there file monitoring (inotify/watchdog) on the data directories? | May hold handles open |
| 6 | Is the container running with read-only root filesystem? | Security setting that may affect writes |
| 7 | Are multiple processor instances running simultaneously? | Race condition possibility |

### Configuration Review Needed

- [ ] Review `docker-compose.yml` volume mounts
- [ ] Check Dockerfile USER directive and permissions
- [ ] Verify host directory ownership matches container UID
- [ ] Review any security contexts (SELinux, AppArmor)

---

## Recommended Action Items

### Immediate (Before Next Test)

1. **Modify `_extract_zip()`** to clear directory contents instead of removing the directory
2. **Add graceful error handling** for rename operations in the main loop
3. **Verify volume permissions** in docker-compose.yml

### Short-term

4. **Add logging** for directory state before rmtree operations
5. **Implement retry logic** with exponential backoff for file operations
6. **Consider job-specific subdirectories** to avoid contention

### Long-term

7. **Add pre-flight checks** for directory permissions before processing
8. **Implement proper file locking** to prevent race conditions
9. **Add health checks** for storage accessibility

---

## Test Environment Details

```
Timestamp Range: 2026-01-28T13:47:17 - 2026-01-28T13:47:31
Python Version: 3.11
Container Base: (verify from Dockerfile)
Documents: ~30 mixed types (unzipped)
Input File: OL4-1.0.0.zip
```

---

*Report generated from live test logs*
