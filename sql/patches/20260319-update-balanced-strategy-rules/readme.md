## Update Balanced Strategy Rules to 5-Band Hotness Model

Updates Strategy ID 2 (Balanced) rules to match the new 5-band hotness model:
- >85: NONE (very hot, skip)
- 65-85: OLTP
- 45-64: QUERY LOW
- 25-44: QUERY HIGH
- 10-24: ARCHIVE LOW
- <10: ARCHIVE HIGH

Removes BASIC and NONE rules, replaces with the full HCC tier set.
