CREATE TABLE sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                expires_at TEXT NOT NULL
            );
CREATE TABLE stripe_events (event_id TEXT PRIMARY KEY, created INTEGER, received_at TEXT NOT NULL);
CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                premium INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            , trial_ends_at TEXT, trial_used INTEGER NOT NULL DEFAULT 0, stripe_customer_id TEXT, stripe_subscription_id TEXT, subscription_status TEXT, subscription_plan TEXT, subscription_period_end TEXT, subscription_cancel_at_period_end INTEGER NOT NULL DEFAULT 0, synced_state TEXT, email_verified INTEGER NOT NULL DEFAULT 0, verification_token TEXT, verification_token_expires_at TEXT, reset_token TEXT, reset_token_expires_at TEXT, stripe_event_created INTEGER, last_active_day TEXT, marketing_consent INTEGER NOT NULL DEFAULT 0, marketing_consent_at TEXT, withdrawal_consent_at TEXT, withdrawal_consent_version INTEGER);
PRAGMA user_version = 1;
