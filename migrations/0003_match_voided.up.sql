-- A finished match that does not count for training or model accuracy:
-- canceled (never played), forfeit (technical result), draw.
ALTER TABLE matches
    ADD COLUMN IF NOT EXISTS voided_reason TEXT CHECK (voided_reason IN ('canceled', 'forfeit', 'draw'));
