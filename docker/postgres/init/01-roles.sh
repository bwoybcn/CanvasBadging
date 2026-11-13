#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Development database bootstrap (runs once, on an empty data volume).
# Creates the three roles from docs/architecture/data-model.md:
#   oc_owner  - owns the schema, runs migrations and the dev seed
#   oc_app    - runtime role for api + worker, subject to row-level security
#   oc_signer - signer service, sees only schema "keys"
# Passwords here are DEVELOPMENT ONLY. Production provisions roles with its own secrets.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE oc_owner LOGIN PASSWORD '${OC_OWNER_PASSWORD:-oc_owner_dev}' CREATEROLE;
CREATE ROLE oc_app LOGIN PASSWORD '${OC_APP_PASSWORD:-oc_app_dev}' NOBYPASSRLS;
CREATE ROLE oc_signer LOGIN PASSWORD '${OC_SIGNER_PASSWORD:-oc_signer_dev}' NOBYPASSRLS;
CREATE DATABASE opencredential OWNER oc_owner;
REVOKE ALL ON DATABASE opencredential FROM PUBLIC;
GRANT CONNECT ON DATABASE opencredential TO oc_app, oc_signer;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname opencredential <<SQL
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
