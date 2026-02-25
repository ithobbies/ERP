# ERP Water & Slurry Shop

Django + DRF проєкт для обліку змін, ТОРО та ТМЦ.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## API

- `POST /api/auth/login/`
- `GET /api/equipment/`
- `POST /api/shift-reports/`
- `PATCH /api/shift-reports/{id}/`
- `POST /api/shift-reports/{id}/approve/`
- `GET /api/dashboard/summary/`
- `GET /api/tmc/?q=<search>`
- `POST /api/tmc/writeoff/`
- `CRUD /api/maintenance-records/`

> `python manage.py runserver` автоматично виконує `migrate` перед стартом, щоб у чистому середовищі не було попередження про unapplied migrations.
