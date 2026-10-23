# School Information System (SIS) – backend

Django + Django REST Framework + PostgreSQL, JWT auth, role-based access, audit log.
Sized for ~15,000 students (indexed relational schema, paginated APIs, stateless API servers).

## First-time setup
    cp .env.example .env            # then edit: SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS
    docker compose build
    docker compose run --rm api python manage.py makemigrations sis   # once; commit sis/migrations/
    docker compose up -d
    docker compose exec api python manage.py createsuperuser           # then set role=admin in /admin
    docker compose exec api python manage.py test                      # run the access-control tests

Put a TLS-terminating reverse proxy (nginx/Caddy) in front; the app redirects HTTP to HTTPS in production.

## API (all under /api/, JWT: POST /api/auth/login/ -> Authorization: Bearer <token>)
students, sections, enrollments, subjects, assessments, grades, attendance, invoices, payments,
audit-log, dashboard. Extras: `POST assessments/{id}/grades/` (bulk marks), `POST attendance/mark/`,
`GET students/{id}/report-card/?term=T1`.

## Who can do what
| Role | Sees | Writes |
|---|---|---|
| admin | everything | everything |
| principal | everything, audit log, dashboard | read-only |
| teacher | students in own classes | grades for assigned class+subject; attendance as class teacher |
| accountant | all students (no medical notes) | invoices, payments |
| parent | own children only | nothing |
| student | self only | nothing |

All access rules live in `sis/access.py`. Grades, attendance, fees, payments, students and enrollments
are written to `AuditLog` (who, what, when, IP).

## Before going live (not done yet)
- Backups: nightly `pg_dump` off-site + restore drill; PostgreSQL disk encryption.
- Frontend portals (React) for students/parents/teachers/admin, using the API above.
- Data import from existing spreadsheets; SMS/email notifications; payment gateway; MFA for admins.
- Load test with ~15k seeded students; privacy-law review (e.g. India DPDP Act) of what you store.
