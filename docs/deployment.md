# Kuro Command Center Deployment

Environment file:

```text
/home/kuro/projects/kuro-command-center/.env
```

Data root:

```text
/home/kuro/data/command-center
```

Systemd example:

```text
/home/kuro/projects/kuro-command-center/deploy/systemd/kuro-command-center.service.example
```

Install after Kuro Knowledge is ready:

```bash
sudo cp /home/kuro/projects/kuro-command-center/deploy/systemd/kuro-command-center.service.example /etc/systemd/system/kuro-command-center.service
sudo systemctl daemon-reload
sudo systemctl enable kuro-command-center
sudo systemctl start kuro-command-center
```

KCC is admin-only at the application route layer. Keep it behind private networking or an authenticated reverse proxy.
