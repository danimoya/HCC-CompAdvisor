SELECT COUNT(*) as result FROM user_constraints
WHERE constraint_name = 'CHK_HISTORY_OPERATION_STATUS'
  AND search_condition_vc LIKE '%QUEUED%'
