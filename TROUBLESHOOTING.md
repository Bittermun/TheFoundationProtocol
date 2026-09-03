# TFP Demo Troubleshooting Guide

This guide helps you resolve common issues when running TFP demos and development environments.

## 🚀 Quick Start Issues

### Issue: "python demo_30sec.py" fails with encoding errors

**Symptoms:**
```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'
```

**Solution:** The demo script now handles this automatically by setting UTF-8 encoding for Windows consoles. If you still encounter issues:

```bash
# Set console encoding manually (Windows)
chcp 65001
python demo_30sec.py
```

### Issue: Port 8000 already in use

**Symptoms:**
```
ERROR: Address already in use
OSError: [Errno 48] Address already in use
```

**Solutions:**

**Option 1: Use a different port**
```bash
uvicorn tfp_demo.server:app --port 8001
```

**Option 2: Kill the process using port 8000**
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Linux/Mac
lsof -ti:8000 | xargs kill -9
```

**Option 3: Modify demo script to use different port**
Edit `demo_30sec.py` and change the port from 8000 to another available port.

---

## 🔧 Dependencies & Installation Issues

### Issue: Module not found errors

**Symptoms:**
```
ModuleNotFoundError: No module named 'uvicorn'
ModuleNotFoundError: No module named 'fastapi'
```

**Solution:**
```bash
cd tfp-foundation-protocol
pip install -r requirements.txt
```

### Issue: Permission denied during installation

**Symptoms:**
```
PermissionError: [Errno 13] Permission denied
```

**Solution:**
```bash
# Use user-level installation
pip install --user -r requirements.txt

# Or use virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Issue: SQLite database locked

**Symptoms:**
```
sqlite3.OperationalError: database is locked
```

**Solution:**
```bash
# Use in-memory database for testing
TFP_DB_PATH=:memory: python demo_30sec.py

# Or remove the lock file
rm pib.db  # Linux/Mac
del pib.db  # Windows
```

---

## 🐳 Docker Issues

### Issue: Docker compose fails to build

**Symptoms:**
```
ERROR: Couldn't connect to Docker daemon
```

**Solution:**
```bash
# Start Docker Desktop (Windows/Mac)
# Or start Docker service (Linux)
sudo systemctl start docker

# Verify Docker is running
docker ps
```

### Issue: Container exits immediately

**Symptoms:**
Container starts and exits immediately without staying running.

**Solution:**
```bash
# Check container logs
docker compose logs tfp-demo

# Rebuild with no cache
docker compose up --build --force-recreate

# Check health status
docker compose ps
```

### Issue: Volume permission errors

**Symptoms:**
```
ERROR: for tfp-demo  Cannot create container for service tfp-demo: create tfp_data: volume already exists
```

**Solution:**
```bash
# Remove existing volume
docker volume rm tfp_data

# Or use different volume name
# Edit docker-compose.yml and change volume name
```

---

## 🌐 Network & Connectivity Issues

### Issue: Server health check fails

**Symptoms:**
```
ERROR: Server failed to start
Timeout waiting for health check
```

**Solution:**
```bash
# Check if server is actually running
curl http://localhost:8000/health

# Increase timeout in demo script
# Edit demo_30sec.py, change timeout from 30 to 60

# Check server logs manually
uvicorn tfp_demo.server:app --reload
```

### Issue: API requests timeout

**Symptoms:**
```
urllib.error.URLError: <urlopen error timed out>
```

**Solution:**
```bash
# Check server is running
curl http://localhost:8000/health

# Increase timeout in api_call function
# Edit demo script, change timeout from 10 to 30

# Check firewall settings
# Ensure port 8000 is not blocked
```

### Issue: Nostr relay connection fails

**Symptoms:**
```
ERROR: Failed to connect to Nostr relay
Connection refused
```

**Solution:**
```bash
# Test without Nostr first
unset NOSTR_RELAY
uvicorn tfp_demo.server:app

# Use a different relay
NOSTR_RELAY=wss://nos.lol uvicorn tfp_demo.server:app

# Check relay status
curl https://api.nostr.band/v1/online/relays
```

---

## 💾 Database Issues

### Issue: Database corruption

**Symptoms:**
```
sqlite3.DatabaseError: database disk image is malformed
```

**Solution:**
```bash
# Backup existing database
cp pib.db pib.db.backup

# Start fresh
rm pib.db
TFP_DB_PATH=pib.db uvicorn tfp_demo.server:app

# Or use in-memory for testing
TFP_DB_PATH=:memory: uvicorn tfp_demo.server:app
```

### Issue: Migration errors

**Symptoms:**
```
ERROR: Failed to apply migration
sqlite3.OperationalError: table already exists
```

**Solution:**
```bash
# Reset database
rm pib.db
TFP_DB_PATH=pib.db uvicorn tfp_demo.server:app

# Or check migration files
ls tfp-foundation-protocol/supabase/migrations/
```

---

## 🔐 Authentication & Security Issues

### Issue: Device signature failures

**Symptoms:**
```
ERROR: Invalid device signature
401 Unauthorized
```

**Solution:**
```bash
# Ensure device is enrolled
curl -X POST http://localhost:8000/api/enroll \
  -H "Content-Type: application/json" \
  -d '{"device_id": "test-device", "puf_entropy_hex": "0123456789abcdef"}'

# Check signature generation
# Ensure HMAC-SHA256 is calculated correctly
# Message format: device_id:title or device_id:task_id
```

### Issue: Credit earning failures

**Symptoms:**
```
ERROR: Failed to earn credits
Rate limit exceeded
```

**Solution:**
```bash
# Check rate limit settings
TFP_EARN_RATE_MAX=20 TFP_EARN_RATE_WINDOW=120 uvicorn tfp_demo.server:app

# Wait for rate limit window to expire
# Default: 10 requests per 60 seconds

# Use different task IDs
# Each task_id can only be used once per device
```

---

## 🎯 Web Demo Issues

### Issue: PWA installation fails

**Symptoms:**
```
Service worker registration failed
Manifest not found
```

**Solution:**
```bash
# Ensure files are served correctly
# Check demo/ directory contains:
# - index.html
# - manifest.json
# - service-worker.js

# Check browser console for errors
# F12 > Console tab

# Clear browser cache and reload
```

### Issue: Content not displaying in web demo

**Symptoms:**
Web demo loads but content list shows empty or errors.

**Solution:**
```bash
# Check server is running
curl http://localhost:8000/api/content

# Check browser console for JavaScript errors
# F12 > Console tab

# Ensure device is enrolled
# Web demo auto-enrolls, check localStorage
# Application > Local Storage > http://localhost:8000
```

---

## 📊 Performance Issues

### Issue: Slow publish/retrieve times

**Symptoms:**
Operations take >10 seconds consistently.

**Solution:**
```bash
# Use in-memory database for testing
TFP_DB_PATH=:memory: uvicorn tfp_demo.server:app

# Check system resources
# CPU, memory, disk I/O

# Disable Nostr if not needed
unset NOSTR_RELAY

# Run performance benchmark
python benchmark_simple.py
```

### Issue: High memory usage

**Symptoms:**
Process consumes excessive memory (>1GB).

**Solution:**
```bash
# Use in-memory database instead of file-based
TFP_DB_PATH=:memory: uvicorn tfp_demo.server:app

# Check for memory leaks
# Monitor process over time

# Limit upload size
TFP_MAX_UPLOAD_BYTES=10485760 uvicorn tfp_demo.server:app  # 10MB limit
```

---

## 🧪 Test Failures

### Issue: Tests fail with database errors

**Symptoms:**
```
FAILED tests/test_demo_server.py - DatabaseError
```

**Solution:**
```bash
# Run tests with in-memory database
TFP_DB_PATH=:memory: PYTHONPATH=. python -m pytest tests/ -q

# Run specific test file
python -m pytest tests/test_demo_server.py -v

# Run with detailed output
python -m pytest tests/ -v -s
```

### Issue: Integration test failures

**Symptoms:**
```
FAILED tests/test_e2e_flow.py - Connection refused
```

**Solution:**
```bash
# Ensure server is running
uvicorn tfp_demo.server:app --reload

# Run in separate terminal
cd tfp-foundation-protocol
PYTHONPATH=. python -m pytest tests/test_e2e_flow.py

# Check test dependencies
pip install pytest pytest-asyncio
```

---

## 🔍 Debugging Tips

### Enable verbose logging

```bash
# Set log level to DEBUG
TFP_LOG_LEVEL=DEBUG uvicorn tfp_demo.server:app

# Or modify server.py temporarily
# logging.basicConfig(level=logging.DEBUG)
```

### Check server logs

```bash
# With Docker
docker compose logs -f tfp-demo

# With direct run
uvicorn tfp_demo.server:app --log-level debug
```

### Monitor API calls

```bash
# Use curl to test endpoints directly
curl -v http://localhost:8000/health
curl -v http://localhost:8000/api/status
curl -v http://localhost:8000/api/content
```

### Check database state

```bash
# SQLite command line
sqlite3 pib.db

# Inside SQLite:
.tables
.schema devices
SELECT * FROM devices;
SELECT * FROM content;
SELECT * FROM credit_ledger;
```

---

## 🆘 Getting Help

### Check documentation

- **Demo Guide**: `DEMO_GUIDE.md`
- **Integration Guide**: `tfp-foundation-protocol/docs/v3.0-integration-guide.md`
- **Security Model**: `tfp-foundation-protocol/docs/SECURITY.md`
- **Architecture**: `ARCHITECTURE.md`

### Check logs and error messages

Always provide:
- Full error message
- Steps to reproduce
- Environment details (OS, Python version)
- Relevant logs

### Community resources

- GitHub Issues: https://github.com/Bittermun/TheFoundationProtocol/issues
- Nostr: Search for #tfp tagged content
- Documentation: Check inline code comments

---

## 📋 Common Error Messages Reference

| Error Message | Common Cause | Solution |
|--------------|--------------|----------|
| `Address already in use` | Port 8000 in use | Use different port or kill process |
| `ModuleNotFoundError` | Missing dependencies | `pip install -r requirements.txt` |
| `Database is locked` | SQLite lock conflict | Use `:memory:` or remove lock file |
| `Invalid device signature` | Wrong HMAC calculation | Check message format and entropy |
| `Rate limit exceeded` | Too many requests | Wait or increase rate limits |
| `Connection refused` | Server not running | Start server first |
| `UnicodeEncodeError` | Console encoding issue | Set UTF-8 encoding |
| `Permission denied` | File permissions | Use `sudo` or fix permissions |
| `Docker daemon not running` | Docker not started | Start Docker Desktop/service |

---

## 🎯 Prevention Checklist

Before running demos, ensure:

- [ ] Python 3.8+ installed
- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] Port 8000 available (or use alternative)
- [ ] Sufficient disk space for database
- [ ] No conflicting processes
- [ ] Correct working directory
- [ ] Environment variables set (if needed)
- [ ] Docker running (if using Docker)

---

This troubleshooting guide covers the most common issues. If you encounter a problem not listed here, please check the documentation or community resources for additional help.