# Deployment Guide

## Production Deployment with Docker

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Production `.env.prod` file configured

> Tip: The application auto-selects the env file to read based on `APP_ENV` / `ENV`. You can override it by setting `ENV_FILE` (e.g. `ENV_FILE=.env.prod`). When using Docker Compose, `--env-file` still controls what compose injects, while `ENV_FILE` is used by the Python app directly.

Note: If `APP_ENV` is provided only inside a `.env.*` file, the app cannot read it to auto-select that `.env.*` file. To avoid the chicken-and-egg problem, set `APP_ENV` externally (in the environment or through your CI/docker compose `environment` entries) or use `ENV_FILE` to explicitly specify which file to load.

### Quick Deploy

````bash


# 2. Deploy
make docker-prod-up

If you need to run production locally without Docker, you can use:

```bash
# Run the app with the production env file
make run-prod
# Or explicitly
ENV_FILE=.env.prod APP_ENV=production make run
````

````

That's it! Your API is now running at http://localhost:8000

### Step-by-Step Deployment

#### 1. Prepare Environment

```bash
# Copy and configure production environment
cp .env.example .env.prod

# Edit with production values
nano .env.prod
````

Required variables:

```env
# Environment (CRITICAL)
ENV=production              # MUST be 'production'
DEBUG=False                # MUST be False for security
APP_ENV=production         # Disables test bypasses

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@prod-host:5432/crypalgos

# JWT Secrets (generate with: openssl rand -hex 32)
ACCESS_TOKEN_SECRET_KEY=<64-char-cryptographic-secret>
REFRESH_TOKEN_SECRET_KEY=<64-char-cryptographic-secret>
JWT_ALGORITHMS=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_MINUTES=10080

# Email Service
RESEND_API_TOKEN=re_production_key
RESEND_FROM_EMAIL=noreply@yourdomain.com
RESEND_FROM_NAME=CrypAlgos
```

#### 2. Build Image

```bash
# Build production image
docker build -t crypalgos-api:latest .

# Check image size (should be ~182MB)
docker images | grep crypalgos-api
```

#### 3. Run Containers

```bash
# Start all services with production env file
docker-compose --env-file .env.prod up -d

# Check health
docker ps
```

#### 4. Apply Migrations

```bash
# Run database migrations
docker-compose exec api alembic upgrade head
```

#### 5. Verify Deployment

```bash
# Check logs
docker-compose logs -f api

# Test endpoint
curl http://localhost:8000/
```

## Docker Configuration

### Production vs Development

**Production (`Dockerfile`)**

- Multi-stage build for minimal size
- Uses uv for dependency management
- Runs as non-root user
- Health checks included
- Final image: ~182MB

**Development (`Dockerfile.dev`)**

- Single-stage build
- Includes dev dependencies
- Hot-reload enabled
- Larger image: ~300MB

### Environment Variables

| Variable          | Description                          | Required | Default |
| ----------------- | ------------------------------------ | -------- | ------- |
| `APP_ENV`         | Environment (production/development) | Yes      | -       |
| `DEBUG`           | Enable debug mode                    | No       | false   |
| `DATABASE_URL`    | PostgreSQL connection string         | Yes      | -       |
| `SECRET_KEY`      | Application secret key               | Yes      | -       |
| `ALLOWED_ORIGINS` | CORS allowed origins                 | No       | []      |
| `LOG_LEVEL`       | Logging level                        | No       | INFO    |

## Deployment Checklist

Before deploying to production:

- [ ] All tests passing (`make check`)
- [ ] `.env.prod` configured with production values
- [ ] `SECRET_KEY` is strong and unique
- [ ] `DEBUG=false` in production
- [ ] Database backups configured
- [ ] SSL/TLS certificates ready
- [ ] Monitoring/logging configured

## Cloud Deployment

### AWS ECS

```bash
# Build and push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

docker tag crypalgos-api:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/crypalgos-api:latest

docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/crypalgos-api:latest
```

### Google Cloud Run

```bash
# Build and deploy
gcloud builds submit --tag gcr.io/<project-id>/crypalgos-api

gcloud run deploy crypalgos-api \
  --image gcr.io/<project-id>/crypalgos-api \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

### Azure Container Instances

```bash
# Create and deploy
az container create \
  --resource-group myResourceGroup \
  --name crypalgos-api \
  --image <registry>.azurecr.io/crypalgos-api:latest \
  --dns-name-label crypalgos-api \
  --ports 8000
```

## Database Management

### Backups

```bash
# Backup database
docker-compose exec db pg_dump -U postgres crypalgos > backup_$(date +%Y%m%d).sql

# Restore from backup
cat backup_20241116.sql | docker-compose exec -T db psql -U postgres crypalgos
```

### Migrations in Production

```bash
# Check current version
docker-compose exec api alembic current

# Upgrade to latest
docker-compose exec api alembic upgrade head

# Rollback if needed
docker-compose exec api alembic downgrade -1
```

## Monitoring

### Health Checks

The container includes automatic health checks:

```yaml
healthcheck:
  test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:8000/\"]
  interval: 30s
  timeout: 3s
  retries: 3
```

Check health status:

```bash
docker ps
# Look for "healthy" in STATUS column
```

### Logs

```bash
# View all logs
docker-compose logs

# Follow API logs
docker-compose logs -f api

# Last 100 lines
docker-compose logs --tail=100 api
```

### Metrics

Access built-in metrics:

- Application logs: `docker-compose logs api`
- Database logs: `docker-compose logs db`

## Scaling

### Horizontal Scaling

```bash
# Scale to 3 instances
docker-compose up -d --scale api=3

# Use a load balancer (nginx, traefik, etc.)
```

### Vertical Scaling

Update `docker-compose.yaml`:

```yaml
services:
  api:
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: 2G
        reservations:
          cpus: "1"
          memory: 1G
```

## Security

### Best Practices

1. **Use secrets management**

   ```bash
   # Use Docker secrets or env from file
   docker-compose --env-file .env.prod up -d
   ```

2. **Run as non-root** (already configured)

   ```dockerfile
   USER appuser
   ```

3. **Keep images updated**

   ```bash
   # Regular security updates
   docker-compose pull
   docker-compose up -d
   ```

4. **Network isolation**
   ```yaml
   networks:
     frontend:
       internal: false
     backend:
       internal: true
   ```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs api

# Inspect container
docker inspect <container-id>

# Check resource usage
docker stats
```

### Database Connection Issues

```bash
# Verify database is running
docker-compose ps db

# Test connection
docker-compose exec api python -c \"import asyncpg; print('OK')\"

# Check DATABASE_URL format
echo $DATABASE_URL
```

### Performance Issues

```bash
# Check resource usage
docker stats

# Monitor database
docker-compose exec db pg_stat_activity

# Check application logs for slow queries
docker-compose logs api | grep \"slow\"
```

## Rollback Strategy

```bash
# Tag current version
docker tag crypalgos-api:latest crypalgos-api:backup-$(date +%Y%m%d)

# Deploy new version
docker-compose up -d

# If issues occur, rollback
docker tag crypalgos-api:backup-20241116 crypalgos-api:latest
docker-compose up -d
```

## CI/CD Integration

The repository includes GitHub Actions workflow that:

1. Runs tests on every push
2. Builds Docker image
3. Pushes to registry (on main branch)
4. Deploys to staging/production

See `.github/workflows/ci.yaml` for details.

## Performance Optimization

### Connection Pooling

```python
# In database configuration
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True
)
```

### Caching

```python
# Add Redis for caching
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

@app.on_event(\"startup\")
async def startup():
    redis = aioredis.from_url(\"redis://localhost\")
    FastAPICache.init(RedisBackend(redis), prefix=\"fastapi-cache\")
```

## Support

For deployment issues:

1. Check logs: `docker-compose logs`
2. Verify configuration: `docker-compose config`
3. Review documentation: `docs/`
4. Open an issue on GitHub
