import os
from i4g.settings import Settings

os.environ["I4G_ENV"] = "dev"
os.environ["I4G_STORAGE__STRUCTURED_BACKEND"] = "cloudsql"
os.environ["I4G_STORAGE__CLOUDSQL__INSTANCE"] = "test-instance"
os.environ["I4G_STORAGE__CLOUDSQL_INSTANCE"] = "test-instance-single"

try:
    settings = Settings()
    print(f"Backend: {settings.storage.structured_backend}", flush=True)
    print(f"Instance: {settings.storage.cloudsql_instance}", flush=True)
except Exception as e:
    print(e, flush=True)
