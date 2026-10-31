-- Т35: критичните събития приемат kind 'geofence' (възел напусна зоната).

ALTER TABLE critical_events DROP CONSTRAINT critical_events_kind_check;
ALTER TABLE critical_events ADD CONSTRAINT critical_events_kind_check
    CHECK (kind IN ('battery', 'deadletter', 'silence', 'geofence'));
