# Production Deployment Checklist

## ✅ Code Quality
- [x] All tests passing (76/76 - 100%)
- [x] Code formatted and linted
- [x] No console.log or debug statements in production code
- [x] Error handling implemented

## 🔐 Security Configuration

### Environment Variables (CRITICAL - Must Set in Production)
```bash
# Environment
ENV=production  # or APP_ENV=production
DEBUG=False

# Database (Production PostgreSQL)
DATABASE_URL=postgresql+asyncpg://prod_user:SECURE_PASSWORD@prod-host:5432/prod_db

# JWT Secrets (MUST CHANGE - Use strong random values)
ACCESS_TOKEN_SECRET_KEY=<GENERATE-256-BIT-RANDOM-KEY>
REFRESH_TOKEN_SECRET_KEY=<GENERATE-256-BIT-RANDOM-KEY>
JWT_ALGORITHMS=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_MINUTES=10080  # 7 days

# Email Service (Resend)
RESEND_API_TOKEN=<YOUR-PRODUCTION-RESEND-API-KEY>
RESEND_FROM_EMAIL=noreply@yourdomain.com
RESEND_FROM_NAME=Your Production App Name
```

### Generate Secure Keys
```bash
# Generate secure JWT secrets (run these and use the output)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # ACCESS_TOKEN_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # REFRESH_TOKEN_SECRET_KEY
```

## 🗄️ Database

### Pre-Deployment
- [ ] Production database created
- [ ] Database credentials secured (use environment variables, not hardcoded)
- [ ] Run migrations on production database:
  ```bash
  alembic upgrade head
  ```
- [ ] Database backups configured
- [ ] Connection pooling configured for production load

### Verify Database Connection
```bash
# Test connection (without running full app)
python3 -c "from app.config.settings import settings; print(settings.database_url)"
```

## 🚀 Deployment Platform Configuration

### Docker (if using)
- [ ] Use multi-stage builds for smaller images
- [ ] Don't include test dependencies in production image
- [ ] Set `ENV=production` in Dockerfile
- [ ] Use non-root user in container
- [ ] Health check endpoint configured

### Cloud Platform (AWS/Azure/GCP/etc.)
- [ ] Set all environment variables in platform secrets/config
- [ ] SSL/TLS certificates configured
- [ ] CORS origins restricted to your frontend domain
- [ ] Rate limiting configured
- [ ] Logging and monitoring set up

## 🔍 Final Security Checks

### CRITICAL - Verify These Settings
```bash
# 1. Ensure APP_ENV is NOT 'testing' in production
echo $APP_ENV  # Should be empty, 'production', or 'prod'

# 2. Ensure DEBUG is False
grep -r "DEBUG=True" .env.prod  # Should return nothing

# 3. Verify no test bypass is active
curl -X GET https://your-api.com/api/v1/users/me \
  -H "Authorization: Bearer invalid_token"
# Should return 401 Unauthorized, NOT 200 OK
```

### Auth Middleware Verification
- [ ] Auth middleware rejects invalid tokens (401)
- [ ] Auth middleware rejects missing tokens (401)
- [ ] Public endpoints (login, register) work without tokens
- [ ] Protected endpoints require valid JWT tokens

## 📊 Monitoring & Observability
- [ ] Application logs configured (JSON format recommended)
- [ ] Error tracking (Sentry, Rollbar, etc.) set up
- [ ] Performance monitoring enabled
- [ ] Database query monitoring
- [ ] API endpoint metrics tracked

## 🧪 Pre-Production Testing
- [ ] Run full test suite one more time:
  ```bash
  ENV_FILE=.env.test APP_ENV=testing python -m pytest tests/ -v
  ```
- [ ] Test production build locally with production-like config
- [ ] Load testing performed (if expecting high traffic)
- [ ] Security scan completed (OWASP, penetration testing)

## 🔄 CI/CD Pipeline
- [ ] Automated tests run on every commit
- [ ] Production deploys only from main/master branch
- [ ] Rollback procedure documented and tested
- [ ] Blue-green or canary deployment strategy implemented

## 📝 Documentation
- [ ] API documentation up to date (OpenAPI/Swagger)
- [ ] Deployment runbook created
- [ ] Incident response plan documented
- [ ] Backup and disaster recovery plan tested

## ⚠️ Known Issues / Tech Debt
- Auth middleware has test bypass (safe, but consider extracting to separate class)
- Session routes use manual JSONResponse instead of BaseResponseHandler (inconsistent but functional)

## 🎯 Post-Deployment Verification
After deploying, verify:
```bash
# 1. Health check
curl https://your-api.com/health

# 2. Auth works
curl -X POST https://your-api.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"identifier":"test@example.com","password":"password123"}'

# 3. Protected endpoint requires auth
curl -X GET https://your-api.com/api/v1/users/me
# Should return 401 without valid token

# 4. Monitor logs for errors
# Check your logging platform for any startup errors or warnings
```

---

## 🚨 STOP - Do Not Deploy If:
- [ ] Any environment variable is still using default/example values
- [ ] APP_ENV is set to 'testing'
- [ ] DEBUG=True in production
- [ ] Database URL points to local/test database
- [ ] JWT secrets are default values or too short
- [ ] RESEND_API_TOKEN is empty or test key
- [ ] Tests are failing
- [ ] Auth bypass can be triggered in production

---

Generated: $(date)
