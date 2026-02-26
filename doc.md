# QiCore – Setup CI/CD con GitHub Actions + Cloud Run (WIF)

Este documento describe la configuración completa de CI/CD para desplegar QiCore automáticamente en Google Cloud Run usando GitHub Actions y Workload Identity Federation (sin llaves).

---

# Verificar entorno gcloud

```bash
gcloud --version
gcloud auth login --force   # login cuenta Google (symmtec.investigacion para QiCore)
gcloud config set project qicore-api
```

Verificar proyecto activo:

```bash
gcloud config get-value project
```

Debe devolver:

```
qicore-api
```

---

# Habilitar APIs necesarias

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com \
  sts.googleapis.com
```

---

# Crear Service Account (Deployer)

## Variables

```bash
PROJECT_ID="qicore-api"
SA_NAME="qicore-deployer"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
```

## Crear Service Account

```bash
gcloud iam service-accounts create "${SA_NAME}" \
  --project "${PROJECT_ID}" \
  --display-name "QiCore GitHub Deployer"
```

## Asignar Roles mínimos

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser"
```

## Mostrar email (usar como Secret en GitHub)

```bash
echo "DEPLOY_SA_EMAIL=${SA_EMAIL}"
```

---

# Crear Workload Identity Federation (WIF)

## Variables

```bash
PROJECT_ID="qicore-api"
PROJECT_NUMBER="841451822292"

GITHUB_OWNER="DTakhion"
GITHUB_REPO="QiCore"

POOL_ID="github-pool"
PROVIDER_ID="github-provider"

SA_EMAIL="qicore-deployer@qicore-api.iam.gserviceaccount.com"
```

## Crear Workload Identity Pool

```bash
gcloud iam workload-identity-pools create "${POOL_ID}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --display-name="GitHub Actions Pool"
```

## Crear Provider OIDC

```bash
gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL_ID}" \
  --display-name="GitHub Actions Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.actor=assertion.actor" \
  --attribute-condition="attribute.repository=='${GITHUB_OWNER}/${GITHUB_REPO}'"
```

## Permitir impersonación del Service Account

```bash
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_OWNER}/${GITHUB_REPO}"
```

## Obtener WIF_PROVIDER (usar como Secret en GitHub)

```bash
WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
echo "WIF_PROVIDER=${WIF_PROVIDER}"
echo "DEPLOY_SA_EMAIL=${SA_EMAIL}"
```

---

# Crear Artifact Registry (Docker)

```bash
gcloud artifacts repositories create qicore \
  --project=qicore-api \
  --location=us-central1 \
  --repository-format=docker \
  --description="QiCore Docker images"
```

> Si devuelve `ALREADY_EXISTS`, el repositorio ya existe y no es error.

---

# Configurar Secrets en GitHub

En el repositorio:

**Settings → Secrets and variables → Actions → New repository secret**

Crear:

- `WIF_PROVIDER`
- `DEPLOY_SA_EMAIL`

---

# Crear Workflow GitHub Actions

Crear el archivo:

```
.github/workflows/deploy-cloudrun.yml
```

Contenido:

```yaml
name: Deploy QiCore to Cloud Run

on:
  push:
    branches: ["main", "dev"]

permissions:
  contents: read
  id-token: write

env:
  PROJECT_ID: qicore-api
  PROJECT_NUMBER: "841451822292"
  REGION: us-central1
  SERVICE: qicore-api
  AR_REPO: qicore
  IMAGE: us-central1-docker.pkg.dev/qicore-api/qicore/qicore-api

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Auth to Google Cloud (WIF)
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.DEPLOY_SA_EMAIL }}

      - name: Setup gcloud
        uses: google-github-actions/setup-gcloud@v2

      - name: Build & Push Docker image
        run: |
          gcloud auth configure-docker $REGION-docker.pkg.dev --quiet
          docker build -t "$IMAGE:${GITHUB_SHA}" .
          docker push "$IMAGE:${GITHUB_SHA}"

      - name: Deploy to Cloud Run
        uses: google-github-actions/deploy-cloudrun@v2
        with:
          service: ${{ env.SERVICE }}
          region: ${{ env.REGION }}
          image: ${{ env.IMAGE }}:${{ github.sha }}
```

---

# Resultado Final

Cada vez que hagamos:

```bash
git push
```

A `dev` o `main`:

- Se construye la imagen Docker
- Se sube a Artifact Registry
- Se despliega automáticamente en Cloud Run
- Se crea una nueva revisión en producción
