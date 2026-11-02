# Backend CI/CD Documentation

This document describes the CI/CD pipelines configured for the EMDC Backend (Django REST API).

## Overview

The backend uses **GitHub Actions** for automated checks and Docker image builds. The deployment workflow contains unconfigured templates; it does not establish where the current public site is hosted:

1. **CI Pipeline** (`ci.yml`) - Runs tests, linting, and security checks
2. **Docker Build** (`docker.yml`) - Builds and publishes Docker images
3. **Deployment** (`deploy.yml`) - Manual template that intentionally stops until a hosting provider is configured

---

## 🔄 CI Pipeline (`ci.yml`)

### Triggers
- Push to `main` or `develop` branches
- Pull requests targeting `main` or `develop`

### Jobs

#### 1. **Test**
- Spins up PostgreSQL 16 container
- Runs the Django test suite with verbosity (485 tests passed locally on October 28, 2026)
- Tests cover:
  - API endpoints
  - Security (SQL injection, XSS)
  - Transaction integrity
  - Data validation
  - Authentication & authorization
  - Helper functions
  - Management commands

```bash
python manage.py test emdcbackend.test --verbosity=2
```

**Database**: Ephemeral PostgreSQL instance (auto-destroyed after tests)

#### 2. **Lint & Code Quality**
- **Flake8**: Checks Python syntax and code style
- **Black**: Validates code formatting
- **isort**: Verifies import order

```bash
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
black --check --diff emdcbackend/
isort --check-only --diff emdcbackend/
```

These lint/format jobs currently use `continue-on-error`, so they report issues but do not block merges. The test suite, migration check, and dependency vulnerability scan are blocking checks.

#### 3. **Security Scan**
- **pip-audit**: Checks for known vulnerabilities in dependencies (blocking)
- **Bandit**: Static security analysis for Python code
- Generates security report artifact (30-day retention)

```bash
pip-audit -r requirements.txt
bandit -r emdcbackend/ -f json -o bandit-report.json
```

#### 4. **Migrations Check**
- Ensures no unapplied or missing migrations
- Runs `makemigrations --check --dry-run`
- Prevents schema drift between environments

```bash
python manage.py makemigrations --check --dry-run --verbosity 2
```

---

## 🐳 Docker Build Pipeline (`docker.yml`)

### Triggers
- Push to `main` branch
- Version tags (e.g., `v1.0.0`)
- Pull requests to `main`

### Features
- Builds production-ready Docker image (Python 3.12-slim)
- Pushes to GitHub Container Registry (ghcr.io)
- Layer caching for faster builds
- Multi-stage builds for optimized image size

### Image Tags Generated
- `main` - Latest main branch
- `v1.0.0` - Semantic version tags
- `pr-123` - Pull request builds
- `main-abc1234` - Commit SHA tags
- `latest` - Latest stable release

### Registry
```
ghcr.io/emdc-fall-2025/backend:latest
```

---

## 🚀 Deployment Pipeline (`deploy.yml`)

### Triggers
- Manual dispatch via GitHub UI only
- This workflow does not deploy automatically when code is pushed.

### Workflow Steps

#### 1. **Pre-Deployment Tests**
Runs full test suite before deployment to ensure stability.

#### 2. **Deployment provider not configured**
The provider examples below are commented templates. The workflow intentionally stops with an error after tests until the department chooses a host and configures its deployment method and secrets. It does not currently deploy to production or staging.

Available provider examples include:

##### **Option 1: DigitalOcean App Platform**
```yaml
- name: Deploy to DigitalOcean
  uses: digitalocean/app_action@main
```

**Required Secrets:**
- `DIGITALOCEAN_ACCESS_TOKEN`

##### **Option 2: VPS via SSH + Docker**
```yaml
- name: Deploy via SSH
  uses: appleboy/ssh-action@master
```

**Commands:**
- Pull latest code
- Rebuild Docker containers
- Run migrations
- Collect static files

**Required Secrets:**
- `SSH_HOST`
- `SSH_USERNAME`
- `SSH_PRIVATE_KEY`
- `SSH_PORT` (optional)

##### **Option 3: Heroku**
```yaml
- name: Deploy to Heroku
  uses: akhileshns/heroku-deploy@v3.12.14
```

**Required Secrets:**
- `HEROKU_API_KEY`
- `HEROKU_EMAIL`

##### **Option 4: AWS ECS/Fargate**
- Builds and pushes to Amazon ECR
- Updates ECS service for zero-downtime deployment

**Required Secrets:**
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

##### **Option 5: Rsync + Systemd**
- Deploys to traditional Linux server
- Uses systemd service management

**Required Secrets:**
- `SSH_HOST`
- `SSH_USERNAME`
- `SSH_PRIVATE_KEY`

#### 3. **Health Check template**
After a real provider is configured, post-deployment verification should:
- Waits 30 seconds for service startup
- Calls `/api/health/` endpoint
- Fail the workflow if the service is unhealthy

---

## 🔐 Required Secrets

Configure these secrets in your GitHub repository settings:

### **Repository Secrets** (Settings → Secrets and variables → Actions)

#### Database & Django
- `DJANGO_SECRET_KEY` - Django secret key (production)
- `POSTGRES_DB` - Database name
- `POSTGRES_USER` - Database username
- `POSTGRES_PASSWORD` - Database password
- `POSTGRES_HOST` - Database host
- `POSTGRES_PORT` - Database port (default: 5432)

#### Email (Optional)
- `RESEND_API_KEY` - Resend API key for emails
- `EMAIL_HOST_USER` - SMTP username
- `DEFAULT_FROM_EMAIL` - From email address

#### Hosting Provider (choose one)
- **DigitalOcean**: `DIGITALOCEAN_ACCESS_TOKEN`
- **Heroku**: `HEROKU_API_KEY`, `HEROKU_EMAIL`
- **AWS**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- **SSH/VPS**: `SSH_HOST`, `SSH_USERNAME`, `SSH_PRIVATE_KEY`, `SSH_PORT`

#### Health Check (after hosting is selected)
- `API_URL` - Deployed API URL (e.g., `https://api.example.edu`)

---

## 📋 Setup Instructions

### 1. Enable GitHub Actions
GitHub Actions is automatically enabled for this repository.

### 2. Configure Secrets
Add deployment secrets only after the department selects a hosting provider. The names above apply to the commented provider templates; the current workflow does not use them to deploy.

### 3. Set Up Database
Ensure PostgreSQL 12+ is available in your deployment environment:

```bash
# DigitalOcean/Heroku - Managed databases automatically configured
# VPS/AWS - Create database manually
createdb emdc_production
```

### 4. Configure Environments (after choosing a provider)
1. Go to **Settings → Environments**
2. Create `production` and `staging` environments
3. Add environment-specific secrets and protection rules

### 5. View Workflows
- View workflow runs in **Actions** tab
- The deployment workflow is a placeholder and intentionally fails after tests until a provider is configured. Do not treat it as a working deployment path.

---

## 🔧 Configuration Files

### Environment Variables
Create `.env` file for local development (not tracked in git):

```bash
# Database
POSTGRES_DB=emdc_dev
POSTGRES_USER=emdc_user
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Django
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=1

# Email
RESEND_API_KEY=re_xxxxx
EMAIL_HOST_USER=resend
DEFAULT_FROM_EMAIL=EMDC Contest <noreply@emdc.com>
```

### Django Settings
Production settings in `emdcbackend/settings.py`:
- `DEBUG = False` in production
- `ALLOWED_HOSTS` configured via environment
- `SESSION_COOKIE_SECURE = True` (HTTPS)
- `CSRF_COOKIE_SECURE = True` (HTTPS)
- `SECURE_SSL_REDIRECT = True` by default when `DEBUG=0`; set `TRUST_X_FORWARDED_PROTO=1` only if the trusted hosting proxy overwrites `X-Forwarded-Proto` with the original HTTPS protocol.
- Set `SECURE_HSTS_SECONDS` only after confirming HTTPS works on every hostname you intend to protect. For example, use `31536000` for one year after the HTTPS setup has been verified. `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD` are off by default and should be enabled only after confirming every affected subdomain is ready.

---

## 🧪 Running Tests Locally

### All Tests
```bash
cd emdcbackend
python manage.py test emdcbackend.test
```

### Specific Test File
```bash
python manage.py test emdcbackend.test.test_auth
python manage.py test emdcbackend.test.test_security
```

### With Coverage
```bash
pip install coverage
coverage run --source='.' manage.py test emdcbackend.test
coverage report
coverage html  # Generate HTML report
```

### Verbose Output
```bash
python manage.py test emdcbackend.test --verbosity=2
```

---

## 🏗️ Build & Deploy Manually

### Docker Build
```bash
docker build -t emdc-backend:latest .
docker run -p 7004:7004 \
  -e POSTGRES_HOST=localhost \
  -e POSTGRES_DB=emdc \
  -e POSTGRES_USER=emdc \
  -e POSTGRES_PASSWORD=password \
  emdc-backend:latest
```

### Production Deployment (VPS)
```bash
# Pull latest code
git pull origin main

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Restart service
sudo systemctl restart emdc-backend
```

---

## 📊 Monitoring

### Workflow Status
- **Actions Tab**: View all workflow runs
- **Commit Status**: CI checks on each commit
- **Pull Requests**: Test results on PR page

### Artifacts
- Security reports stored for 30 days
- Download from: Actions → Workflow Run → Artifacts

### Logs
- Django logs via `python manage.py runserver`
- Production logs: `journalctl -u emdc-backend -f`

---

## 🐛 Troubleshooting

### Tests Failing
1. Check PostgreSQL is running
2. Verify database credentials
3. Ensure migrations are applied: `python manage.py migrate`
4. Review test output for specific failures

### Migration Errors
```bash
# Reset migrations (development only!)
python manage.py migrate --fake emdcbackend zero
python manage.py migrate emdcbackend

# Check for conflicts
python manage.py makemigrations --check
```

### Docker Build Fails
1. Verify `requirements.txt` is complete
2. Check Dockerfile syntax
3. Ensure PostgreSQL dependencies are installed

### Deployment Fails
1. Check secrets are configured correctly
2. Verify database is accessible
3. Review deployment logs
4. Check health endpoint: `curl https://api.emdc.com/api/health/`

---

## 🔒 Security Best Practices

### Secrets Management
- ✅ Never commit secrets to git
- ✅ Use GitHub Secrets for CI/CD
- ✅ Rotate secrets regularly
- ✅ Use different secrets for staging/production

### Database
- ✅ Use strong passwords (16+ characters)
- ✅ Restrict database access by IP
- ✅ Enable SSL for database connections
- ✅ Regular backups (automated)

### Django
- ✅ `DEBUG = False` in production
- ✅ Use HTTPS (SSL certificate)
- ✅ Configure `ALLOWED_HOSTS` properly
- ✅ Keep dependencies updated

---

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Django Deployment Checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)

---

## 🤝 Contributing

When modifying CI/CD:
1. Test in feature branch first
2. Update this documentation
3. Run full test suite locally
4. Notify team of new secrets/requirements
5. Test deployment to staging before production

