# Kuro Command Center Rollback

Stop only the physical KCC service:

```bash
sudo systemctl stop kuro-command-center
sudo systemctl disable kuro-command-center
sudo systemctl daemon-reload
```

The monorepo fallback remains at:

```text
/home/kuro/projects/kuro-command-center
```

KCC data is isolated under:

```text
/home/kuro/data/command-center
```

Do not copy KCC operational state into KRC research stores during rollback.
