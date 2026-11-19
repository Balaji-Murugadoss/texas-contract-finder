"""Create two client businesses (tenants). The businesses are examples you define;
the opportunities and awards they search are real. Prints each tenant's API key once."""
import secrets

import app_state

TENANTS = [
    dict(tenant_id="lonestar-hvac", name="Lone Star HVAC (example)", naics_codes="238220",
         state="TX", certifications="Texas HUB", employees=12,
         notes="Commercial HVAC install and repair, Dallas-Fort Worth"),
    dict(tenant_id="dfw-data", name="DFW Data Co (example)", naics_codes="541511,541512",
         state="TX", certifications="", employees=5,
         notes="Custom software, data pipelines and dashboards"),
]

if __name__ == "__main__":
    con = app_state.connect()
    for t in TENANTS:
        key = secrets.token_urlsafe(24)
        app_state.upsert_tenant(con, api_key=key, **t)
        print(f"{t['tenant_id']}: API key = {key}")
