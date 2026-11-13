# Deployment

Production installation guidance (spec §18.4) is written in W8. Until then, note:

- Set `OC_ENV=production` and real values for `OC_SECRET_KEY`, `OC_SIGNER_SHARED_SECRET` and
  `SIGNER_KEK`. The services refuse to start otherwise.
- Provision the three database roles (see `docker/postgres/init/01-roles.sh` for the shape) with
  your own passwords, then run `oc migrate` as the owner role.
- Never run `oc seed` in production; it refuses to.
