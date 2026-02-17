# Gmail Service

A FastAPI-based Gmail service with production-grade security and storage.

## Features

- **PostgreSQL Storage**: Tokens are stored in a database, not local files.
- **Encryption**: Access and refresh tokens are encrypted at rest using Fernet.
- **Automatic Refresh**: Tokens are automatically refreshed when expired.
- **Clean Architecture**: Separated concerns (Auth, Service, Database, Models).

## Setup

1. **Clone the repository**
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   # OR
   pip install .
   ```
3. **Set up Environment Variables**:
   Copy `.env.example` to `.env` and fill in the details.
   ```bash
   cp .env.example .env
   ```
   Required variables:
   - `DATABASE_URL`: PostgreSQL connection string (e.g. `postgresql://user:pass@localhost:5432/dbname`)
   - `FERNET_KEY`: Key for encryption. Generate one using python:
     ```python
     from cryptography.fernet import Fernet
     print(Fernet.generate_key().decode())
     ```

4. **Database Migration**:
   Run the alembic migrations to create the database tables.
   ```bash
   alembic upgrade head
   ```

5. **Run the Service**:
   ```bash
   uvicorn main:app --reload
   ```

## API Endpoints

- `GET /auth/login?user_id=...`: Start OAuth flow.
- `GET /auth/callback`: OAuth callback (handled automatically).
- `GET /email/list?user_id=...`: List emails.
- `GET /email/read?user_id=...&message_id=...`: Read specific email.
- `POST /email/send`: Send email.

## Development

- **Migrations**:
  To generic a new migration after model changes:
  ```bash
  alembic revision --autogenerate -m "Description"
  ```
