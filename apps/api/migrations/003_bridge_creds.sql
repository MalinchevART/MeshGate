-- R2+: креденшъли за външни брокери (публичният mqtt.meshtastic.org
-- изисква потребител/парола) — nullable, само за връзките на моста

ALTER TABLE bridge_configs ADD COLUMN IF NOT EXISTS remote_username text;
ALTER TABLE bridge_configs ADD COLUMN IF NOT EXISTS remote_password text;
