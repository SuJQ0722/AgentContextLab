# Compression growth: offline evidence

Geometry estimate = Σ4⌈w/28⌉⌈h/28⌉. These are estimates, NOT provider image tokens. All runs stay stopped; only sidecars/manifests read.

Examples selected by greatest number of recorded compressions per attempt, deterministic job/path tie-break.

| Cell / question / retry | Compression | Rendered messages | Generated pages | Generated geometry estimate | Retained canvas pages | Retained canvas estimate | Dropped images |
|---|---:|---:|---:|---:|---:|---:|---:|
| bc_hermes/q_048_r01/attempt_006 | 1 | 20 | 8 | 76664 | 8 | 76664 | 0 |
| bc_hermes/q_048_r01/attempt_006 | 2 | 28 | 11 | 101840 | 10 | 95680 | 1 |
| bc_hermes/q_048_r01/attempt_006 | 3 | 32 | 16 | 121972 | 10 | 85124 | 6 |
| bc_hermes/q_048_r01/attempt_006 | 4 | 37 | 20 | 156828 | 10 | 100492 | 10 |
| bc_hermes/q_048_r01/attempt_006 | 5 | 45 | 22 | 163624 | 10 | 89928 | 12 |
| bc_hermes/q_048_r01/attempt_006 | 6 | 57 | 27 | 182540 | 10 | 78044 | 17 |
| bc_hermes/q_048_r02/attempt_001 | 1 | 19 | 7 | 58856 | 7 | 58856 | 0 |
| bc_hermes/q_048_r02/attempt_001 | 2 | 27 | 12 | 109856 | 10 | 97536 | 2 |
| bc_hermes/q_048_r02/attempt_001 | 3 | 36 | 18 | 144528 | 10 | 97376 | 8 |
| bc_hermes/q_048_r02/attempt_001 | 4 | 43 | 22 | 168800 | 10 | 94880 | 12 |
| bc_hermes/q_048_r02/attempt_001 | 5 | 55 | 26 | 176144 | NA | NA | NA |
| mmbc_vera/mmbc_023_r03/attempt_006 | 1 | 18 | 3 | 23088 | 3 | 23088 | 0 |
| mmbc_vera/mmbc_023_r03/attempt_006 | 2 | 33 | 7 | 49956 | 7 | 49956 | 0 |
| mmbc_vera/mmbc_023_r03/attempt_006 | 3 | 43 | 8 | 61240 | 8 | 61240 | 0 |
| mmbc_vera/mmbc_023_r03/attempt_006 | 4 | 53 | 10 | 70684 | 10 | 70684 | 1 |

Missing wire entries do not prove that generated pages were sent. Matching uses latest preceding render completion timestamp within the same attempt. Repeated request payloads are not independent questions.

Full history rendering grows; last-10 retention caps sent image count by discarding pages rather than preserving all historical content. It also competes with native images. Native image drop is recorded and must not be described as lossless retention.

Provider usage has image_tokens for only 29 physical requests in these two cells (13 positive,16 zero). Most requests lack that breakdown; no general measured image-token growth curve can be claimed.