# PST – Price Setting Tool

## Local development

1. Install and start PostgreSQL locally, then create a database named `pst`.
2. Copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml`.
3. Update `DATABASE_URL` in the local secrets file with the local database user, password, host, and port.
4. Install dependencies and run the app:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m streamlit run pst/app.py
   ```

The application creates its schema and seed data on first run.

## Deployment

GitHub contains source code and the safe example configuration only. For Streamlit Community Cloud, set `DATABASE_URL` in the app's Secrets settings using the Supabase Session Pooler URL. Do not commit `.streamlit/secrets.toml` or any database password.