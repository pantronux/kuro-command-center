# KRC Refocus Phase 9 Legacy QA Deactivation

Kuro Playground is now the primary KRC surface. The QA Playground runtime is
not deleted, but it is no longer a default KRC product surface because it made
the Playground feel like two separate products.

## Default KRC Behavior

```env
KURO_APP_PROFILE=krc
KURO_KRC_QA_PLAYGROUND_ENABLED=false
KURO_KRC_QA_PRODUCTIZATION_ENABLED=false
```

With those defaults:

- QA navigation is not rendered in KRC mode.
- the QA card is not rendered on the Kuro Playground landing page.
- `/api/playground/qa/*` returns `503` in KRC mode.
- legacy mode can still exercise the original QA routes.

## Optional Reactivation

The old QA runtime can be re-enabled deliberately for a future experiment:

```env
KURO_KRC_QA_PLAYGROUND_ENABLED=true
KURO_KRC_QA_PRODUCTIZATION_ENABLED=true
```

This preserves working code without letting QA dilute the Kuro Playground
research surface.
