# Safety Model

The safety model restricts automated terminal commands, enforces path traversal validations, skips explicit directories like .env and node_modules, and blocks secret leakage. Pre-restore snapshots act as ultimate undo states.