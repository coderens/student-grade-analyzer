# GradePilot: Render to Google Cloud Run + Cloud SQL

This guide keeps the existing Flask application and PostgreSQL database design. It does not delete or change the Render deployment.

## Before starting

- Create/select a Google Cloud project and enable billing. **Cloud SQL is a paid service**; check the current pricing and choose a budget-appropriate instance before creating it.
- Keep Render running until the new app and imported records have been verified.
- Never commit database URLs, passwords, `SECRET_KEY`, SQL dumps, or service-account keys to GitHub.

## 1. Create the Google Cloud resources

In the Google Cloud Console, select the same Singapore region (`asia-southeast1`) for Cloud Run and Cloud SQL to reduce cross-region latency.

1. Enable Cloud Run, Cloud Build, Artifact Registry, Cloud SQL Admin, Secret Manager, and Cloud Storage APIs.
2. Create a Cloud SQL for PostgreSQL instance, a database named `gradepilot`, and a dedicated database user.
3. Create two Secret Manager secrets: `gradepilot-database-url` and `gradepilot-secret-key`.
4. Grant the Cloud Run service identity access to those secrets (`Secret Manager Secret Accessor`) and to Cloud SQL (`Cloud SQL Client`).

For the Cloud Run `DATABASE_URL` secret, use the Cloud SQL Unix socket form (replace the uppercase placeholders; URL-encode special characters in the username/password):

```
postgresql://DB_USER:DB_PASSWORD@/gradepilot?host=/cloudsql/PROJECT_ID:asia-southeast1:INSTANCE_NAME
```

Set `SECRET_KEY` to a long random secret. Do not use the development fallback in `app.py` in production.

## 2. Export the current Render database

Use the **external** PostgreSQL connection URL from the Render database dashboard. Do not paste it into chat or commit it to a file.

Install PostgreSQL client tools locally. In PowerShell, set the URL for this terminal session (replace the placeholder privately):

```powershell
$env:SOURCE_DATABASE_URL = "PASTE_RENDER_EXTERNAL_DATABASE_URL_HERE"
pg_dump --no-owner --no-acl --format=plain --file=gradepilot.sql "$env:SOURCE_DATABASE_URL"
```

If the local `pg_dump` version does not match the server version, install a compatible PostgreSQL client version. Keep the dump private; it contains student records and administrator account hashes.

## 3. Import into Cloud SQL

Create a private Cloud Storage bucket in the same region. Replace placeholders with your actual values:

```powershell
gcloud config set project PROJECT_ID
gcloud storage buckets create gs://UNIQUE_MIGRATION_BUCKET --location=asia-southeast1
gcloud storage cp .\gradepilot.sql.gz gs://UNIQUE_MIGRATION_BUCKET/gradepilot.sql.gz
gcloud sql import sql INSTANCE_NAME gs://UNIQUE_MIGRATION_BUCKET/gradepilot.sql.gz --database=gradepilot
```

If the import reports a permissions issue, grant the Cloud SQL instance's service agent the required access to the bucket, then retry. Verify the imported tables and row counts before switching traffic. Delete the local `gradepilot.sql` dump and the temporary bucket object when the migration is verified and no longer needed.

## 4. Deploy the app

From the repository root, deploy this branch after merging the migration files, or check out the branch locally:

```powershell
gcloud run deploy gradepilot --source . --region asia-southeast1 --add-cloudsql-instances PROJECT_ID:asia-southeast1:INSTANCE_NAME
```

In the Cloud Run service's **Variables & Secrets** settings, add secret-backed environment variables:
- `DATABASE_URL` → secret `gradepilot-database-url`, latest version
- `SECRET_KEY` → secret `gradepilot-secret-key`, latest version

Allow public invocations only if appropriate for your project; the app itself should continue to enforce administrator login. Ensure the Cloud Run service identity has the IAM permissions listed above, then redeploy.

The Dockerfile starts Gunicorn only. It intentionally does **not** run `flask init-db` on every startup because Cloud Run can start multiple instances. When restoring an existing database, its schema comes from the database dump.

## 5. Verify before switching users

- Open the Cloud Run URL and test login, dashboard, student search, add/edit/delete, and report downloads.
- Compare table row counts in Render and Cloud SQL.
- Check Cloud Run logs for database connection errors.
- Keep Render and its database intact until the new deployment is verified and you have a rollback plan.
- Once verified, plan a short write freeze for the final sync if users may edit records during migration. A one-time dump does not include writes made after that dump was taken.

## Official Google documentation

- [Deploy a Python/Flask app to Cloud Run](https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-service)
- [Connect Cloud Run to Cloud SQL for PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/connect-run)
- [Cloud SQL PostgreSQL import/export](https://docs.cloud.google.com/sql/docs/postgres/import-export)
