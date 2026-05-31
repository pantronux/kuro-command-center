# Same-VM App Split Deployment

Recommended roles:

```text
KRC:       KURO_APP_ROLE=krc       port 8443
KCC:       KURO_APP_ROLE=kcc       port 8444
Knowledge: KURO_APP_ROLE=knowledge port 8088
Stack:     owned by /home/kuro/projects/kuro-stack
```

Keep the compatibility route:

```text
https://host:8443/krc-shell
```

Future-facing routes:

```text
/research        -> KRC
/command-center  -> KCC
/knowledge       -> Kuro Knowledge, preferably private/admin-only
/stack           -> Kuro Stack
```

Use the service examples under `deploy/systemd/` and the reverse proxy example under `deploy/nginx/`.
