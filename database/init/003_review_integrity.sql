ALTER TABLE review_actions
    ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT TRUE;

WITH ranked_reviews AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY analysis_run_id
               ORDER BY created_at DESC, id DESC
           ) AS review_rank
    FROM review_actions
)
UPDATE review_actions AS review
SET is_current = (ranked.review_rank = 1)
FROM ranked_reviews AS ranked
WHERE review.id = ranked.id
  AND review.is_current IS DISTINCT FROM (ranked.review_rank = 1);

DROP INDEX IF EXISTS review_actions_one_decision_idx;

CREATE UNIQUE INDEX IF NOT EXISTS review_actions_one_current_decision_idx
    ON review_actions (analysis_run_id) WHERE is_current;
